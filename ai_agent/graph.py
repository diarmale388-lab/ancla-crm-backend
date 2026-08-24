"""
ai_agent/graph.py
-----------------
Construcción y compilación del StateGraph de LangGraph para Sofi AI.
Integra la verificación obligatoria de chatbot_enabled, el enrutamiento multi-modelo
y la gestión de memoria/sesión utilizando el teléfono como thread_id.
"""

from typing import Literal, Dict, Any
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import tools_condition

from ai_agent.state import AgentState
from ai_agent.nodes.classifier import classifier_node
from ai_agent.nodes.sales_expert import sales_expert_node
from ai_agent.nodes.simple_interaction import simple_interaction_node
from ai_agent.nodes.tool_executor import tool_executor_node


async def entry_guard_node(state: AgentState) -> Dict[str, Any]:
    """
    Nodo inicial de guardia que verifica el flag chatbot_enabled.
    """
    # Este nodo no altera el estado, solo sirve como punto de verificación de entrada
    return {}


def check_chatbot_status(state: AgentState) -> Literal["classifier_node", "__end__"]:
    """
    Arista condicional obligatoria: Si chatbot_enabled es False, el grafo finaliza inmediatamente.
    """
    if not state.get("chatbot_enabled", True):
        return END
    return "classifier_node"


def route_by_intent(state: AgentState) -> Literal["sales_expert_node", "human_handover_node"]:
    """
    Arista condicional: TODO el tráfico conversacional se enruta directamente a sales_expert_node (Claude).
    ÚNICAMENTE se enruta a human_handover_node si el cliente solicitó atención humana explícita
    (que a su vez genera un mensaje de cortesía y ejecuta la desactivación del piloto automático,
    en lugar de dejar al cliente sin respuesta).
    """
    intent = state.get("intent", "SALES_CONVERSATION")
    if intent == "HUMAN_HANDOVER" or state.get("requires_human", False):
        return "human_handover_node"
    return "sales_expert_node"


async def human_handover_node(state: AgentState) -> Dict[str, Any]:
    """
    Nodo de transferencia a un asesor humano.
    A diferencia de finalizar el grafo en silencio, este nodo:
      1. Genera un mensaje cálido de cortesía informando al cliente que un asesor lo contactará.
      2. Ejecuta la acción real de handover en el CRM (desactiva el chatbot para este chat y
         notifica al equipo comercial) mediante la herramienta `request_human_handover`.
    """
    phone = state.get("phone", "")
    user_name = (state.get("user_name") or "").strip()
    reason = "Solicitud explícita de atención humana detectada por el clasificador"

    greeting = f", {user_name}" if user_name else ""
    handover_message = (
        f"¡Entendido{greeting}! 🙌 En un momento uno de nuestros asesores de ANCLA Special Projects "
        f"se pondrá en contacto contigo directamente por este mismo medio para atenderte de forma personalizada."
    )

    try:
        from ai_agent.tools import request_human_handover
        await request_human_handover.ainvoke({"phone": phone, "reason": reason})
    except Exception:
        # Aunque falle la señalización en el CRM, el cliente NUNCA debe quedarse sin respuesta.
        pass

    return {"messages": [AIMessage(content=handover_message)], "requires_human": True}


def build_sofi_graph():
    """
    Construye y compila el StateGraph autónomo de Sofi AI.
    """
    workflow = StateGraph(AgentState)
    
    # 1. Agregar Nodos
    workflow.add_node("entry_guard", entry_guard_node)
    workflow.add_node("classifier_node", classifier_node)
    workflow.add_node("sales_expert_node", sales_expert_node)
    workflow.add_node("human_handover_node", human_handover_node)
    workflow.add_node("tools", tool_executor_node)
    
    # 2. Configurar Entrada y Guardia chatbot_enabled
    workflow.add_edge(START, "entry_guard")
    workflow.add_conditional_edges(
        "entry_guard",
        check_chatbot_status,
        {
            "classifier_node": "classifier_node",
            END: END
        }
    )
    
    # 3. Configurar Enrutamiento Directo a Claude desde Clasificador (o a Handover Humano)
    workflow.add_conditional_edges(
        "classifier_node",
        route_by_intent,
        {
            "sales_expert_node": "sales_expert_node",
            "human_handover_node": "human_handover_node"
        }
    )
    workflow.add_edge("human_handover_node", END)
    
    # 4. Configurar Enrutamiento de Herramientas (Tool Calling) desde Sales Expert
    workflow.add_conditional_edges(
        "sales_expert_node",
        tools_condition,
        {
            "tools": "tools",
            END: END
        }
    )
    
    # 5. Retorno desde Ejecutor de Herramientas hacia Sales Expert
    workflow.add_edge("tools", "sales_expert_node")

    
    # 7. Compilar con Memoria Persistente de Sesión (thread_id = phone)
    checkpointer = MemorySaver()
    compiled_graph = workflow.compile(checkpointer=checkpointer)
    
    return compiled_graph


# Instancia única reutilizable del grafo compilado
sofi_ai_agent = build_sofi_graph()
