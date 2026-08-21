import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.base import Contact, Message, User, PipelineStage, SenderType, ChannelType, MessageType, MessageStatus
from app.services.whatsapp import whatsapp_service
from app.services.activity import record_activity
from app.core.round_robin import assign_lead_round_robin

from datetime import datetime, timedelta

logger = logging.getLogger("leadgen_service")

def get_dynamic_upcoming_days(count: int = 3) -> list:
    """Calcula dinámicamente los próximos días hábiles a partir de la fecha actual."""
    today = datetime.now()
    days_es = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
    months_es = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}
    
    rows = []
    added = 0
    for i in range(1, 14):
        f_date = today + timedelta(days=i)
        if f_date.weekday() == 6:  # Omitir domingos
            continue
        day_str = f"{days_es[f_date.weekday()]} {f_date.day} de {months_es[f_date.month]}"
        rows.append({
            "id": f"day_{f_date.strftime('%Y-%m-%d')}_VIRTUAL",
            "title": day_str[:24],
            "description": "Atención personalizada disponible"
        })
        added += 1
        if added >= count:
            break
    return rows


async def process_leadgen_submission(db: Session, lead_data: Dict[str, Any]) -> Contact:
    """
    Procesa un nuevo cliente potencial de Meta Lead Ads / Formulario 'Inauguracion Showroom Armenia 2026',
    realiza el mapeo de campos, deduplica por teléfono y ejecuta RUTA A o RUTA B.
    """
    raw_name = lead_data.get("full_name") or lead_data.get("name") or lead_data.get("first_name", "")
    raw_email = lead_data.get("email", "")
    raw_phone = lead_data.get("phone_number") or lead_data.get("phone") or lead_data.get("whatsapp", "")
    raw_city = lead_data.get("city") or lead_data.get("ciudad", "")

    # Preguntas personalizadas - Extracción dinámica para Campañas Meta Ads (Local vs Nacional)
    asistencia_presencial = lead_data.get("Asistencia_Presencial") or lead_data.get("asistencia_presencial") or lead_data.get("urgencia_visita") or lead_data.get("asistencia", "")
    estado_terreno = lead_data.get("Estado_Terreno") or lead_data.get("estado_terreno") or lead_data.get("terreno", "")
    proposito_proyecto = lead_data.get("Proposito_Proyecto") or lead_data.get("proposito_proyecto") or lead_data.get("proposito", "")
    tipo_perfil = lead_data.get("Tipo_Perfil") or lead_data.get("tipo_perfil") or lead_data.get("perfil", "")
    region_construccion = lead_data.get("Region_Construccion") or lead_data.get("region_construccion") or lead_data.get("region", "") or raw_city
    preferencia_contacto = lead_data.get("Preferencia_Contacto") or lead_data.get("preferencia_contacto") or lead_data.get("preferencia", "")
    form_title = lead_data.get("form_name") or lead_data.get("form_title") or lead_data.get("ad_name") or "Meta Ads Form"

    for k, v in lead_data.items():
        k_lower = str(k).lower()
        val_str = str(v).strip()
        if not val_str:
            continue
        if any(w in k_lower for w in ["urgencia", "asist", "presencial", "visita"]):
            asistencia_presencial = val_str
        if any(w in k_lower for w in ["terreno", "lote", "propio"]):
            estado_terreno = val_str
        if any(w in k_lower for w in ["proposito", "propósito", "proyecto", "glamping", "vivienda"]):
            proposito_proyecto = val_str
        if any(w in k_lower for w in ["perfil", "natural", "empresa", "inversionista"]):
            tipo_perfil = val_str
        if any(w in k_lower for w in ["region", "región", "donde construir", "dónde construir", "ciudad de construccion", "ciudad o departamento", "pensado construir"]):
            region_construccion = val_str
        if any(w in k_lower for w in ["preferencia", "videollamada", "zoom", "meet", "contacto", "asesoría personalizada", "asesoria personalizada", "prefieres recibir"]):
            preferencia_contacto = val_str

    # Sanitizar y normalizar teléfono (REGLA DE UNIFICACIÓN)
    clean_phone = re.sub(r'[^\d]', '', str(raw_phone))
    if clean_phone.startswith("0"):
        clean_phone = clean_phone[1:]
    if len(clean_phone) == 10 and clean_phone.startswith("3"):
        clean_phone = f"57{clean_phone}"

    if not clean_phone:
        logger.error("Error: leadgen_submission sin número de teléfono válido.")
        raise ValueError("Teléfono no proporcionado.")

    # 1. Separar nombre completo
    name_parts = str(raw_name).strip().split()
    first_name = name_parts[0] if name_parts else "Cliente"
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    # 2. Buscar contacto existente por teléfono (DEDUPLICACIÓN POR TELÉFONO)
    contact = db.query(Contact).filter(Contact.phone == clean_phone).first()
    is_new = False

    # Identificar si es Campaña Local o Nacional
    form_lower = str(form_title).lower()
    if "nacional" in form_lower or "virtual" in form_lower:
        campaign_type = "CAMPAÑA NACIONAL (Citas Virtuales)"
    else:
        campaign_type = "CAMPAÑA LOCAL (Showroom Armenia)"

    # Identificar canal de origen
    platform = str(lead_data.get("platform") or lead_data.get("channel") or lead_data.get("source_type") or "").lower()
    if "instagram" in platform or "ig" in platform:
        channel_name = "Instagram Ads"
    elif "facebook" in platform or "fb" in platform:
        channel_name = "Facebook Ads"
    else:
        channel_name = "Meta Lead Ads"

    channel_tag = f"[Canal: {channel_name}] | [{campaign_type}]"

    # Evaluador de Lead VIP 🔥 (< 5 min)
    urgencia_lower = str(asistencia_presencial).lower()
    terreno_lower = str(estado_terreno).lower()
    is_vip_lead = ("esta semana" in urgencia_lower or "urgente" in urgencia_lower) and ("ya tengo" in terreno_lower or "propio" in terreno_lower or "sí" in terreno_lower or "si" in terreno_lower)

    vip_tag = "[LEAD_VIP_5MIN]" if is_vip_lead else ""

    if not contact:
        is_new = True
        contact = Contact(
            phone=clean_phone,
            first_name=first_name,
            last_name=last_name,
            email=raw_email.lower().strip() if raw_email else None,
            source=f"{channel_name} - {campaign_type}",
            chatbot_enabled=True,
            habeas_data_authorized=True,
            habeas_data_authorized_at=datetime.utcnow()
        )
        # 🛡️ Dejar 'Sin Asignar' por defecto (visible únicamente para Administradores / Liliana León)
        contact.assigned_user_id = None
        db.add(contact)
        db.commit()
        db.refresh(contact)
    else:
        # Actualizar datos si no existían
        if first_name and (not contact.first_name or len(contact.first_name) < 3):
            contact.first_name = first_name
            contact.last_name = last_name
        if raw_email and not contact.email:
            contact.email = raw_email.lower().strip()
        contact.source = f"{channel_name} - {campaign_type}"
        db.add(contact)
        db.commit()

    # 3. Guardar Respuestas de Preguntas Personalizadas y Etiqueta de Canal en Notas
    notes_block = (
        f"{channel_tag} {vip_tag}\n"
        f"[Formulario: {form_title}]\n"
        f"📍 Ciudad/Región Construcción: {region_construccion or raw_city or 'No especificada'}\n"
        f"⏱️ Urgencia / Asistencia: {asistencia_presencial or 'No especificada'}\n"
        f"🏡 Estado Terreno: {estado_terreno or 'No especificado'}\n"
        f"🎯 Propósito Proyecto: {proposito_proyecto or 'No especificado'}\n"
        f"👤 Tipo Perfil: {tipo_perfil or 'No especificado'}\n"
        f"📞 Preferencia Contacto: {preferencia_contacto or 'No especificada'}"
    )

    if contact.qualification_notes:
        if "[Canal:" not in contact.qualification_notes:
            contact.qualification_notes = f"{channel_tag} {vip_tag}\n{contact.qualification_notes}\n\n{notes_block}"
    else:
        contact.qualification_notes = notes_block

    db.add(contact)
    db.commit()

    # Guardar la respuesta del formulario como un mensaje visible del cliente en el chat de WhatsApp con formato completo
    form_chat_msg = (
        f"¡Hola! Completé el formulario y me gustaría obtener más información sobre tu negocio.\n\n"
        f"¿Ya cuentas con un terreno o lote propio?: {estado_terreno or 'Sí, ya tengo lote'}\n"
        f"Full name: {first_name} {last_name or ''}\n"
        f"¿Cuándo te gustaría visitar nuestro showroom en Armenia?: {asistencia_presencial or 'Esta semana'}\n"
        f"Email: {raw_email or 'No provisto'}\n"
        f"¿Cuál es el propósito principal de tu proyecto?: {proposito_proyecto or 'Vivienda Propia o Campestre'}\n"
        f"¿Te contactas como Persona Natural o Empresa?: {tipo_perfil or 'Persona Natural'}\n"
        f"Phone number: {phone}"
    )

    db_form_msg = Message(
        contact_id=contact.id,
        sender_type=SenderType.CONTACT,
        channel=ChannelType.WHATSAPP,
        message_type=MessageType.TEXT,
        content=form_chat_msg,
        status=MessageStatus.DELIVERED
    )
    db.add(db_form_msg)
    db.commit()

    # Evaluación de retraso para saludo con disculpa si se creó antes de hoy
    now_utc = datetime.utcnow()
    is_delayed = (now_utc.date() > contact.created_at.date()) or ((now_utc - contact.created_at).total_seconds() > 14400)
    
    if is_delayed:
        greeting_prefix = f"¡Hola {first_name}! 👋 Te ofrecemos una sincera disculpa por la demora en responder a tu registro. 🙏✨\n\n"
    else:
        greeting_prefix = f"¡Hola {first_name}! 👋 Gracias por registrarte en ANCLA Special Projects. 🏠✨\n\n"

    # 4. Evaluación de la Ruta (LOCAL Presencial vs NACIONAL Virtual)
    if "nacional" in form_lower or "virtual" in form_lower:
        is_ruta_b = True
    elif "local" in form_lower or "showroom" in form_lower or "armenia" in form_lower:
        is_ruta_b = False
    else:
        # Fallback por ciudad
        asistencia_lower = str(asistencia_presencial).lower()
        city_lower = str(raw_city or region_construccion).lower()
        is_ruta_b = any(token in asistencia_lower for token in ["no", "otra región", "otra region", "virtual", "lista de espera"])
        if not is_ruta_b and not asistencia_presencial:
            if any(c in city_lower for c in ["bogot", "medell", "cali", "barranquilla", "cartagena", "bucaramanga", "cucuta", "ibague", "pasto"]):
                is_ruta_b = True

    is_ruta_a = not is_ruta_b

    contact_display_name = f"{contact.first_name or 'Hola'} {contact.last_name or ''}".strip()

    if is_ruta_a:
        # 🟢 CAMPAÑA LOCAL (SHOWROOM ARMENIA - CITAS PRESENCIALES)
        logger.info(f"Procesando CAMPAÑA LOCAL para el lead {contact.phone} ({contact_display_name})")

        if "[SHOWROOM_PRESENCIAL]" not in (contact.qualification_notes or ""):
            contact.qualification_notes = f"[Tags]: [SHOWROOM_PRESENCIAL]\n{contact.qualification_notes or ''}"

        user_assigned = db.query(User).filter(User.is_active == True).first()
        if user_assigned:
            contact.assigned_user_id = user_assigned.id
            agent_name = user_assigned.full_name or "Liliana León"
        else:
            agent_name = "Liliana León"

        stage = db.query(PipelineStage).filter(PipelineStage.name.ilike("%showroom%") | PipelineStage.name.ilike("%contacto%")).first()
        if stage:
            contact.pipeline_stage_id = stage.id

        db.add(contact)
        db.commit()

        # Invocación directa a Sofi AI para el mensaje de bienvenida inicial
        from app.services.ai_engine import ai_engine
        ai_reply = await ai_engine.generate_autopilot_reply(db, contact, form_chat_msg)
        if ai_reply:
            await whatsapp_service.send_text_message(
                to_phone=contact.phone,
                message_text=ai_reply,
                db=db
            )

        record_activity(db, contact.id, "leadgen_workflow", f"Workflow CAMPAÑA LOCAL ejecutado: Asignada etiqueta [SHOWROOM_PRESENCIAL] y asesor {agent_name}.")

        try:
            from app.routers.webhooks import manager
            ws_payload = {
                "event": "new_contact",
                "data": {
                    "id": contact.id,
                    "first_name": contact.first_name,
                    "last_name": contact.last_name,
                    "phone": contact.phone,
                    "email": contact.email,
                    "source": contact.source,
                    "qualification_notes": contact.qualification_notes,
                    "pipeline_stage_id": contact.pipeline_stage_id
                }
            }
            await manager.broadcast(ws_payload)
        except Exception as ws_err:
            logger.error(f"Error emitiendo WebSocket de nuevo contacto: {ws_err}")

    else:
        # 💻 CAMPAÑA NACIONAL (CITAS VIRTUALES / LLAMADA TELEFÓNICA)
        logger.info(f"Procesando CAMPAÑA NACIONAL para el lead {contact.phone} ({contact_display_name})")

        if "[ASESORIA_VIRTUAL_NACIONAL]" not in (contact.qualification_notes or ""):
            contact.qualification_notes = f"[Tags]: [ASESORIA_VIRTUAL_NACIONAL]\n{contact.qualification_notes or ''}"

        user_assigned = db.query(User).filter(User.is_active == True).first()
        if user_assigned:
            contact.assigned_user_id = user_assigned.id
            agent_name = user_assigned.full_name or "Liliana León"
        else:
            agent_name = "Liliana León"

        stage = db.query(PipelineStage).filter(PipelineStage.name.ilike("%contacto%") | PipelineStage.name.ilike("%nuevo%")).first()
        if stage:
            contact.pipeline_stage_id = stage.id

        db.add(contact)
        db.commit()

        # Invocación directa a Sofi AI para la bienvenida nacional
        from app.services.ai_engine import ai_engine
        ai_reply = await ai_engine.generate_autopilot_reply(db, contact, form_chat_msg)
        if ai_reply:
            await whatsapp_service.send_text_message(
                to_phone=contact.phone,
                message_text=ai_reply,
                db=db
            )

        record_activity(db, contact.id, "leadgen_workflow", f"Workflow RUTA B ejecutado: Asignada etiqueta [LISTA_ESPERA_VIP] y asesor {agent_name}.")

        try:
            from app.routers.webhooks import manager
            ws_payload = {
                "event": "new_contact",
                "data": {
                    "id": contact.id,
                    "first_name": contact.first_name,
                    "last_name": contact.last_name,
                    "phone": contact.phone,
                    "email": contact.email,
                    "source": contact.source,
                    "qualification_notes": contact.qualification_notes,
                    "pipeline_stage_id": contact.pipeline_stage_id
                }
            }
            await manager.broadcast(ws_payload)
        except Exception as ws_err:
            logger.error(f"Error emitiendo WebSocket de nuevo contacto RUTA B: {ws_err}")

    return contact
