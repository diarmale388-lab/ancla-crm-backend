import logging
from sqlalchemy.orm import Session
from typing import Optional
from app.models.base import Contact, User, SystemSetting, PipelineStage
from app.services.activity import record_activity
from app.services.whatsapp import whatsapp_service
import asyncio

logger = logging.getLogger("automation_service")

async def execute_stage_change_triggers(db: Session, contact: Contact, stage_id: int, user_id: int):
    """
    Executes triggers related to stage transition.
    Rule 1: If stage is 'Propuesta Enviada', automatically send the proposal template.
    """
    stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
    if not stage:
        return
        
    if stage.name == "Propuesta Enviada":
        # Comprobar si la regla está habilitada en los settings
        rule_enabled_setting = db.query(SystemSetting).filter(SystemSetting.key == "rule_proposal_enabled").first()
        is_enabled = rule_enabled_setting.value == "true" if rule_enabled_setting else True # default habilitado
        
        if is_enabled:
            logger.info(f"Triggering automated WhatsApp proposal to contact {contact.phone}")
            
            # Enviar mensaje por WhatsApp
            proposal_msg = (
                f"Hola {contact.first_name or ''}, adjuntamos los detalles de la propuesta comercial conversada. "
                "¡Quedamos atentos a cualquier duda!"
            )
            try:
                # Meta template rule: Enviar mensaje de plantilla oficial
                await whatsapp_service.send_text_message(
                    to_phone=contact.phone,
                    message_text=proposal_msg
                )
                
                # Registrar el mensaje en BD local
                from app.models.base import Message, SenderType, ChannelType, MessageStatus, MessageType
                db_msg = Message(
                    contact_id=contact.id,
                    sender_type=SenderType.SYSTEM,
                    channel=ChannelType.WHATSAPP,
                    message_type=MessageType.TEXT,
                    content=proposal_msg,
                    status=MessageStatus.SENT
                )
                db.add(db_msg)
                
                # Guardar log de actividad automatizada
                record_activity(
                    db=db,
                    contact_id=contact.id,
                    activity_type="system",
                    description="Trigger automático: Envío de propuesta por WhatsApp al cambiar a fase 'Propuesta Enviada'."
                )
                db.commit()
            except Exception as e:
                logger.error(f"Error sending automatic WhatsApp proposal: {e}")


def check_message_keywords_trigger(db: Session, contact: Contact, message_text: str) -> bool:
    """
    Checks incoming message for keywords like 'humano', 'asesor', 'persona'.
    If found, turns off the chatbot (Piloto IA) and returns True.
    """
    # Comprobar si la regla está habilitada en los settings
    rule_enabled_setting = db.query(SystemSetting).filter(SystemSetting.key == "rule_keywords_enabled").first()
    is_enabled = rule_enabled_setting.value == "true" if rule_enabled_setting else True # default habilitado
    
    if not is_enabled:
        return False
        
    # Ignorar si es un formulario de registro que contiene "Persona Natural" o preguntas de Meta Lead Ads
    msg_lower = message_text.lower()
    if any(w in msg_lower for w in ["completé el formulario", "persona natural", "persona jurídica", "persona juridica", "¿nos visitas como", "full name:"]):
        return False

    keywords = ["hablar con humano", "quiero un humano", "asesor humano", "hablar con un asesor", "hablar con una persona", "persona real", "atencion humana", "hablar con alguien", "/humano", "quiero hablar con una persona"]
    
    if any(keyword in msg_lower for keyword in keywords):
        logger.info(f"Keyword trigger matched in message '{message_text}'. Turning off chatbot for contact {contact.id}")
        
        # Desactivar chatbot
        contact.chatbot_enabled = False
        db.add(contact)
        
        # Loggear actividad
        record_activity(
            db=db,
            contact_id=contact.id,
            activity_type="chatbot_toggle",
            description=f"El cliente escribió palabra clave detectada. El Piloto IA se desactivó automáticamente."
        )
        db.commit()
        
        # Opcional: Notificar por WebSockets a los clientes conectados
        from app.core.socket_manager import manager
        ws_payload = {
            "event": "chatbot_toggled",
            "data": {
                "contact_id": contact.id,
                "chatbot_enabled": False
            }
        }
        asyncio.create_task(manager.broadcast(ws_payload))
        return True
        
    return False
