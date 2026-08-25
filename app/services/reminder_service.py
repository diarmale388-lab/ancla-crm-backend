import asyncio
import logging
from datetime import datetime, timedelta
import zoneinfo
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.base import Appointment, Contact, Message, SenderType, ChannelType, MessageStatus
from app.services.whatsapp import whatsapp_service

logger = logging.getLogger("reminder_service")
BOGOTA_TZ = zoneinfo.ZoneInfo("America/Bogota")

# LEY 1 (Contrato Inviolable de Sofi AI): ERRADICACIÓN TOTAL de enlaces de Google Meet. Esta línea
# es SIEMPRE Y EXCLUSIVAMENTE el texto de acceso para Asesoría Virtual, sin importar si existe un
# `google_meet_url` real en BD. Prohibido imprimir cualquier link de Meet en mensajes al cliente.
VIRTUAL_NO_MEET_LINE = (
    "📲 Modalidad: Asesoría Virtual (Nuestro equipo se comunicará contigo puntualmente "
    "por este medio para iniciar la videollamada)."
)

# Línea de acceso para la modalidad LLAMADA (distinta e independiente de VIRTUAL).
LLAMADA_ACCESS_LINE = (
    "📞 Modalidad: Llamada Telefónica Comercial (Nuestro equipo de expertos te llamará "
    "puntualmente a este mismo número)."
)


def format_time_12h(dt: datetime) -> str:
    h = dt.hour
    m = dt.minute
    am_pm = "AM" if h < 12 else "PM"
    h_12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
    return f"{h_12:02d}:{m:02d} {am_pm}"


def format_spanish_date(dt: datetime) -> str:
    days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    months = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    day_name = days[dt.weekday()]
    month_name = months[dt.month - 1]
    return f"{day_name} {dt.day} de {month_name}"


def _resolve_modality_bucket(appointment_type: str) -> str:
    """
    Normaliza el appointment_type de BD a una de las 3 modalidades EXACTAS y no intercambiables:
    'PRESENCIAL', 'LLAMADA' o 'VIRTUAL'. Ver arquitectura de modalidades en ai_agent/tools.py.
    """
    import re
    modality_str = (appointment_type or "VIRTUAL").upper()
    if re.search(r'\b(PRESENCIAL|SHOWROOM|VISITA|ARMENIA)\b', modality_str):
        return "PRESENCIAL"
    if re.search(r'\b(VIRTUAL|VIDEOLLAMADA|MEET|ZOOM)\b', modality_str):
        return "VIRTUAL"
    if re.search(r'\b(LLAMADA|TELEFONICA|TELEFONO|CALL)\b', modality_str):
        return "LLAMADA"
    return "VIRTUAL"


async def process_appointment_reminders(db: Session):
    now_bogota = datetime.now(BOGOTA_TZ).replace(tzinfo=None)
    upcoming_limit = now_bogota + timedelta(days=2)
    
    appointments = db.query(Appointment).filter(
        Appointment.status.in_(["CONFIRMED", "PENDING"]),
        Appointment.datetime >= now_bogota - timedelta(minutes=30),
        Appointment.datetime <= upcoming_limit
    ).all()
    
    for appt in appointments:
        contact = db.query(Contact).filter(Contact.id == appt.contact_id).first()
        if not contact or not contact.phone:
            continue
            
        time_to_appt = appt.datetime - now_bogota
        total_seconds = time_to_appt.total_seconds()
        
        name = contact.first_name or "Estimado/a"
        time_str = format_time_12h(appt.datetime)
        date_str = format_spanish_date(appt.datetime)
        lot_city = (contact.lot_city or "").strip()
        project_context = f"para tu proyecto en {lot_city}" if lot_city else "para tu proyecto de casa modular"
        modality_bucket = _resolve_modality_bucket(appt.appointment_type)
        is_virtual = modality_bucket == "VIRTUAL"
        is_llamada = modality_bucket == "LLAMADA"
        is_presencial = modality_bucket == "PRESENCIAL"

        # 1. VENTANA 24 HORAS
        if 22 * 3600 <= total_seconds <= 26 * 3600 and not appt.reminder_24h_sent:
            msg_text = None
            if appt.created_at and (now_bogota - appt.created_at.replace(tzinfo=None)) <= timedelta(hours=3):
                pass
            elif is_virtual:
                msg_text = (
                    f"¡Hola {name}! 👋 Te recordamos que mañana {date_str} a las {time_str} tenemos reservada tu *Asesoría Virtual* {project_context} 🏡✨.\n\n"
                    f"📍 Nuestro equipo te presentará en pantalla los planos de distribución, renders reales y la cotización personalizada puesta en tu lote.\n\n"
                    f"{VIRTUAL_NO_MEET_LINE}\n\n"
                    f"¡Nos vemos mañana puntualmente!"
                )
            elif is_llamada:
                msg_text = (
                    f"¡Hola {name}! 👋 Te recordamos que mañana {date_str} a las {time_str} tenemos reservada tu *Llamada Telefónica Comercial* {project_context} 🏡✨.\n\n"
                    f"📞 Nuestro equipo de expertos te llamará puntualmente a este número para brindarte toda la información técnica y la cotización de tu proyecto.\n\n"
                    f"¡Nos comunicamos contigo mañana!"
                )
            elif is_presencial:
                msg_text = (
                    f"¡Hola {name}! 👋 Te recordamos que mañana {date_str} a las {time_str} tenemos reservada tu *Visita al Showroom en Armenia* (Avenida Centenario, frente a Pan y Miel) 🏡✨.\n\n"
                    f"🚗 Contamos con parqueadero privado y gratuito. Enlaces para llegar fácilmente:\n"
                    f"• Waze: https://waze.com/ul?q=Avenida+Centenario+Armenia+Quindio\n"
                    f"• Google Maps: https://maps.google.com/?q=4.5616751,-75.6455612\n\n"
                    f"¡Te esperamos mañana con gusto!"
                )

            if msg_text:
                try:
                    res = await whatsapp_service.send_text_message(contact.phone, msg_text, db=db)
                    if res:
                        appt.reminder_24h_sent = True
                        db_msg = Message(
                            contact_id=contact.id,
                            sender_type=SenderType.SYSTEM,
                            channel=ChannelType.WHATSAPP,
                            content=msg_text,
                            status=MessageStatus.DELIVERED
                        )
                        db.add(db_msg)
                        db.commit()
                        logger.info(f"Recordatorio 24h enviado exitosamente a {contact.phone} (Cita {appt.id})")
                except Exception as err:
                    logger.error(f"Error enviando recordatorio 24h a {contact.phone}: {err}")

        # 2. VENTANA 2 HORAS
        if 90 * 60 <= total_seconds <= 150 * 60 and not appt.reminder_2h_sent:
            if is_virtual:
                msg_text = (
                    f"¡Hola {name}! ⏰ En 2 horas iniciamos tu *Asesoría Virtual* ({time_str}) {project_context} 🏡.\n\n"
                    f"{VIRTUAL_NO_MEET_LINE}\n\n"
                    f"¿Nos confirmas si todo en orden para tu conexión? 😊"
                )
            elif is_llamada:
                msg_text = (
                    f"¡Hola {name}! ⏰ En 2 horas te llamaremos para tu *Llamada Telefónica Comercial* ({time_str}) {project_context} 🏡.\n\n"
                    f"{LLAMADA_ACCESS_LINE}\n\n"
                    f"¿Nos confirmas que estarás disponible para recibir la llamada? 😊"
                )
            else:
                msg_text = (
                    f"¡Hola {name}! ⏰ En 2 horas te esperamos en nuestro Showroom de Armenia ({time_str}) 🏡.\n\n"
                    f"📍 Avenida Centenario, frente a Pan y Miel (Parqueadero privado disponible).\n"
                    f"🚗 Waze: https://waze.com/ul?q=Avenida+Centenario+Armenia+Quindio\n\n"
                    f"¡Nos vemos en breve!"
                )
            
            try:
                res = await whatsapp_service.send_text_message(contact.phone, msg_text, db=db)
                if res:
                    appt.reminder_2h_sent = True
                    db_msg = Message(
                        contact_id=contact.id,
                        sender_type=SenderType.SYSTEM,
                        channel=ChannelType.WHATSAPP,
                        content=msg_text,
                        status=MessageStatus.DELIVERED
                    )
                    db.add(db_msg)
                    db.commit()
                    logger.info(f"Recordatorio 2h enviado exitosamente a {contact.phone} (Cita {appt.id})")
            except Exception as err:
                logger.error(f"Error enviando recordatorio 2h a {contact.phone}: {err}")

        # 3. VENTANA 15 MINUTOS
        if 5 * 60 <= total_seconds <= 20 * 60 and not appt.reminder_15m_sent:
            msg_text = None
            if is_virtual:
                msg_text = (
                    f"¡Hola {name}! 👋 En 15 minutos nuestro equipo de expertos estará listo para atenderte en tu Asesoría Virtual:\n"
                    f"{VIRTUAL_NO_MEET_LINE}\n\n"
                    f"¡Nos vemos en breve para revisar los planos de tu casa modular! 🏡"
                )
            elif is_llamada:
                msg_text = (
                    f"¡Hola {name}! 👋 En 15 minutos nuestro equipo de expertos te llamará para tu Llamada Telefónica Comercial:\n"
                    f"{LLAMADA_ACCESS_LINE}\n\n"
                    f"¡Prepárate para revisar la información de tu casa modular! 🏡"
                )

            if msg_text:
                try:
                    res = await whatsapp_service.send_text_message(contact.phone, msg_text, db=db)
                    if res:
                        appt.reminder_15m_sent = True
                        db_msg = Message(
                            contact_id=contact.id,
                            sender_type=SenderType.SYSTEM,
                            channel=ChannelType.WHATSAPP,
                            content=msg_text,
                            status=MessageStatus.DELIVERED
                        )
                        db.add(db_msg)
                        db.commit()
                        logger.info(f"Recordatorio 15m enviado exitosamente a {contact.phone} (Cita {appt.id})")
                except Exception as err:
                    logger.error(f"Error enviando recordatorio 15m a {contact.phone}: {err}")


async def appointment_reminder_loop():
    logger.info("Iniciando Background Worker de Recordatorios Automáticos Anti-No-Show...")
    while True:
        try:
            db = SessionLocal()
            try:
                await process_appointment_reminders(db)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Excepción en appointment_reminder_loop: {e}")
        await asyncio.sleep(60)
