"""
ai_agent/graph.py
-----------------
Construcción y compilación del StateGraph de LangGraph para Sofi AI.
Integra la verificación obligatoria de chatbot_enabled, el enrutamiento multi-modelo
y la gestión de memoria/sesión utilizando el teléfono como thread_id.
"""

from typing import Literal, Dict, Any
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


def route_by_intent(state: AgentState) -> Literal["sales_expert_node", "__end__"]:
    """
    Arista condicional: TODO el tráfico conversacional se enruta directamente a sales_expert_node (Claude).
    ÚNICAMENTE se redirige a END si el cliente solicitó atención humana explícita.
    """
    intent = state.get("intent", "SALES_CONVERSATION")
    if intent == "HUMAN_HANDOVER" or state.get("requires_human", False):
        return END
    return "sales_expert_node"


def build_sofi_graph():
    """
    Construye y compila el StateGraph autónomo de Sofi AI.
    """
    workflow = StateGraph(AgentState)
    
    # 1. Agregar Nodos
    workflow.add_node("entry_guard", entry_guard_node)
    workflow.add_node("classifier_node", classifier_node)
    workflow.add_node("sales_expert_node", sales_expert_node)
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
    
    # 3. Configurar Enrutamiento Directo a Claude desde Clasificador
    workflow.add_conditional_edges(
        "classifier_node",
        route_by_intent,
        {
            "sales_expert_node": "sales_expert_node",
            END: END
        }
    )
    
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
