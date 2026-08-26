"""
ai_agent/nodes/sales_expert.py
-------------------------------
Nodo experto comercial Sofi AI (sales_expert_node).
Utiliza 'anthropic/claude-3.5-sonnet' exclusivo para persuasión comercial, manejo de objeciones y empatía.
Soporta Tool Calling enlazado con las herramientas puente de ai_agent/tools.py.
"""

from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage

from ai_agent.config import ai_settings
from ai_agent.state import AgentState
from ai_agent.prompts import SALES_EXPERT_PROMPT
from ai_agent.tools import ALL_AI_TOOLS
from ai_agent.context import build_dynamic_context_str, get_sanitized_history


async def sales_expert_node(state: AgentState) -> Dict[str, Any]:
    """
    Nodo comercial principal impulsado por Claude Sonnet vía OpenRouter.
    Única voz visible para calificación, objeciones de precio/catálogo y negociación.
    """
    messages = list(state.get("messages", []))
    user_name = state.get("user_name", "")

    # 1. PREFIJO ESTÁTICO (Invariable, cacheado con 90% de descuento en Anthropic/OpenRouter con TTL extendido de 1 hora)
    static_system_message = SystemMessage(
        content=[
            {
                "type": "text",
                "text": SALES_EXPERT_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"}
            }
        ]
    )

    # 2. SUFIJO DINÁMICO COMPARTIDO (idéntico al inyectado en scheduling_node: cero divergencia de estado)
    dynamic_system_message = SystemMessage(content=build_dynamic_context_str(state))

    # Sanitización + Ventana Deslizante de Memoria Inteligente (últimos 10 a 12 mensajes)
    sanitized_history = get_sanitized_history(messages)

    prompt_messages = [static_system_message, dynamic_system_message] + sanitized_history

    api_key = ai_settings.OPENROUTER_API_KEY.strip()
    
    # Inicializar LLM vía OpenRouter con Prompt Caching de 1h y razonamiento calibrado ("low")
    llm = ChatOpenAI(
        model=ai_settings.SALES_EXPERT_MODEL,
        openai_api_key=api_key,
        openai_api_base=ai_settings.OPENROUTER_BASE_URL,
        temperature=0.3,
        max_tokens=1000,
        extra_body={"reasoning": {"effort": "low"}},
        default_headers={
            "HTTP-Referer": ai_settings.HTTP_REFERER,
            "X-Title": ai_settings.SITE_NAME,
        }
    )
    
    # Enlazar herramientas puente al modelo de ventas
    llm_with_tools = llm.bind_tools(ALL_AI_TOOLS)
    
    try:
        response = await llm_with_tools.ainvoke(prompt_messages)
        try:
            safe_text = str(response.content)[:120].encode('ascii', errors='replace').decode('ascii')
            print(f"[AI_ENGINE] Invocación LLM exitosa ({ai_settings.SALES_EXPERT_MODEL}). Respuesta obtenida: {safe_text}...")
        except Exception:
            pass
        return {"messages": [response]}
    except Exception as e:
        import traceback
        err_tb = traceback.format_exc()
        try:
            print(f"\n[FALLBACK] Excepción en sales_expert_node con modelo principal ({ai_settings.SALES_EXPERT_MODEL}): {e}")
            print(f"[FALLBACK] Intentando recuperación automática con modelo de respaldo (openai/gpt-4o-mini)...")
        except Exception:
            pass

        # Intento de rescate con modelo ultra-eficiente gpt-4o-mini
        try:
            fallback_llm = ChatOpenAI(
                model="openai/gpt-4o-mini",
                openai_api_key=api_key,
                openai_api_base=ai_settings.OPENROUTER_BASE_URL,
                temperature=0.4,
                max_tokens=350,
                default_headers={
                    "HTTP-Referer": ai_settings.HTTP_REFERER,
                    "X-Title": ai_settings.SITE_NAME,
                }
            ).bind_tools(ALL_AI_TOOLS)
            fb_response = await fallback_llm.ainvoke(prompt_messages)
            print(f"[AI_ENGINE] Recuperación exitosa con openai/gpt-4o-mini!")
            return {"messages": [fb_response]}
        except Exception as fb_err:
            print(f"[FALLBACK_ERROR] Falló también modelo de respaldo: {fb_err}")

        # Mensaje de cortesía consultivo y humano (NUNCA hablar de fallos técnicos ni de transferir a asesores externos)
        fallback_greeting = f"¡Hola {user_name}! 👋" if user_name else "¡Hola! 👋"
        fallback_message = (
            f"{fallback_greeting} Qué gusto saludarte. En ANCLA Special Projects construimos casas modulares premium con ingeniería en acero (**Flex Home** y **Cápsulas Living**). "
            f"Con mucho gusto podemos coordinar una **Asesoría Virtual** o **Llamada Telefónica** con nuestro equipo de expertos para presentarte planos y cotización. ¿En qué ciudad o municipio planeas tu proyecto? 😊🏡"
        )
        return {"messages": [AIMessage(content=fallback_message)]}
