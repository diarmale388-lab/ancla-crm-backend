import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.contact import Contact
from app.models.user import User
from app.models.activity import LeadActivity
from app.services.whatsapp import send_whatsapp_message

logger = logging.getLogger("sla_monitor")

async def check_sla_15_minutes(db: Session):
    """
    Revisa los leads ingresados que llevan más de 15 minutos sin atención
    y despacha una alerta al WhatsApp del asesor asignado o administrador.
    """
    try:
        now = datetime.utcnow()
        threshold_time = now - timedelta(minutes=15)
        cutoff_recent = now - timedelta(hours=24) # Solo prospectos de las últimas 24 horas

        # Obtener prospectos nuevos creados hace más de 15 minutos sin interacción
        leads = db.query(Contact).filter(
            Contact.created_at <= threshold_time,
            Contact.created_at >= cutoff_recent
        ).all()

        for lead in leads:
            notes = lead.qualification_notes or ""
            
            # Si ya se alertó sobre este lead, omitir
            if "[SLA_15MIN_ALERT_SENT]" in notes:
                continue

            # Verificar si el lead ya fue atendido o cambió de etapa
            # Si tiene last_interaction_at posterior a created_at + 1 min o etapa avanzada, omitir
            if lead.last_interaction_at and (lead.last_interaction_at - lead.created_at).total_seconds() > 60:
                continue

            # Determinar a quién alertar (Asesor asignado o Administrador)
            recipient_phone = None
            assigned_name = "Equipo Comercial"

            if lead.assigned_user_id:
                agent = db.query(User).filter(User.id == lead.assigned_user_id).first()
                if agent and agent.phone:
                    recipient_phone = agent.phone
                    assigned_name = agent.full_name or agent.username

            # Si no hay asesor asignado con teléfono, buscar al admin principal
            if not recipient_phone:
                admin = db.query(User).filter(User.role == "admin", User.phone.isnot(None)).first()
                if admin and admin.phone:
                    recipient_phone = admin.phone
                else:
                    # Fallback al número principal de atención ANCLA
                    recipient_phone = "573177001670"

            clean_lead_phone = (lead.phone or "").replace("+", "").replace(" ", "").replace("-", "")
            lead_name = f"{lead.first_name or ''} {lead.last_name or ''}".strip() or lead.phone or "Nuevo Prospecto"
            product = lead.interest_product or "Portafolio ANCLA (Flex Home / Cápsula Living)"
            city = lead.lot_city or "Por definir"

            alert_msg = (
                f"🚨 *ALERTA DE SLA - 15 MINUTOS SIN ATENCIÓN*\n\n"
                f"Hola *{assigned_name}*, el siguiente prospecto ingresó hace más de 15 minutos y aún no registra interacción:\n\n"
                f"👤 *Lead:* {lead_name} (#{lead.id})\n"
                f"📞 *Teléfono:* +{clean_lead_phone}\n"
                f"🏡 *Interés:* {product}\n"
                f"📍 *Ubicación:* {city}\n\n"
                f"⚡ *Iniciar Conversación Inmediata:*\n"
                f"https://wa.me/{clean_lead_phone}?text={encode_uri_component('Hola, gusto en saludarte. Te escribo de ANCLA Special Projects para coordinar los detalles de tu proyecto.')}\n\n"
                f"_ANCLA Special Projects • Radar de SLA y Eficiencia Comercial_"
            )

            # Enviar mensaje vía servicio de WhatsApp (Meta Cloud API)
            try:
                send_whatsapp_message(recipient_phone, alert_msg)
                logger.info(f"🚨 Alerta de SLA 15min enviada a {recipient_phone} para el lead #{lead.id} ({lead_name})")
            except Exception as e_send:
                logger.warning(f"No se pudo enviar WhatsApp de alerta SLA: {e_send}")

            # Marcar el lead con el tag de alerta y registrar actividad
            lead.qualification_notes = f"{notes}\n[SLA_15MIN_ALERT_SENT]".strip()
            
            activity = LeadActivity(
                contact_id=lead.id,
                activity_type="sla_alert_triggered",
                description=f"🚨 Alerta SLA de 15 minutos disparada a WhatsApp ({recipient_phone}). Lead pendiente de primer contacto."
            )
            db.add(activity)
            db.commit()

    except Exception as e:
        logger.error(f"Error en ciclo de SLA check: {e}")
        db.rollback()

def encode_uri_component(text: str) -> str:
    import urllib.parse
    return urllib.parse.quote(text)

async def sla_monitor_loop():
    """Loop continuo que vigila el SLA cada 60 segundos."""
    logger.info("🟢 Iniciando monitor de SLA de 15 minutos en segundo plano...")
    while True:
        try:
            db = SessionLocal()
            try:
                await check_sla_15_minutes(db)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Excepción en sla_monitor_loop: {e}")
        
        await asyncio.sleep(60) # Ejecutar cada 1 minuto
