import logging
from sqlalchemy.orm import Session
from app.models.base import Contact, PipelineStage
from app.core.socket_manager import manager

logger = logging.getLogger("pipeline_auto_service")

async def auto_progress_lead_stage(db: Session, contact_id: int, message_content: str):
    """
    Evalúa el contenido del mensaje enviado para mover automáticamente
    al contacto (lead) a la siguiente fase del pipeline de ventas.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        return

    # Obtener etapas disponibles
    stages = db.query(PipelineStage).all()
    stage_by_name = {s.name: s.id for s in stages}
    stage_positions = {s.id: s.position for s in stages}

    nuevo_lead_id = stage_by_name.get("Nuevo Lead")
    contacto_iniciado_id = stage_by_name.get("Contacto Iniciado")
    llamada_agendada_id = stage_by_name.get("Llamada Agendada")

    stage_changed = False
    old_stage_id = contact.pipeline_stage_id

    # 1. Progresión a "Contacto Iniciado"
    # Si la etapa actual es "Nuevo Lead" (o None), y se envía un mensaje
    if contacto_iniciado_id:
        if contact.pipeline_stage_id == nuevo_lead_id or contact.pipeline_stage_id is None:
            contact.pipeline_stage_id = contacto_iniciado_id
            stage_changed = True

    # 2. Progresión a "Llamada Agendada"
    # Si el mensaje contiene un link de calendario o intención de agendar
    if llamada_agendada_id:
        content_lower = message_content.lower()
        if "calendario_link" in content_lower or "calendly.com" in content_lower or "agend" in content_lower:
            current_position = stage_positions.get(contact.pipeline_stage_id, -1)
            target_position = stage_positions.get(llamada_agendada_id, 99)

            # Solo avanzar, nunca retroceder de fase automáticamente por mensaje
            if current_position < target_position:
                contact.pipeline_stage_id = llamada_agendada_id
                stage_changed = True

    if stage_changed:
        db.add(contact)
        db.commit()
        db.refresh(contact)
        logger.info(f"Lead {contact_id} progresado automáticamente de fase {old_stage_id} a {contact.pipeline_stage_id}")

        # Transmitir el cambio por WebSocket en tiempo real
        ws_payload = {
            "event": "lead_stage_updated",
            "data": {
                "contact_id": contact.id,
                "pipeline_stage_id": contact.pipeline_stage_id
            }
        }
        await manager.broadcast(ws_payload)
