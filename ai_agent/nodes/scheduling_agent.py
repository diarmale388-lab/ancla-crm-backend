"""
ai_agent/nodes/scheduling_agent.py
-----------------------------------
Nodo especializado en agenda (scheduling_node). Utiliza 'anthropic/claude-haiku-4.5'
vía OpenRouter para el 70% del tráfico mecánico de agendamiento (consultar horarios,
confirmar/cancelar citas, escalar horarios nocturnos), reduciendo latencia y costo
frente a Claude Sonnet sin sacrificar el tono ni las reglas de negocio.

Comparte el mismo constructor de contexto dinámico que sales_expert_node
(ai_agent/context.py) para garantizar "cero amnesia" y "cero variación de tono"
entre ambos nodos visibles (Regla de Oro de la Voz Unificada).
"""

from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage

from ai_agent.config import ai_settings
from ai_agent.state import AgentState
from ai_agent.prompts import SCHEDULING_AGENT_PROMPT
from ai_agent.tools import SCHEDULING_TOOLS
from ai_agent.context import build_dynamic_context_str, get_sanitized_history


async def scheduling_agent_node(state: AgentState) -> Dict[str, Any]:
    """
    Nodo de agenda impulsado por Claude Haiku vía OpenRouter.
    Herramientas Scoped: consultar_disponibilidad, save_appointment, cancel_appointment,
    solicitar_autorizacion_cita_nocturna.
    """
    messages = list(state.get("messages", []))
    user_name = state.get("user_name", "")

    # 1. PREFIJO ESTÁTICO (cacheado con TTL extendido de 1 hora, igual que sales_expert_node)
    static_system_message = SystemMessage(
        content=[
            {
                "type": "text",
                "text": SCHEDULING_AGENT_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"}
            }
        ]
    )

    # 2. SUFIJO DINÁMICO COMPARTIDO (idéntico al de sales_expert_node: cero divergencia de estado)
    dynamic_system_message = SystemMessage(content=build_dynamic_context_str(state))

    sanitized_history = get_sanitized_history(messages)

    prompt_messages = [static_system_message, dynamic_system_message] + sanitized_history

    api_key = ai_settings.OPENROUTER_API_KEY.strip()

    llm = ChatOpenAI(
        model=ai_settings.SCHEDULING_MODEL,
        openai_api_key=api_key,
        openai_api_base=ai_settings.OPENROUTER_BASE_URL,
        temperature=0.2,
        max_tokens=700,
        default_headers={
            "HTTP-Referer": ai_settings.HTTP_REFERER,
            "X-Title": ai_settings.SITE_NAME,
        }
    )

    llm_with_tools = llm.bind_tools(SCHEDULING_TOOLS)

    try:
        response = await llm_with_tools.ainvoke(prompt_messages)
        try:
            safe_text = str(response.content)[:120].encode('ascii', errors='replace').decode('ascii')
            print(f"[AI_ENGINE] Invocación LLM exitosa ({ai_settings.SCHEDULING_MODEL}). Respuesta obtenida: {safe_text}...")
        except Exception:
            pass
        return {"messages": [response]}
    except Exception as e:
        # Red de seguridad: ante cualquier falla del modelo scoped de agenda, delega la
        # atención completa a sales_expert_node (Claude Sonnet) en vez de dejar al cliente
        # sin respuesta o con un mensaje genérico de error técnico.
        try:
            print(f"[FALLBACK] Excepción en scheduling_agent_node con modelo ({ai_settings.SCHEDULING_MODEL}): {e}. Delegando a sales_expert_node.")
        except Exception:
            pass
        from ai_agent.nodes.sales_expert import sales_expert_node
        return await sales_expert_node(state)
