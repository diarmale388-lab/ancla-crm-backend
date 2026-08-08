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


async def sales_expert_node(state: AgentState) -> Dict[str, Any]:
    """
    Nodo comercial principal impulsado por Claude 3.5 Sonnet vía OpenRouter.
    """
    messages = list(state.get("messages", []))
    phone = state.get("phone", "")
    user_name = state.get("user_name", "")
    meta_ads_lead_data = state.get("meta_ads_lead_data")
    
    import datetime as dt_tz
    try:
        from zoneinfo import ZoneInfo
        bogota_now = dt_tz.datetime.now(ZoneInfo("America/Bogota"))
    except Exception:
        bogota_now = dt_tz.datetime.now(dt_tz.timezone(dt_tz.timedelta(hours=-5)))
    current_time_str = bogota_now.strftime("%Y-%m-%d %I:%M %p")

    
    # Formatear contexto de formulario de Meta Ads si está presente
    lead_context_str = ""
    if meta_ads_lead_data and isinstance(meta_ads_lead_data, dict):
        lead_context_str = "\n[DATOS EXTRAÍDOS DE FORMULARIO META ADS DE ESTE CLIENTE]:\n"
        for k, v in meta_ads_lead_data.items():
            lead_context_str += f"- {k}: {v}\n"
        lead_context_str += "⚠️ REGLA: Reconoce estos datos y no le vuelvas a preguntar lo que el cliente ya respondió en el formulario."

    # Extracción de estado relacional de la BD
    contact_modality = state.get("metadata", {}).get("scheduling_state") or "NO_DEFINIDA"
    contact_has_land = state.get("metadata", {}).get("has_land", "No especificado")
    contact_location = state.get("metadata", {}).get("location", "No especificado")
    contact_active_appointment = state.get("metadata", {}).get("active_appointment", "Ninguna")

    formatted_prompt = SALES_EXPERT_PROMPT.format(
        contact_modality=contact_modality,
        contact_has_land=contact_has_land,
        contact_location=contact_location,
        contact_active_appointment=contact_active_appointment
    )

    # Construir mensaje de sistema con contexto dinámico y fecha actual
    system_content = (
        f"{formatted_prompt}\n\n"
        f"[FECHA Y HORA ACTUAL (COLOMBIA - AMERICA/BOGOTA)]: {current_time_str}\n"
        f"⚠️ NUNCA OFREZCAS DÍAS NI HORAS ANTERIORES A ESTA FECHA/HORA.\n\n"
        f"[CONTEXTO DE SESIÓN]\n- Teléfono cliente: {phone}\n- Nombre cliente: {user_name if user_name else 'No especificado aún'}"
        f"{lead_context_str}"
    )
    # Sanitización de historial para eliminar plantillas antiguas redundantes y mensajes duplicados
    try:
        from app.services.history_sanitizer import sanitize_chat_history_for_llm
        sanitized_history = sanitize_chat_history_for_llm(messages)
    except Exception:
        sanitized_history = messages

    prompt_messages = [SystemMessage(content=system_content)] + sanitized_history

    
    api_key = ai_settings.OPENROUTER_API_KEY.strip() or "sk-or-v1-dummy-key-for-testing"
    
    # Inicializar Claude 3.5 Sonnet vía OpenRouter con binding de herramientas
    llm = ChatOpenAI(
        model=ai_settings.SALES_EXPERT_MODEL,
        openai_api_key=api_key,
        openai_api_base=ai_settings.OPENROUTER_BASE_URL,
        temperature=0.4,
        max_tokens=1000,
        default_headers={
            "HTTP-Referer": ai_settings.HTTP_REFERER,
            "X-Title": ai_settings.SITE_NAME,
        }
    )
    
    # Enlazar herramientas puente al modelo de ventas
    llm_with_tools = llm.bind_tools(ALL_AI_TOOLS)
    
    print(f"\n[AI_ENGINE] Invocando LLM Sales Expert ({ai_settings.SALES_EXPERT_MODEL}) vía OpenRouter...")
    print(f"[AI_ENGINE] System Prompt (primeros 250 caracteres):\n{system_content[:250]}...")
    
    try:
        response = await llm_with_tools.ainvoke(prompt_messages)
        print(f"[AI_ENGINE] Invocación LLM exitosa. Respuesta obtenida: {str(response.content)[:120]}...")
        return {"messages": [response]}
    except Exception as e:
        import traceback
        err_tb = traceback.format_exc()
        print(f"\n[FALLBACK] Excepción en sales_expert_node ({ai_settings.SALES_EXPERT_MODEL}): {e}")
        print(f"[FALLBACK] Traceback completo:\n{err_tb}")
        # Fallback elegante si hay un fallo de API externo
        fallback_msg = AIMessage(
            content="¡Hola! En este momento estoy verificando la información en nuestro sistema. ¿Me podrías regalar un momento o indicarme tu disponibilidad de horario para atenderte?"
        )
        return {"messages": [fallback_msg]}
