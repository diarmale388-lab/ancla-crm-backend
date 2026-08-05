# -*- coding: utf-8 -*-
"""
Endpoint dedicado para envio de reconfirmacion del Showroom con botones interactivos.
"""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, Any
from app.database import get_db
from app.models.base import User, Contact, Message, SenderType, ChannelType, MessageStatus, MessageType, UserRole, Appointment
from app.core.deps import get_current_user
from app.services.whatsapp import whatsapp_service
from app.services.activity import record_activity

logger = logging.getLogger("showroom_confirm")

router = APIRouter(prefix="/showroom-confirm", tags=["showroom-confirm"])

DEFAULT_MESSAGE = (
    "Muy buenos dias, {nombre}!\n\n"
    "Te habla *Liliana Leon*, Directora Lider de *Ancla Special Projects*.\n\n"
    "Es un gusto saludarte. Queremos confirmar tu asistencia a nuestra "
    "*Gran Inauguracion VIP* de nuestro nuevo Showroom y Sala de Ventas en Colombia.\n\n"
    "*Tu cita*: Hoy, *{dia}* a las *{hora}*\n"
    "*Ubicacion*: Armenia, Quindio - Avenida Centenario, frente a Pan y Miel.\n\n"
    "Para nosotros es muy importante contar con tu presencia. "
    "Nos confirmas tu asistencia?\n\n"
    "Te esperamos!\n"
    "_Liliana Leon - Directora Lider, Ancla Special Projects_"
)


class ConfirmPayload(BaseModel):
    message_text: Optional[str] = None
    delay_seconds: float = 2.0
    target_day: int = 28


async def _send_confirmations(attendees, message_text, delay_seconds, admin_id, db_factory):
    logger.info("Iniciando envio de reconfirmacion showroom a %d asistentes...", len(attendees))
    for idx, (contact_id, phone, name, day_str, time_str) in enumerate(attendees):
        db = db_factory()
        try:
            personalized = message_text.replace("{nombre}", name).replace("{dia}", day_str).replace("{hora}", time_str)
            buttons = [
                {"id": "btn_confirm_today", "title": "Confirmo hoy"},
                {"id": "btn_confirm_tomorrow", "title": "Asistire manana"},
                {"id": "btn_no_attend", "title": "No podre asistir"},
            ]
            logger.info("Enviando reconfirmacion %d/%d a %s (%s)", idx + 1, len(attendees), phone, name)
            await whatsapp_service.send_interactive_buttons(
                to_phone=phone,
                body_text=personalized,
                buttons=buttons,
                header_text="Confirmacion Showroom",
                footer_text="Ancla Special Projects",
                db=db,
            )
            db_msg = Message(
                contact_id=contact_id,
                sender_type=SenderType.USER,
                sender_id=admin_id,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=personalized,
                status=MessageStatus.SENT,
            )
            db.add(db_msg)
            record_activity(db=db, contact_id=contact_id, activity_type="message_sent",
                            description="Reconfirmacion Showroom enviada con botones interactivos", user_id=admin_id)
            db.commit()
        except Exception as e:
            logger.error("Error enviando reconfirmacion a %s: %s", phone, e)
        finally:
            db.close()
        await asyncio.sleep(delay_seconds)
    logger.info("Reconfirmacion showroom finalizada: %d mensajes enviados.", len(attendees))


@router.post("/send")
def send_showroom_confirmation(
    payload: ConfirmPayload,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
) -> Any:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo admin.")

    from datetime import datetime
    message_text = payload.message_text or DEFAULT_MESSAGE
    target_start = datetime(2026, 7, payload.target_day, 0, 0, 0)
    target_end = datetime(2026, 7, payload.target_day, 23, 59, 59)

    results = db.query(Appointment, Contact).join(
        Contact, Appointment.contact_id == Contact.id
    ).filter(
        Appointment.status == "CONFIRMED",
        Appointment.datetime >= target_start,
        Appointment.datetime <= target_end,
    ).order_by(Appointment.datetime.asc()).all()

    if not results:
        raise HTTPException(status_code=400, detail=f"No hay asistentes confirmados para el {payload.target_day} de Julio.")

    attendees = []
    for a, c in results:
        notes = (a.notes or "").lower() + " " + (c.qualification_notes or "").lower()
        if any(w in notes for w in ["virtual", "espera vip", "lista de espera"]):
            continue
        name = f"{c.first_name or ''} {c.last_name or ''}".strip() or "Estimado cliente"
        day_name = "Martes 28 de Julio" if a.datetime.day == 28 else "Miercoles 29 de Julio"
        time_str = a.datetime.strftime("%I:%M %p").replace(" 0", " ").strip()
        attendees.append((c.id, c.phone, name, day_name, time_str))

    if not attendees:
        raise HTTPException(status_code=400, detail=f"No hay asistentes PRESENCIALES para el {payload.target_day} de Julio.")

    from app.database import SessionLocal
    background_tasks.add_task(_send_confirmations, attendees, message_text, payload.delay_seconds, current_user.id, SessionLocal)

    return {
        "status": "success",
        "message": f"Reconfirmacion showroom iniciada para {len(attendees)} asistentes presenciales.",
        "recipient_count": len(attendees),
        "attendees": [{"name": a[2], "phone": a[1], "time": a[4]} for a in attendees],
        "estimated_duration_seconds": len(attendees) * payload.delay_seconds,
    }
