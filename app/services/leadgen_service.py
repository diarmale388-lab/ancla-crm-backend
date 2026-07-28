import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.base import Contact, Message, User, PipelineStage, SenderType, ChannelType, MessageType, MessageStatus
from app.services.whatsapp import whatsapp_service
from app.services.activity import record_activity
from app.core.round_robin import assign_lead_round_robin

logger = logging.getLogger("leadgen_service")

async def process_leadgen_submission(db: Session, lead_data: Dict[str, Any]) -> Contact:
    """
    Procesa un nuevo cliente potencial de Meta Lead Ads / Formulario 'Inauguracion Showroom Armenia 2026',
    realiza el mapeo de campos, deduplica por teléfono y ejecuta RUTA A o RUTA B.
    """
    raw_name = lead_data.get("full_name") or lead_data.get("name") or lead_data.get("first_name", "")
    raw_email = lead_data.get("email", "")
    raw_phone = lead_data.get("phone_number") or lead_data.get("phone") or lead_data.get("whatsapp", "")
    raw_city = lead_data.get("city") or lead_data.get("ciudad", "")

    # Preguntas personalizadas - Extracción dinámica para cualquier formato de Meta Lead Ads
    asistencia_presencial = lead_data.get("Asistencia_Presencial") or lead_data.get("asistencia_presencial") or lead_data.get("asistencia", "")
    estado_terreno = lead_data.get("Estado_Terreno") or lead_data.get("estado_terreno") or lead_data.get("terreno", "")
    proposito_proyecto = lead_data.get("Proposito_Proyecto") or lead_data.get("proposito_proyecto") or lead_data.get("proposito", "")
    tipo_perfil = lead_data.get("Tipo_Perfil") or lead_data.get("tipo_perfil") or lead_data.get("perfil", "")

    for k, v in lead_data.items():
        k_lower = str(k).lower()
        val_str = str(v).strip()
        if not val_str:
            continue
        if any(w in k_lower for w in ["asist", "presencial", "showroom", "28 o 29", "horario de visita"]):
            asistencia_presencial = val_str
        elif any(w in k_lower for w in ["terreno", "lote", "propio"]):
            estado_terreno = val_str
        elif any(w in k_lower for w in ["proposito", "propósito", "proyecto", "glamping", "turismo"]):
            proposito_proyecto = val_str
        elif any(w in k_lower for w in ["perfil", "natural", "empresa", "visitas como"]):
            tipo_perfil = val_str

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

    if not contact:
        is_new = True
        contact = Contact(
            phone=clean_phone,
            first_name=first_name,
            last_name=last_name,
            email=raw_email.lower().strip() if raw_email else None,
            source="Meta Lead Ads - Inauguracion Showroom Armenia 2026",
            chatbot_enabled=True,
            habeas_data_authorized=True,
            habeas_data_authorized_at=datetime.utcnow()
        )
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
        contact.source = "Meta Lead Ads - Inauguracion Showroom Armenia 2026"
        db.add(contact)
        db.commit()

    # 3. Guardar Respuestas de Preguntas Personalizadas en Notas
    notes_block = (
        f"[Lead Ads Form: Formulario Inauguracion Showroom Armenia 2026]\n"
        f"📍 Ciudad: {raw_city or 'No especificada'}\n"
        f"🙋 Asistencia Presencial: {asistencia_presencial or 'No especificada'}\n"
        f"🏡 Estado Terreno: {estado_terreno or 'No especificado'}\n"
        f"🎯 Propósito Proyecto: {proposito_proyecto or 'No especificado'}\n"
        f"👤 Tipo Perfil: {tipo_perfil or 'No especificado'}"
    )

    if contact.qualification_notes:
        if "[Lead Ads Form:" not in contact.qualification_notes:
            contact.qualification_notes = f"{contact.qualification_notes}\n\n{notes_block}"
    else:
        contact.qualification_notes = notes_block

    db.add(contact)
    db.commit()

    # 4. Evaluación de la Condición (RUTA A vs RUTA B)
    asistencia_lower = str(asistencia_presencial).lower()
    city_lower = str(raw_city).lower()
    
    # Es RUTA B (Virtual / Lista de Espera VIP) si la respuesta de asistencia dice "no" o "virtual", o si está en otra ciudad fuera del eje cafetero y la asistencia está vacía
    is_ruta_b = any(token in asistencia_lower for token in ["no", "otra región", "otra region", "virtual", "lista de espera"])
    if not is_ruta_b and not asistencia_presencial:
        # Si no especificó asistencia, guiarse por ciudad
        if any(c in city_lower for c in ["bogot", "medell", "cali", "barranquilla", "cartagena", "bucaramanga", "cucuta", "ibague", "pasto"]):
            is_ruta_b = True

    is_ruta_a = not is_ruta_b

    contact_display_name = f"{contact.first_name or 'Hola'} {contact.last_name or ''}".strip()

    if is_ruta_a:
        # 🟢 RUTA A (CONFIRMÓ ASISTENCIA PRESENCIAL)
        logger.info(f"Procesando RUTA A para el lead {contact.phone} ({contact_display_name})")

        # Acción 1: Etiqueta [SHOWROOM_PRESENCIAL]
        if "[SHOWROOM_PRESENCIAL]" not in (contact.qualification_notes or ""):
            contact.qualification_notes = f"[Tags]: [SHOWROOM_PRESENCIAL]\n{contact.qualification_notes or ''}"

        # Acción 2: Asignación a Asesor Comercial Humano (Liliana León o User 1)
        user_assigned = db.query(User).filter(User.is_active == True).first()
        if user_assigned:
            contact.assigned_user_id = user_assigned.id
            agent_name = user_assigned.full_name or "Liliana León"
        else:
            agent_name = "Liliana León"

        # Marcar en Kanban en 'Contacto Inicial' o 'Showroom'
        stage = db.query(PipelineStage).filter(PipelineStage.name.ilike("%showroom%") | PipelineStage.name.ilike("%contacto%")).first()
        if stage:
            contact.pipeline_stage_id = stage.id

        db.add(contact)
        db.commit()

        # Acción 3: Mensaje Automático de Salida por WhatsApp RUTA A con Botones de Selección de DÍA (Paso 1)
        msg_ruta_a = (
            f"¡Hola {contact_display_name}! 👋 Gracias por registrarte a la Gran Inauguración de nuestro Showroom en Armenia. 🏠✨\n\n"
            f"Te invitamos cordialmente a conocer nuestras casas modulares exhibidas (Flex Home y Cápsula Linvig).\n\n"
            f"📍 **Ubicación**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n\n"
            f"Por favor selecciona el día que prefieres visitarnos:"
        )

        db_msg = Message(
            contact_id=contact.id,
            sender_type=SenderType.SYSTEM,
            channel=ChannelType.WHATSAPP,
            message_type=MessageType.TEXT,
            content=msg_ruta_a,
            status=MessageStatus.SENT
        )
        db.add(db_msg)
        db.commit()

        # Botones Táctiles Interactivos de Selección de Día (Paso 1)
        buttons = [
            {"id": "btn_day_mar28", "title": "📍 Martes 28 Julio"},
            {"id": "btn_day_mie29", "title": "📍 Miérc 29 Julio"}
        ]
        try:
            await whatsapp_service.send_interactive_buttons(
                to_phone=contact.phone,
                body_text=msg_ruta_a,
                buttons=buttons,
                header_text="ANCLA Special Projects",
                footer_text="Selecciona el día de tu preferencia",
                db=db
            )
        except Exception as e_wa:
            logger.error(f"Error enviando mensaje RUTA A por WhatsApp: {e_wa}")
            await whatsapp_service.send_text_message(to_phone=contact.phone, message_text=msg_ruta_a, db=db)

        record_activity(db, contact.id, "leadgen_workflow", f"Workflow RUTA A ejecutado: Asignada etiqueta [SHOWROOM_PRESENCIAL] y asesor {agent_name}.")

        # Emitir evento WebSocket en tiempo real para refresco instantáneo del CRM
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
        # 🔵 RUTA B (NO PUEDE ASISTIR PRESENCIAL / LISTA DE ESPERA VIP / ATENCIÓN VIRTUAL)
        logger.info(f"Procesando RUTA B para el lead {contact.phone} ({contact_display_name})")

        if "[LISTA_ESPERA_VIP]" not in (contact.qualification_notes or ""):
            contact.qualification_notes = f"[Tags]: [LISTA_ESPERA_VIP]\n{contact.qualification_notes or ''}"

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

        msg_ruta_b = (
            f"¡Hola {contact_display_name}! 👋 Gracias por registrarte en ANCLA Special Projects. 🏡✨\n\n"
            f"Hemos notado que te encuentras fuera de la región o no podrás asistir de forma presencial a nuestro Showroom en Armenia este 28 y 29 de Julio.\n\n"
            f"🌟 ¡No te preocupes! Has quedado registrado en nuestra **Lista de Espera VIP** para atención personalizada virtual a partir del **Jueves 30 de Julio**.\n\n"
            f"¿Te gustaría que vayamos agendando desde ya tu **Asesoría Virtual (Llamada 📞 / Google Meet 💻)** para presentarte nuestros modelos FLEX HOME y Cápsula Linvig?"
        )

        db_msg = Message(
            contact_id=contact.id,
            sender_type=SenderType.SYSTEM,
            channel=ChannelType.WHATSAPP,
            message_type=MessageType.TEXT,
            content=msg_ruta_b,
            status=MessageStatus.SENT
        )
        db.add(db_msg)
        db.commit()

        buttons_b = [
            {"id": "btn_virt_yes", "title": "💻 Sí, agendar virtual"},
            {"id": "btn_virt_info", "title": "ℹ️ Más información"}
        ]
        try:
            await whatsapp_service.send_interactive_buttons(
                to_phone=contact.phone,
                body_text=msg_ruta_b,
                buttons=buttons_b,
                header_text="ANCLA Special Projects",
                footer_text="Selecciona tu opción preferida",
                db=db
            )
        except Exception as e_wa:
            logger.error(f"Error enviando mensaje RUTA B por WhatsApp: {e_wa}")
            await whatsapp_service.send_text_message(to_phone=contact.phone, message_text=msg_ruta_b, db=db)

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
