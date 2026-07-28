import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional, Any
from app.database import get_db
from app.models.base import User, Contact, Message, SenderType, ChannelType, MessageStatus, MessageType, UserRole
from app.core.deps import get_current_user
from app.services.whatsapp import whatsapp_service
from app.services.activity import record_activity

logger = logging.getLogger("broadcasts_router")

router = APIRouter(prefix="/broadcasts", tags=["broadcasts"])

class BroadcastRequest(BaseModel):
    message_text: str = Field(..., min_length=1, description="Cuerpo del mensaje de difusión")
    pipeline_stage_id: Optional[int] = Field(None, description="Filtrar por etapa del pipeline")
    lead_source: Optional[str] = Field(None, description="Filtrar por fuente de lead (ej. Meta Ads)")
    interest_product: Optional[str] = Field(None, description="Filtrar por interés de producto (Glamping, Flex Home, Frío, Bodegas)")
    qualification_level: Optional[str] = Field(None, description="Filtrar por nivel de calificación (potencial, explorador, curioso)")
    template_name: Optional[str] = Field(None, description="Nombre de la plantilla de WhatsApp aprobada por Meta")
    delay_seconds: float = Field(1.5, ge=0.5, le=10.0, description="Retraso entre envíos para evitar alertas de Meta")

async def run_broadcast_task(
    contacts: List[Contact],
    message_text: str,
    template_name: Optional[str],
    delay_seconds: float,
    admin_id: int,
    db_session_factory
):
    """
    Tarea en segundo plano que despacha mensajes progresivamente con delay
    para cumplir con los lineamientos antispam de Meta y evitar bloqueos.
    """
    logger.info(f"Iniciando envío masivo a {len(contacts)} contactos...")
    
    for idx, contact in enumerate(contacts):
        # Crear una nueva sesión de BD para cada contacto si es un background thread/task duradero
        db = db_session_factory()
        try:
            # Volver a cargar el contacto en la nueva sesión
            fresh_contact = db.query(Contact).filter(Contact.id == contact.id).first()
            if not fresh_contact:
                continue

            logger.info(f"Despachando broadcast {idx+1}/{len(contacts)} a {fresh_contact.phone}")
            
            # Enviar mensaje por WhatsApp Cloud API
            # Nota: Si template_name está definido, en un entorno de producción se llamaría al endpoint de plantillas de Meta
            await whatsapp_service.send_text_message(
                to_phone=fresh_contact.phone,
                message_text=message_text
            )

            # Registrar mensaje en la BD local
            db_msg = Message(
                contact_id=fresh_contact.id,
                sender_type=SenderType.USER,
                sender_id=admin_id,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=message_text,
                status=MessageStatus.SENT
            )
            db.add(db_msg)
            
            # Registrar en el timeline del Lead
            record_activity(
                db=db,
                contact_id=fresh_contact.id,
                activity_type="message_sent",
                description=f"Difusión enviada: '{message_text}'" + (f" (Plantilla: {template_name})" if template_name else ""),
                user_id=admin_id
            )
            db.commit()
        except Exception as e:
            logger.error(f"Error despachando broadcast a {contact.phone}: {e}")
        finally:
            db.close()
            
        # Espera programada anti-spam (Throttling)
        await asyncio.sleep(delay_seconds)
        
    logger.info("Envío masivo finalizado exitosamente.")

@router.post("/send")
def send_broadcast(
    *,
    db: Session = Depends(get_db),
    payload: BroadcastRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Inicia una campaña de difusión masiva por WhatsApp filtrando destinatarios (Solo Admin).
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: Se requieren permisos de administrador."
        )

    # Filtrar destinatarios
    query = db.query(Contact)
    if payload.pipeline_stage_id is not None:
        query = query.filter(Contact.pipeline_stage_id == payload.pipeline_stage_id)
    if payload.lead_source:
        query = query.filter(Contact.source == payload.lead_source)
    if payload.interest_product:
        query = query.filter(Contact.interest_product == payload.interest_product)
    if payload.qualification_level:
        query = query.filter(Contact.qualification_level == payload.qualification_level)
        
    contacts = query.all()
    if not contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se encontraron contactos que coincidan con los filtros seleccionados."
        )

    # Evitar bloqueos tontos: si el lote es muy grande (> 100) y no se usa plantilla Meta, forzar advertencia
    if len(contacts) > 50 and not payload.template_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta limita los envíos masivos directos a más de 50 contactos si no se utiliza una plantilla aprobada (Meta Template). Por favor, registra la plantilla o reduce el grupo de destinatarios."
        )

    # Iniciar tarea en segundo plano
    from app.database import SessionLocal
    background_tasks.add_task(
        run_broadcast_task,
        contacts,
        payload.message_text,
        payload.template_name,
        payload.delay_seconds,
        current_user.id,
        SessionLocal
    )

    return {
        "status": "success",
        "message": f"Difusión iniciada en segundo plano para {len(contacts)} contactos.",
        "recipient_count": len(contacts),
        "estimated_duration_seconds": len(contacts) * payload.delay_seconds
    }


# ──────────────────────────────────────────────────────────────────────
# NUEVO: Endpoint de Reconfirmación Showroom con Botones Interactivos
# ──────────────────────────────────────────────────────────────────────

class ShowroomConfirmRequest(BaseModel):
    message_text: str = Field(
        default=(
            "¡Muy buenos días, {nombre}! ☀️\n\n"
            "Te habla *Liliana León*, Directora Líder de *Ancla Special Projects*.\n\n"
            "Es un gusto saludarte. Queremos confirmar tu asistencia a nuestra "
            "*Gran Inauguración VIP* de nuestro nuevo Showroom y Sala de Ventas en Colombia.\n\n"
            "📅 *Tu cita*: Hoy, *{dia}* a las *{hora}*\n"
            "📍 *Ubicación*: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n\n"
            "Para nosotros es muy importante contar con tu presencia. "
            "¿Nos confirmas tu asistencia?\n\n"
            "¡Te esperamos! 🏡✨\n"
            "_Liliana León — Directora Líder, Ancla Special Projects_"
        ),
        description="Texto del mensaje de reconfirmación. Usa {nombre}, {dia}, {hora} como placeholders."
    )
    delay_seconds: float = Field(2.0, ge=0.5, le=10.0, description="Delay entre envíos para anti-spam de Meta")
    target_day: int = Field(28, ge=28, le=29, description="Día objetivo: 28 o 29 de Julio")


async def run_showroom_confirm_task(
    attendees: list,
    message_text: str,
    delay_seconds: float,
    admin_id: int,
    db_session_factory
):
    """
    Tarea en segundo plano que envía mensajes de reconfirmación con botones
    interactivos a cada asistente confirmado del showroom.
    """
    logger.info(f"🏠 Iniciando envío de reconfirmación showroom a {len(attendees)} asistentes...")

    for idx, (contact_id, phone, name, day_str, time_str) in enumerate(attendees):
        db = db_session_factory()
        try:
            # Personalizar el mensaje con los datos del contacto
            personalized = message_text.replace("{nombre}", name).replace("{dia}", day_str).replace("{hora}", time_str)

            # Botones interactivos de WhatsApp (máx 20 chars por título)
            buttons = [
                {"id": "btn_confirm_today", "title": "✅ Confirmo hoy"},
                {"id": "btn_confirm_tomorrow", "title": "📅 Asistiré mañana"},
            ]

            logger.info(f"  📲 Enviando reconfirmación {idx+1}/{len(attendees)} a {phone} ({name})")

            # Enviar mensaje con botones interactivos por WhatsApp Cloud API
            await whatsapp_service.send_interactive_buttons(
                to_phone=phone,
                body_text=personalized,
                buttons=buttons,
                header_text="🏠 Confirmación Showroom",
                footer_text="Ancla Special Projects",
                db=db
            )

            # Registrar el mensaje en la BD local
            db_msg = Message(
                contact_id=contact_id,
                sender_type=SenderType.USER,
                sender_id=admin_id,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=personalized,
                status=MessageStatus.SENT
            )
            db.add(db_msg)

            # Registrar actividad en el timeline del contacto
            record_activity(
                db=db,
                contact_id=contact_id,
                activity_type="message_sent",
                description=f"Reconfirmación Showroom enviada con botones interactivos",
                user_id=admin_id
            )
            db.commit()
        except Exception as e:
            logger.error(f"  ❌ Error enviando reconfirmación a {phone}: {e}")
        finally:
            db.close()

        # Throttling anti-spam
        await asyncio.sleep(delay_seconds)

    logger.info(f"✅ Reconfirmación showroom finalizada: {len(attendees)} mensajes enviados.")


@router.post("/showroom-confirm")
def send_showroom_confirmation(
    *,
    db: Session = Depends(get_db),
    payload: ShowroomConfirmRequest = ShowroomConfirmRequest(),
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Envía mensajes de reconfirmación con botones interactivos de WhatsApp
    a todos los asistentes presenciales confirmados para el día objetivo del Showroom.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: Se requieren permisos de administrador."
        )

    from app.models.base import Appointment, Contact as ContactModel
    from datetime import datetime

    target_start = datetime(2026, 7, payload.target_day, 0, 0, 0)
    target_end = datetime(2026, 7, payload.target_day, 23, 59, 59)

    results = db.query(Appointment, ContactModel).join(
        ContactModel, Appointment.contact_id == ContactModel.id
    ).filter(
        Appointment.status == 'CONFIRMED',
        Appointment.datetime >= target_start,
        Appointment.datetime <= target_end
    ).order_by(Appointment.datetime.asc()).all()

    if not results:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se encontraron asistentes confirmados para el {payload.target_day} de Julio."
        )

    # Filtrar solo los presenciales (no virtuales)
    attendees = []
    for a, c in results:
        notes = (a.notes or "").lower() + " " + (c.qualification_notes or "").lower()
        is_virtual = any(w in notes for w in ["virtual", "espera vip", "lista de espera"])
        if is_virtual:
            continue  # Saltar virtuales, solo presenciales

        name = f"{c.first_name or ''} {c.last_name or ''}".strip() or "Estimado cliente"
        day_name = "Martes 28 de Julio" if a.datetime.day == 28 else "Miércoles 29 de Julio"
        time_str = a.datetime.strftime("%I:%M %p").replace(" 0", " ").strip()
        attendees.append((c.id, c.phone, name, day_name, time_str))

    if not attendees:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se encontraron asistentes PRESENCIALES confirmados para el {payload.target_day} de Julio."
        )

    # Iniciar tarea en segundo plano
    from app.database import SessionLocal
    background_tasks.add_task(
        run_showroom_confirm_task,
        attendees,
        payload.message_text,
        payload.delay_seconds,
        current_user.id,
        SessionLocal
    )

    return {
        "status": "success",
        "message": f"Reconfirmación showroom iniciada para {len(attendees)} asistentes presenciales del {payload.target_day} de Julio.",
        "recipient_count": len(attendees),
        "attendees": [{"name": a[2], "phone": a[1], "time": a[4]} for a in attendees],
        "estimated_duration_seconds": len(attendees) * payload.delay_seconds
    }

