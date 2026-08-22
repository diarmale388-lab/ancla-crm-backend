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

    # Determinar si es el primer mensaje del cliente o conversación en curso
    human_count = sum(1 for m in messages if getattr(m, 'type', '') == 'human' or getattr(m, 'sender_type', '') in ['contact', 'user'])
    is_first_interaction = human_count <= 1

    interaction_instruction = (
        "\n[INSTRUCCIÓN DE CONTROL DE CONVERSACIÓN - PRIMER CONTACTO]:\n"
        "⚠️ ESTE ES EL PRIMER MENSAJE QUE EL CLIENTE ENVÍA EN EL CHAT. ES ABSOLUTAMENTE OBLIGATORIO SALUDAR CÁLIDAMENTE Y DAR LA BIENVENIDA A ANCLA SPECIAL PROJECTS ANTES DE RESPONDER O AGENDAR."
        if is_first_interaction else
        "\n[INSTRUCCIÓN DE CONTROL DE CONVERSACIÓN - CONTINUACIÓN DE CHAT]:\n"
        "Este mensaje es la continuación de una conversación en curso. NO REPITAS el saludo inicial ni la bienvenida para mantener el diálogo natural."
    )

    # Recuperar Directrices Oficiales Aprobadas por Dirección General (Candados 1 y 2)
    approved_guidelines_str = ""
    try:
        from app.database import SessionLocal
        from app.models.base import AIKnowledgeApproval
        with SessionLocal() as db_session:
            approved_items = db_session.query(AIKnowledgeApproval).filter(AIKnowledgeApproval.status == "APPROVED").all()
            if approved_items:
                approved_guidelines_str = "\n[DIRECTRICES TÉCNICAS OFICIALES APROBADAS POR DIRECCIÓN GENERAL (CUMPLIMIENTO OBLIGATORIO)]:\n"
                for item in approved_items:
                    approved_guidelines_str += f"• TEMA: {item.topic}\n  - Consulta/Duda: {item.detected_question}\n  - Respuesta Oficial Autorizada: {item.official_answer}\n"
    except Exception:
        pass

    # 1. PREFIJO ESTÁTICO (Invariable, cacheado automáticamente al 50% por OpenAI / 90% por Anthropic)
    static_system_message = SystemMessage(content=SALES_EXPERT_PROMPT)

    # 2. SUFIJO DINÁMICO (Datos específicos del cliente actual y hora)
    dynamic_context_str = (
        f"[ESTADO RELACIONAL DEL CONTACTO EN POSTGRESQL]:\n"
        f"- Teléfono: {phone}\n"
        f"- Nombre cliente: {user_name if user_name else 'No especificado aún'}\n"
        f"- Modalidad elegida en BD: {contact_modality}\n"
        f"- ¿Posee lote propio?: {contact_has_land}\n"
        f"- Ubicación / Ciudad: {contact_location}\n"
        f"- Cita actualmente agendada: {contact_active_appointment}\n"
        f"- Fecha y Hora Actual (Colombia - America/Bogota): {current_time_str}\n"
        f"⚠️ NUNCA OFREZCAS DÍAS NI HORAS ANTERIORES A ESTA FECHA/HORA.\n"
        f"{approved_guidelines_str}"
        f"{lead_context_str}"
        f"{interaction_instruction}"
    )
    dynamic_system_message = SystemMessage(content=dynamic_context_str)


    # Sanitización de historial para eliminar plantillas antiguas redundantes y mensajes duplicados
    try:
        from app.services.history_sanitizer import sanitize_chat_history_for_llm
        sanitized_history = sanitize_chat_history_for_llm(messages)
    except Exception:
        sanitized_history = messages

    # Ventana Deslizante de Memoria Inteligente (últimos 10 a 12 mensajes)
    if len(sanitized_history) > 12:
        sanitized_history = sanitized_history[-12:]

    prompt_messages = [static_system_message, dynamic_system_message] + sanitized_history

    api_key = ai_settings.OPENROUTER_API_KEY.strip()
    
    # Inicializar LLM vía OpenRouter con límite de tokens optimizado
    llm = ChatOpenAI(
        model=ai_settings.SALES_EXPERT_MODEL,
        openai_api_key=api_key,
        openai_api_base=ai_settings.OPENROUTER_BASE_URL,
        temperature=0.4,
        max_tokens=350,
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
            print(f"[AI_ENGINE] Invocación LLM exitosa. Respuesta obtenida: {safe_text}...")
        except Exception:
            pass
        return {"messages": [response]}
    except Exception as e:
        import traceback
        err_tb = traceback.format_exc()
        try:
            print(f"\n[FALLBACK] Excepción en sales_expert_node ({ai_settings.SALES_EXPERT_MODEL}): {e}")
            print(f"[FALLBACK] Traceback completo:\n{err_tb}")
        except Exception:
            pass
        return {"messages": []}
