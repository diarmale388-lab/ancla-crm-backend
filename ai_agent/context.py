"""
ai_agent/context.py
--------------------
Construcción compartida del contexto dinámico inyectado a CUALQUIER nodo visible
de Claude (sales_expert_node, scheduling_node). Existe como módulo único para
garantizar "cero amnesia" y "cero variaciones de tono/estado" entre sub-agentes
(Regla de Oro de la Voz Unificada del Contrato Inviolable de Sofi AI).

LEY 2 (Calendario Determinista): las fechas se calculan y formatean en español
aquí mismo, en Python, ANTES de llegar al LLM.
"""

import datetime as dt_tz
from typing import Any, Dict, Tuple


def get_bogota_dates() -> Tuple[str, str, str]:
    """Retorna (fecha_actual_legible, fecha_manana_legible, hora_actual_str)."""
    try:
        from zoneinfo import ZoneInfo
        bogota_now = dt_tz.datetime.now(ZoneInfo("America/Bogota"))
    except Exception:
        bogota_now = dt_tz.datetime.now(dt_tz.timezone(dt_tz.timedelta(hours=-5)))

    current_time_str = bogota_now.strftime("%Y-%m-%d %I:%M %p")
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    hoy_es = f"{dias[bogota_now.weekday()]} {bogota_now.day} de {meses[bogota_now.month - 1]} de {bogota_now.year}"
    manana_dt = bogota_now + dt_tz.timedelta(days=1)
    manana_es = f"{dias[manana_dt.weekday()]} {manana_dt.day} de {meses[manana_dt.month - 1]}"
    return hoy_es, manana_es, current_time_str


def build_lead_context_str(meta_ads_lead_data: Any) -> Tuple[str, str]:
    """Retorna (lead_context_str, modalidad_preferida_str) a partir del formulario Meta Ads."""
    lead_context_str = ""
    modalidad_preferida_str = "NO_ESPECIFICADA"
    if meta_ads_lead_data and isinstance(meta_ads_lead_data, dict):
        lead_context_str = "\n[DATOS EXTRAÍDOS DE FORMULARIO META ADS DE ESTE CLIENTE]:\n"
        for k, v in meta_ads_lead_data.items():
            lead_context_str += f"- {k}: {v}\n"
        lead_context_str += "⚠️ REGLA: Reconoce estos datos y no le vuelvas a preguntar lo que el cliente ya respondió en el formulario."

        raw_modalidad = str(meta_ads_lead_data.get("modalidad_preferida") or "").upper().strip()
        if "LLAMADA" in raw_modalidad or "TELEFON" in raw_modalidad:
            modalidad_preferida_str = "LLAMADA"
        elif "PRESENCIAL" in raw_modalidad or "SHOWROOM" in raw_modalidad:
            modalidad_preferida_str = "PRESENCIAL"
        elif "VIRTUAL" in raw_modalidad:
            modalidad_preferida_str = "VIRTUAL"
    return lead_context_str, modalidad_preferida_str


def build_approved_guidelines_str() -> str:
    """Directrices oficiales aprobadas por Dirección General (Candados 1 y 2)."""
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
    return approved_guidelines_str


def build_dynamic_context_str(state: Dict[str, Any]) -> str:
    """
    Construye el bloque de contexto dinámico compartido (Estado Relacional en PostgreSQL +
    Fecha determinista + Formulario Meta Ads) que se inyecta a CUALQUIER nodo visible de Claude.
    """
    phone = state.get("phone", "")
    user_name = state.get("user_name", "")
    meta_ads_lead_data = state.get("meta_ads_lead_data")
    messages = list(state.get("messages", []))

    hoy_es, manana_es, current_time_str = get_bogota_dates()
    lead_context_str, modalidad_preferida_str = build_lead_context_str(meta_ads_lead_data)
    approved_guidelines_str = build_approved_guidelines_str()

    metadata = state.get("metadata", {}) or {}
    contact_modality = metadata.get("scheduling_state") or "NO_DEFINIDA"
    contact_has_land = metadata.get("has_land", "No especificado")
    contact_location = metadata.get("location", "No especificado")
    contact_active_appointment = metadata.get("active_appointment", "Ninguna")

    human_count = sum(1 for m in messages if getattr(m, 'type', '') == 'human' or getattr(m, 'sender_type', '') in ['contact', 'user'])
    is_first_interaction = human_count <= 1
    interaction_instruction = (
        "\n[INSTRUCCIÓN DE CONTROL DE CONVERSACIÓN - PRIMER CONTACTO]:\n"
        "⚠️ ESTE ES EL PRIMER MENSAJE QUE EL CLIENTE ENVÍA EN EL CHAT. ES ABSOLUTAMENTE OBLIGATORIO SALUDAR CÁLIDAMENTE Y DAR LA BIENVENIDA A ANCLA SPECIAL PROJECTS ANTES DE RESPONDER O AGENDAR."
        if is_first_interaction else
        "\n[INSTRUCCIÓN DE CONTROL DE CONVERSACIÓN - CONTINUACIÓN DE CHAT]:\n"
        "Este mensaje es la continuación de una conversación en curso. NO REPITAS el saludo inicial ni la bienvenida para mantener el diálogo natural."
    )

    return (
        f"[ESTADO RELACIONAL DEL CONTACTO EN POSTGRESQL]:\n"
        f"- Teléfono: {phone}\n"
        f"- Nombre cliente: {user_name if user_name else 'No especificado aún'}\n"
        f"- Modalidad elegida en BD: {contact_modality}\n"
        f"- Modalidad preferida (Formulario Meta Ads, ver Regla 25): {modalidad_preferida_str}\n"
        f"- ¿Posee lote propio?: {contact_has_land}\n"
        f"- Ubicación / Ciudad: {contact_location}\n"
        f"- Cita actualmente agendada: {contact_active_appointment}\n"
        f"- Fecha Actual (Colombia): {hoy_es} ({current_time_str})\n"
        f"- Mañana es: {manana_es}\n"
        f"⚠️ PROHIBIDO cambiar el día de la semana de una fecha. NUNCA OFREZCAS DÍAS NI HORAS ANTERIORES A ESTA FECHA/HORA.\n"
        f"⚠️ RECUERDA: LLAMADA es LLAMADA y VIRTUAL es VIRTUAL (modalidades distintas y no intercambiables). PROHIBIDO imprimir cualquier link de Google Meet.\n"
        f"{approved_guidelines_str}"
        f"{lead_context_str}"
        f"{interaction_instruction}"
    )


def get_sanitized_history(messages, max_len: int = 12):
    """Sanitiza y recorta el historial (ventana deslizante) de forma idéntica para todos los nodos visibles."""
    try:
        from app.services.history_sanitizer import sanitize_chat_history_for_llm
        sanitized_history = sanitize_chat_history_for_llm(messages)
    except Exception:
        sanitized_history = messages
    if len(sanitized_history) > max_len:
        sanitized_history = sanitized_history[-max_len:]
    return sanitized_history
