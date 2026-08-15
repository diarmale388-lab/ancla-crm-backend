import logging
import asyncio
import json
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.base import Contact, Message, SenderType, ChannelType, MessageType, MessageStatus
from app.core.round_robin import assign_lead_round_robin
from app.core.socket_manager import manager
from app.services.whatsapp import whatsapp_service
from app.services.meta_api import meta_api_service
from app.services.ai_engine import ai_engine
from app.routers.webhooks import process_meta_ads_attribution

logger = logging.getLogger("arq_worker")
logging.basicConfig(level=logging.INFO)

# Parsear la URL de Redis para arq
redis_url = urlparse(settings.REDIS_URL)
redis_settings = RedisSettings(
    host=redis_url.hostname,
    port=redis_url.port or 6379,
    password=redis_url.password,
    database=int(redis_url.path[1:]) if redis_url.path and len(redis_url.path) > 1 else 0,
    ssl=redis_url.scheme == 'rediss'
)

async def send_habeas_data_notice(to_phone: str, db: Session) -> bool:
    """
    Envía un mensaje interactivo con botones a WhatsApp solicitando el consentimiento de Habeas Data.
    """
    access_token, phone_id = whatsapp_service.get_credentials(db)
    if not access_token or not phone_id:
        logger.error("No se pudieron leer las credenciales de WhatsApp para Habeas Data.")
        return False

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    "Hola, en ANCLA Special Projects nos interesa brindarte asesoría sobre nuestras viviendas modulares y proyectos. "
                    "Para poder comunicarnos contigo, enviarte catálogos y procesar tu solicitud, requerimos tu consentimiento "
                    "bajo nuestra Política de Tratamiento de Datos Personales (Ley 1581 de 2012).\n\n"
                    "¿Autorizas el tratamiento de tus datos?"
                )
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "habeas_accept",
                            "title": "Sí, autorizo"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "habeas_reject",
                            "title": "No autorizo"
                        }
                    }
                ]
            }
        }
    }

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=headers, json=payload, timeout=10.0)
            res_data = res.json()
            if res.status_code == 200:
                logger.info(f"Mensaje de aviso de Habeas Data enviado a {to_phone}")
                return True
            logger.error(f"Fallo al enviar aviso Habeas Data: {res_data}")
            return False
    except Exception as e:
        logger.error(f"Error de conexión enviando aviso Habeas Data: {e}")
        return False


async def download_and_upload_media_to_gdrive(media_id: str, db: Session) -> tuple[Optional[str], Optional[bytes], Optional[str]]:
    """
    Descarga el archivo de Meta usando el media_id y lo sube a Google Drive de forma permanente.
    Retorna una tupla: (drive_id, file_bytes, mime_type).
    """
    try:
        import httpx
        from app.services.google_integration import upload_whatsapp_media_to_google_drive
        
        # 1. Obtener credenciales de Meta
        access_token, phone_id = whatsapp_service.get_credentials(db)
        if not access_token:
            logger.error("No se pudo obtener el token de Meta para descargar media.")
            return None, None, None

        # 2. Consultar metadata del archivo en Meta
        meta_url = f"https://graph.facebook.com/v18.0/{media_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            res = await client.get(meta_url, headers=headers, timeout=10.0)
            if res.status_code != 200:
                logger.error(f"Error consultando metadata de media {media_id} a Meta: {res.text}")
                return None, None, None
                
            media_info = res.json()
            download_url = media_info.get("url")
            mime_type = media_info.get("mime_type", "application/octet-stream")
            
            if not download_url:
                logger.error(f"No se encontró URL de descarga para media {media_id}")
                return None, None, None
                
            # 3. Descargar el archivo binario
            download_res = await client.get(download_url, headers=headers, timeout=30.0)
            if download_res.status_code != 200:
                logger.error(f"Error descargando binario de media {media_id}: {download_res.status_code}")
                return None, None, None
                
            file_bytes = download_res.content

        # Determinar una extensión tentativa en base al mime type
        import mimetypes
        ext = mimetypes.guess_extension(mime_type) or ""
        filename = f"whatsapp_media_{media_id}{ext}"

        # 4. Subir a Google Drive
        drive_file_id = await upload_whatsapp_media_to_google_drive(db, file_bytes, filename, mime_type)
        if drive_file_id:
            return f"gdrive_{drive_file_id}", file_bytes, mime_type
            
        return None, file_bytes, mime_type
    except Exception as e:
        logger.error(f"Excepción en download_and_upload_media_to_gdrive: {e}")
        return None, None, None


async def transcribe_whatsapp_audio(file_bytes: bytes, mime_type: str, db: Session) -> Optional[str]:
    """
    Transcribe una nota de voz/audio recibida en WhatsApp usando el Speech-to-Text de Google Gemini multimodal en OpenRouter.
    """
    if not file_bytes:
        return None
    try:
        from app.services.transcription import transcribe_audio_bytes
        transcript = await transcribe_audio_bytes(file_bytes)
        if transcript:
            logger.info(f"✅ Transcripción en memoria exitosa: '{transcript}'")
            return transcript
    except Exception as e:
        logger.error(f"Excepción en transcribe_whatsapp_audio: {e}")
    return None


async def process_ai_response_after_consent(contact_id: int, last_message_content: str):
    logger.info(f"Iniciando respuesta automática de la IA post-consentimiento para contacto ID {contact_id}...")
    await asyncio.sleep(2.0)  # Esperar a que se entregue el aviso legal de confirmación
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if contact and contact.chatbot_enabled:
            ai_reply = await ai_engine.generate_autopilot_reply(
                db=db,
                contact=contact,
                last_message=last_message_content
            )
            if ai_reply:
                # Evitar duplicados
                ultimo_mensaje_ia = db.query(Message).filter(
                    Message.contact_id == contact.id,
                    Message.sender_type == SenderType.AI
                ).order_by(Message.created_at.desc()).first()

                if ultimo_mensaje_ia and ultimo_mensaje_ia.content == ai_reply:
                    logger.info("Evitando duplicado de chatbot post-consentimiento.")
                    return

                # Guardar respuesta de la IA
                db_ai_msg = Message(
                    contact_id=contact.id,
                    sender_type=SenderType.AI,
                    channel=ChannelType.WHATSAPP,
                    message_type=MessageType.TEXT,
                    content=ai_reply,
                    status=MessageStatus.SENT
                )
                db.add(db_ai_msg)
                db.commit()
                db.refresh(db_ai_msg)
                
                # Enviar por WhatsApp
                external_res = await whatsapp_service.send_text_message(
                    to_phone=contact.phone,
                    message_text=ai_reply,
                    db=db
                )
                if external_res and "messages" in external_res:
                    db_ai_msg.external_message_id = external_res["messages"][0].get("id")
                    db_ai_msg.status = MessageStatus.DELIVERED
                    db.add(db_ai_msg)
                    db.commit()
                
                # Transmitir por WebSocket
                ws_payload = {
                    "event": "message_received",
                    "data": {
                        "id": db_ai_msg.id,
                        "contact_id": contact.id,
                        "sender_type": db_ai_msg.sender_type,
                        "channel": db_ai_msg.channel,
                        "message_type": db_ai_msg.message_type,
                        "content": db_ai_msg.content,
                        "status": db_ai_msg.status,
                        "created_at": db_ai_msg.created_at.isoformat()
                    }
                }
    except Exception as e:
        logger.error(f"Error procesando respuesta de IA: {e}")
    finally:
        db.close()


async def process_whatsapp_message(ctx, payload: dict):
    """
    Tarea asíncrona para procesar el evento de WhatsApp recibido desde Meta.
    Realiza validación de Habeas Data, persistencia, asignación, RAG, e IA.
    """
    print(f"\n[WORKER] Iniciando procesamiento de mensaje WhatsApp: {payload}")
    logger.info(f"[WORKER] Iniciando procesamiento de mensaje WhatsApp: {payload}")
    
    value = payload.get("value", {})
    messages = value.get("messages", [])
    if not messages:
        print("[WORKER] No se encontraron mensajes en el payload.")
        logger.info("[WORKER] No se encontraron mensajes en el payload.")
        return
        
    msg = messages[0]
    external_msg_id = msg.get("id")
    from_phone = msg.get("from")
    
    if not from_phone:
        print("[WORKER] El mensaje no tiene teléfono de origen.")
        logger.info("[WORKER] El mensaje no tiene teléfono de origen.")
        return

    # Abrir sesión de base de datos síncrona
    db: Session = SessionLocal()
    try:
        # 1. Comprobar duplicado en la base de datos relacional
        exists = db.query(Message).filter(Message.external_message_id == external_msg_id).first()
        if exists:
            print(f"[WORKER] Filtro Anti-Duplicados: Mensaje duplicado de WhatsApp omitido en worker (wamid={external_msg_id})")
            logger.info(f"[WORKER] Filtro Anti-Duplicados: Mensaje duplicado de WhatsApp omitido en worker (wamid={external_msg_id})")
            db.close()
            return
        else:
            print(f"[WORKER] Filtro Anti-Duplicados: Mensaje nuevo aceptado (wamid={external_msg_id})")
            logger.info(f"[WORKER] Filtro Anti-Duplicados: Mensaje nuevo aceptado (wamid={external_msg_id})")

        msg_type = msg.get("type", "text")
        content = ""
        button_reply_id = None

        if msg_type == "text":
            content = msg.get("text", {}).get("body", "")
        elif msg_type in ["interactive", "button", "list_reply", "button_reply"]:
            interactive = msg.get("interactive", {})
            button = msg.get("button", {})
            if interactive.get("type") == "button_reply":
                button_reply = interactive.get("button_reply", {})
                button_reply_id = button_reply.get("id")
                content = button_reply.get("title", "") or button_reply.get("id", "")
            elif interactive.get("type") == "list_reply":
                list_reply = interactive.get("list_reply", {})
                button_reply_id = list_reply.get("id")
                content = list_reply.get("title", "") or list_reply.get("id", "")
            elif button:
                content = button.get("text", "") or button.get("payload", "")
            else:
                content = interactive.get("body", {}).get("text", "") or "[Respuesta interactiva]"
        elif msg_type in ["audio", "voice"]:
            media_id = msg.get(msg_type, {}).get("id", "")
            # Descargar de Meta y subir a Google Drive
            drive_id, file_bytes, mime_type = await download_and_upload_media_to_gdrive(media_id, db)
            target_id = drive_id if drive_id else media_id
            
            # Transcribir audio directamente desde bytes en memoria o fallback a descarga directa
            transcription = None
            if file_bytes:
                from app.services.transcription import transcribe_audio_bytes
                transcription = await transcribe_audio_bytes(file_bytes, db=db)
                
            if not transcription and media_id:
                try:
                    local_path = await whatsapp_service.download_media(media_id, db)
                    if local_path:
                        from app.services.transcription import transcribe_audio_file
                        transcription = await transcribe_audio_file(local_path, db=db)
                except Exception as down_e:
                    logger.error(f"Fallback download_media error: {down_e}")

            if transcription:
                content = transcription
                logger.info(f"🎤 [AUDIO TRANSCRIPTO] para {from_phone}: '{transcription}'")
            else:
                content = f"[Media ID: {target_id}]\n[🎙️ Nota de voz recibida]"
        elif msg_type in ["image", "video", "document"]:
            media_id = msg.get(msg_type, {}).get("id", "")
            # Descargar de Meta y subir a Google Drive
            drive_id, file_bytes, mime_type = await download_and_upload_media_to_gdrive(media_id, db)
            target_id = drive_id if drive_id else media_id
            content = f"[Media ID: {target_id}]"
        else:
            content = f"[Mensaje de tipo: {msg_type}]"

        if not content:
            content = msg.get("text", {}).get("body", "") or msg.get("button", {}).get("text", "") or msg.get("interactive", {}).get("list_reply", {}).get("title", "") or msg.get("interactive", {}).get("button_reply", {}).get("title", "") or f"[Mensaje de WhatsApp: {msg_type}]"

        content_lower = (content or "").lower().strip()

        # 2. Buscar o Crear Contacto (flexible con o sin '+')
        clean_from = "".join(filter(str.isdigit, str(from_phone)))
        contact = db.query(Contact).filter(
            (Contact.phone == clean_from) | 
            (Contact.phone == f"+{clean_from}") | 
            (Contact.phone == from_phone)
        ).first()
        is_new = False
        if not contact:
            profile_name = "WhatsApp Contact"
            contacts_info = value.get("contacts", [])
            if contacts_info:
                profile_name = contacts_info[0].get("profile", {}).get("name", "WhatsApp Contact")
            
            names = profile_name.split(" ", 1)
            first_name = names[0]
            last_name = names[1] if len(names) > 1 else ""

            contact = Contact(
                phone=from_phone,
                first_name=first_name,
                last_name=last_name,
                source="WhatsApp",
                chatbot_enabled=True,
                habeas_data_authorized=True,
                whatsapp_phone_number_id=value.get("metadata", {}).get("phone_number_id")
            )
            db.add(contact)
            db.commit()
            db.refresh(contact)
            is_new = True
            print(f"[WORKER] Contacto Nuevo Creado #{contact.id} ({contact.phone}). Chatbot Enabled: {contact.chatbot_enabled}")
            logger.info(f"[WORKER] Contacto Nuevo Creado #{contact.id} ({contact.phone}). Chatbot Enabled: {contact.chatbot_enabled}")
        else:
            print(f"[WORKER] Contacto Existente #{contact.id} ({contact.phone}). Chatbot Enabled: {contact.chatbot_enabled}")
            logger.info(f"[WORKER] Contacto Existente #{contact.id} ({contact.phone}). Chatbot Enabled: {contact.chatbot_enabled}")

        # 3. Procesar Atribución de Meta Ads
        referral = msg.get("referral")
        if referral or is_new or "Meta Ads" not in (contact.source or ""):
            process_meta_ads_attribution(msg, contact, content, db)
            db.add(contact)
            db.commit()

        # 3.b Parsear Respuestas de Formulario Meta Ads si vienen en el texto del mensaje
        if content and (":" in content or "formulario" in content.lower()):
            try:
                from app.services.form_parser import parse_and_update_contact_from_text
                parse_and_update_contact_from_text(contact, content, db)
            except Exception as form_err:
                logger.error(f"Error parseando respuestas del formulario en mensaje: {form_err}")

        # 4. Asignación de lead por Round Robin si es nuevo
        if is_new or contact.assigned_user_id is None:
            assign_lead_round_robin(db, contact)
            db.add(contact)
            db.commit()

        # Determinar el tipo de mensaje en BD
        db_msg_type = MessageType.TEXT
        if msg_type in ["audio", "voice"]:
            db_msg_type = MessageType.AUDIO
        elif msg_type == "document":
            db_msg_type = MessageType.DOCUMENT
        elif msg_type == "video":
            db_msg_type = MessageType.VIDEO
        elif msg_type == "image":
            db_msg_type = MessageType.IMAGE

        # 5. Guardar mensaje recibido en BD
        db_content = f"[🎙️ Nota de voz]: {content}" if msg_type in ["audio", "voice"] and not content.startswith("[Media ID:") else content
        db_msg = Message(
            contact_id=contact.id,
            sender_type=SenderType.CONTACT,
            channel=ChannelType.WHATSAPP,
            message_type=db_msg_type,
            content=db_content,
            status=MessageStatus.DELIVERED,
            external_message_id=external_msg_id
        )
        db.add(db_msg)
        db.commit()
        db.refresh(db_msg)

        try:
            from app.services.audit_trail import log_event_audit
            log_event_audit(
                db=db,
                source="META_WEBHOOK",
                event_type="INCOMING_MSG",
                contact_id=contact.id,
                payload={"from_phone": contact.phone, "content": content, "msg_id": db_msg.id}
            )
        except Exception as aud_e:
            logger.error(f"Audit log error incoming: {aud_e}")

        # Transmitir en tiempo real
        ws_payload = {
            "event": "new_message",
            "assigned_user_id": contact.assigned_user_id,
            "data": {
                "id": db_msg.id,
                "contact_id": contact.id,
                "contact_name": f"{contact.first_name} {contact.last_name or ''}".strip(),
                "sender_type": db_msg.sender_type.value if hasattr(db_msg.sender_type, "value") else str(db_msg.sender_type),
                "channel": db_msg.channel.value if hasattr(db_msg.channel, "value") else str(db_msg.channel),
                "message_type": db_msg.message_type.value if hasattr(db_msg.message_type, "value") else str(db_msg.message_type),
                "content": db_msg.content,
                "created_at": db_msg.created_at.isoformat(),
                "contact": {
                    "id": contact.id,
                    "first_name": contact.first_name,
                    "last_name": contact.last_name,
                    "phone": contact.phone,
                    "assigned_user_id": contact.assigned_user_id
                }
            }
        }
        # Publicar evento global en Redis Pub/Sub
        try:
            import redis.asyncio as redis_async
            from app.config import settings
            r_client = redis_async.from_url(settings.REDIS_URL, decode_responses=True)
            await r_client.publish("crm_live_updates", json.dumps(ws_payload, default=str))
            await r_client.close()
        except Exception as r_err:
            logger.error(f"Error publicando en Redis Pub/Sub: {r_err}")
            
        await manager.broadcast_to_all(ws_payload)

        # 5.b Despachar WebPush nativo a través de Google FCM / Apple APNs para despertar celulares con pantalla bloqueada
        try:
            from app.services.push_service import send_push_for_incoming_message
            await send_push_for_incoming_message(contact=contact, message=db_msg, db=db)
        except Exception as push_err:
            logger.error(f"Error despachando WebPush nativo en worker: {push_err}")


        # 6. Evaluar e interceptar revocación voluntaria (Opt-Out)
        text_lower = content.lower().strip()
        if text_lower in ["baja", "eliminar", "eliminar mi informacion", "eliminar mi info", "revocar", "revocar consentimiento"]:
            logger.info(f"Usuario {from_phone} solicitó revocación de Habeas Data (Opt-Out).")
            contact.habeas_data_authorized = False
            contact.chatbot_enabled = False
            
            import datetime as dt
            contact.habeas_data_authorized_at = dt.datetime.utcnow()
            db.add(contact)
            
            # Registrar log de auditoría
            from app.models.base import HabeasDataConsentLog, LeadActivityLog
            audit = HabeasDataConsentLog(
                contact_id=contact.id,
                authorized=False,
                meta_message_id=external_msg_id
            )
            db.add(audit)
            
            activity = LeadActivityLog(
                contact_id=contact.id,
                activity_type="habeas_data_revoked",
                description="El usuario revocó voluntariamente su consentimiento de tratamiento de datos."
            )
            db.add(activity)
            db.commit()
            
            await whatsapp_service.send_text_message(
                to_phone=from_phone,
                message_text="Entendido. Tus datos han sido bloqueados. No recibirás más información comercial de nuestra parte.",
                db=db
            )
            return

        # 7. Evaluar Solicitud de Hablar con Liliana León (Escalación Manual de Atención)
        if button_reply_id in ["btn_contact_liliana", "btn_liliana"] or any(w in text_lower for w in ["hablar con liliana", "hablar con liliana león", "hablar con liliana leon", "contactar a liliana", "comunicar con liliana"]):
            name = f"{contact.first_name or ''}".strip() or "estimado cliente"
            liliana_msg = (
                f"¡Entendido, {name}! 📲✨ En aproximadamente 15 minutos nuestra Directora Comercial **Liliana León** "
                f"se comunicará directamente contigo al número (+{contact.phone}) para atender tus inquietudes personalmente.\n\n"
                f"¡Muchas gracias por tu interés en ANCLA Special Projects! 🏡🤝"
            )
            contact.chatbot_enabled = False
            db.add(contact)
            db.commit()
            
            db_lili_msg = Message(
                contact_id=contact.id,
                sender_type=SenderType.AI,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=liliana_msg,
                status=MessageStatus.SENT
            )
            db.add(db_lili_msg)
            db.commit()
            
            await whatsapp_service.send_text_message(to_phone=from_phone, message_text=liliana_msg, db=db)
            return

        # 7.2 Evaluar Botones Interactivos de Confirmación y Reagendamiento (Prioridad Alta sobre Flujo Genérico)
        if button_reply_id in ["btn_confirm_appt", "btn_confirm_slot"] or "confirmar asistencia" in content_lower:
            name = f"{contact.first_name or ''}".strip() or "estimado cliente"
            confirm_reply = (
                f"¡Excelente, {name}! 👏✨ Tu asistencia ha sido reconfirmada.\n\n"
                f"Tu cita con nuestro equipo de **ANCLA Special Projects** está 100% reservada. ¡Nos vemos en breve! 🏡🤝\n\n"
                f"📍 **Showroom Armenia**: Av. Centenario, frente a Pan y Miel.\n"
                f"📍 **GPS Google Maps**: https://maps.google.com/?q=4.5616751,-75.6455612"
            )
            await whatsapp_service.send_text_message(to_phone=from_phone, message_text=confirm_reply, db=db)
            return

        if button_reply_id == "btn_reagenda_appt" or "reagendar cita" in content_lower or "reagendar" in content_lower:
            name = f"{contact.first_name or ''}".strip() or "estimado cliente"
            
            notes_str = (contact.qualification_notes or "").lower()
            source_str = (contact.source or "").lower()
            modality = "VIRTUAL" if any(w in notes_str or w in source_str for w in ["virtual", "llamada", "zoom", "meet"]) else "PRESENCIAL"
            
            contact.scheduling_state = f"AWAITING_DAY:{modality}"
            db.add(contact)
            db.commit()

            import datetime as dt_mod
            colombia_now = dt_mod.datetime.utcnow() - dt_mod.timedelta(hours=5)
            now_date = colombia_now.date()
            days_es = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            months_es_short = ['', 'Ene.', 'Feb.', 'Mar.', 'Abr.', 'May.', 'Jun.', 'Jul.', 'Ago.', 'Sep.', 'Oct.', 'Nov.', 'Dic.']

            this_week_rows = []
            next_week_rows = []

            for i in range(1, 14):
                d = now_date + dt_mod.timedelta(days=i)
                if d.weekday() == 6:
                    continue
                day_name = days_es[d.weekday()]
                month_name = months_es_short[d.month]
                title_str = f"{day_name} {d.day} de {month_name}"[:24]
                row_item = {
                    "id": f"day_{d.strftime('%Y-%m-%d')}_{modality}",
                    "title": title_str,
                    "description": f"Cupos disponibles para {modality.lower()}"
                }
                if i <= 3:
                    this_week_rows.append(row_item)
                else:
                    next_week_rows.append(row_item)

            sections = []
            if this_week_rows:
                sections.append({"title": "📅 Esta Semana", "rows": this_week_rows[:4]})
            if next_week_rows:
                sections.append({"title": "🗓️ Próxima Semana", "rows": next_week_rows[:5]})

            body_txt = (
                f"¡No te preocupes, {name}! 🗓️ Entendemos que se presentan inconvenientes. Hemos liberado tu cupo anterior.\n\n"
                f"Para tu **{'Visita Presencial en Showroom Armenia' if modality == 'PRESENCIAL' else 'Asesoría Virtual (Google Meet / Zoom)'}**, "
                "por favor abre el menú desplegable a continuación y selecciona el nuevo día de tu preferencia:"
            )

            await whatsapp_service.send_interactive_list(
                to_phone=from_phone,
                body_text=body_txt,
                button_text="📅 Seleccionar Día",
                sections=sections,
                header_text="ANCLA Special Projects",
                footer_text="Selecciona un día de la lista",
                db=db
            )
            return

        # 7.5 Agendamiento y conversación delegados 100% al motor inteligente Sofi AI (/ai_agent)
        # Desactivamos el interceptor legacy rígido para dar control total a la IA Sofi con Claude 3.5 Sonnet
        pass

        # 8. Evaluar Respuestas a Botones de Habeas Data
        if button_reply_id == "habeas_accept":
            logger.info(f"Usuario {from_phone} aceptó Habeas Data.")
            contact.habeas_data_authorized = True
            import datetime as dt
            contact.habeas_data_authorized_at = dt.datetime.utcnow()
            contact.chatbot_enabled = True
            db.add(contact)

            # Registrar consentimiento en la base de datos de auditoría de Neon
            from app.models.base import HabeasDataConsentLog, LeadActivityLog
            audit = HabeasDataConsentLog(
                contact_id=contact.id,
                authorized=True,
                meta_message_id=external_msg_id
            )
            db.add(audit)
            
            activity = LeadActivityLog(
                contact_id=contact.id,
                activity_type="habeas_data_accepted",
                description="El usuario otorgó consentimiento expreso para tratamiento de datos personales."
            )
            db.add(activity)
            db.commit()

            # Confirmar aceptación al cliente
            await whatsapp_service.send_text_message(
                to_phone=from_phone,
                message_text="¡Gracias por tu autorización! En breve te atenderemos.",
                db=db
            )

            # Buscar el último mensaje real del usuario para procesarlo de inmediato con la IA
            last_real_msg = db.query(Message).filter(
                Message.contact_id == contact.id,
                Message.sender_type == SenderType.CONTACT,
                Message.content != "Sí, autorizo"
            ).order_by(Message.created_at.desc()).first()
            
            if last_real_msg:
                asyncio.create_task(process_ai_response_after_consent(contact.id, last_real_msg.content))
            
            return

        elif button_reply_id == "habeas_reject":
            logger.info(f"Usuario {from_phone} rechazó Habeas Data.")
            contact.habeas_data_authorized = False
            contact.chatbot_enabled = False
            import datetime as dt
            contact.habeas_data_authorized_at = dt.datetime.utcnow()
            db.add(contact)

            # Registrar rechazo
            from app.models.base import HabeasDataConsentLog, LeadActivityLog
            audit = HabeasDataConsentLog(
                contact_id=contact.id,
                authorized=False,
                meta_message_id=external_msg_id
            )
            db.add(audit)

            activity = LeadActivityLog(
                contact_id=contact.id,
                activity_type="habeas_data_rejected",
                description="El usuario denegó consentimiento de tratamiento de datos. Chatbot desactivado."
            )
            db.add(activity)
            db.commit()

            # Confirmar rechazo
            await whatsapp_service.send_text_message(
                to_phone=from_phone,
                message_text="Entendido. Respetamos tu privacidad. No te enviaremos campañas comerciales. Si deseas contactar a un asesor, puedes llamarnos directamente.",
                db=db
            )
            return

        # 8. Consentimiento de datos (Bypassed por solicitud explícita del cliente)
        contact.habeas_data_authorized = True
        db.add(contact)
        db.commit()

        # 9. Disparadores de automatizaciones de palabras clave
        from app.services.automation import check_message_keywords_trigger
        check_message_keywords_trigger(db, contact, content)

        # Persistencia de Modalidad en Estado de Contacto
        content_lower = (content or "").lower()
        if "virtual" in content_lower or "llamada" in content_lower:
            contact.scheduling_state = "MODALITY_VIRTUAL"
            db.add(contact)
            db.commit()
        elif "presencial" in content_lower or "showroom" in content_lower or "visita" in content_lower:
            contact.scheduling_state = "MODALITY_PRESENCIAL"
            db.add(contact)
            db.commit()

        # 10. Piloto Automático de la Inteligencia Artificial (Sofi) con Debounce de Acumulación (2.0 Segundos)
        if contact.chatbot_enabled and msg_type in ["text", "audio", "voice", "interactive", "button", "list_reply", "button_reply"]:
            # Debounce: Esperar 2.0 segundos para agrupar respuestas ultrarrápidas
            await asyncio.sleep(2.0)
            
            # Re-verificar si el chatbot sigue activo
            db.refresh(contact)
            if not contact.chatbot_enabled:
                logger.info(f"Debounce: Chatbot fue desactivado o transferido a humano para {contact.phone}.")
                return

            # Verificar si llegó un mensaje MÁS RECIENTE del mismo contacto
            newer_msg = db.query(Message).filter(
                Message.contact_id == contact.id,
                Message.sender_type == SenderType.CONTACT,
                Message.created_at > db_msg.created_at
            ).first()

            if newer_msg:
                logger.info(f"Debounce: Omitiendo respuesta parcial de mensaje ID {db_msg.id} porque {contact.phone} envió un mensaje posterior.")
                return

            # Concatenar mensajes recientes de los últimos 60 segundos limpiando prefijos
            import datetime as dt_debounce
            recent_msgs = db.query(Message).filter(
                Message.contact_id == contact.id,
                Message.sender_type == SenderType.CONTACT,
                Message.created_at >= db_msg.created_at - dt_debounce.timedelta(seconds=60)
            ).order_by(Message.created_at.asc()).all()

            cleaned_msgs = []
            for m in recent_msgs:
                c_text = m.content or ""
                if c_text.startswith("[🎙️ Nota de voz]: "):
                    c_text = c_text.replace("[🎙️ Nota de voz]: ", "").strip()
                if c_text and not c_text.startswith("[Media ID:"):
                    cleaned_msgs.append(c_text)
            accumulated_text = " ".join(cleaned_msgs).strip() or content

            ai_reply = await ai_engine.generate_autopilot_reply(
                db=db,
                contact=contact,
                last_message=accumulated_text
            )
            if ai_reply:
                try:
                    from app.services.audit_trail import log_event_audit
                    log_event_audit(
                        db=db,
                        source="AI_ENGINE",
                        event_type="AI_REPLY_GENERATED",
                        contact_id=contact.id,
                        payload={"reply": ai_reply[:200]}
                    )
                except Exception as aud_ai_e:
                    logger.error(f"Audit log error AI reply: {aud_ai_e}")

                # Guardar respuesta de la IA
                db_ai_msg = Message(
                    contact_id=contact.id,
                    sender_type=SenderType.AI,
                    channel=ChannelType.WHATSAPP,
                    message_type=MessageType.TEXT,
                    content=ai_reply,
                    status=MessageStatus.SENT
                )
                db.add(db_ai_msg)
                db.commit()
                db.refresh(db_ai_msg)

                # Enviar respuesta de Sofi AI con botones o listas interactivas si corresponde
                try:
                    import re
                    ai_reply_lower = ai_reply.lower()
                    is_modality_question = any(k in ai_reply_lower for k in ["reunión virtual o", "virtual o presencial", "showroom en armenia?", "modalidad prefieres", "asesoría virtual o", "visitar nuestra sala", "visita presencial"])
                    time_slots = re.findall(r"(?:0[1-9]|1[0-2]):[0-5][0-9]\s*(?:AM|PM)", ai_reply, re.IGNORECASE)

                    if is_modality_question and not time_slots:
                        buttons = [
                            {"id": "MODALITY_PRESENCIAL", "title": "🏢 Visita Presencial"},
                            {"id": "MODALITY_VIRTUAL", "title": "💻 Asesoría Virtual"}
                        ]
                        await whatsapp_service.send_quick_buttons(
                            to_phone=contact.phone,
                            body_text=ai_reply,
                            buttons=buttons,
                            header_text="ANCLA Special Projects",
                            footer_text="Selecciona una opción",
                            db=db
                        )
                    elif time_slots and len(time_slots) >= 2:
                        rows = []
                        seen = set()
                        for slot in time_slots:
                            slot_clean = slot.upper().strip()
                            if slot_clean not in seen:
                                seen.add(slot_clean)
                                rows.append({
                                    "id": f"slot_{len(rows)+1}",
                                    "title": slot_clean,
                                    "description": f"Seleccionar horario {slot_clean}"
                                })
                                if len(rows) >= 10:
                                    break
                        
                        sections = [{
                            "title": "Franjas Disponibles",
                            "rows": rows
                        }]
                        
                        await whatsapp_service.send_interactive_list(
                            to_phone=contact.phone,
                            header_text="📅 Horarios Disponibles",
                            body_text=ai_reply,
                            button_text="Ver Horarios",
                            sections=sections,
                            footer_text="ANCLA Special Projects",
                            db=db
                        )
                    else:
                        await whatsapp_service.send_text_message(
                            to_phone=contact.phone,
                            message_text=ai_reply,
                            db=db
                        )
                    db_ai_msg.status = MessageStatus.DELIVERED
                    db.add(db_ai_msg)
                    db.commit()
                except Exception as send_err:
                    logger.error(f"Error al enviar elemento interactivo por WhatsApp API: {send_err}")
                    # FALLBACK DE SEGURIDAD AUTO-HEAL (SOFI SOLA EN AUTOMÁTICO):
                    # Si falla el botón interactivo, re-intenta automáticamente enviando el mensaje en texto plano
                    try:
                        logger.info(f"Re-intentando despacho de seguridad en texto plano para contacto #{contact.id}...")
                        await asyncio.sleep(1.5)
                        res_fallback = await whatsapp_service.send_text_message(
                            to_phone=contact.phone,
                            message_text=ai_reply,
                            db=db
                        )
                        if res_fallback and (res_fallback.get("messages") or res_fallback.get("status") == "success"):
                            db_ai_msg.status = MessageStatus.DELIVERED
                        else:
                            db_ai_msg.status = MessageStatus.FAILED
                        db.add(db_ai_msg)
                        db.commit()
                    except Exception as fallback_err:
                        logger.error(f"Fallo final en fallback de texto plano: {fallback_err}")
                        db_ai_msg.status = MessageStatus.FAILED
                        db.add(db_ai_msg)
                        db.commit()

                # Transmitir respuesta de la IA en tiempo real
                ws_payload_ai = {
                    "event": "new_message",
                    "assigned_user_id": contact.assigned_user_id,
                    "data": {
                        "id": db_ai_msg.id,
                        "contact_id": contact.id,
                        "sender_type": db_ai_msg.sender_type.value if hasattr(db_ai_msg.sender_type, "value") else str(db_ai_msg.sender_type),
                        "channel": db_ai_msg.channel.value if hasattr(db_ai_msg.channel, "value") else str(db_ai_msg.channel),
                        "message_type": db_ai_msg.message_type.value if hasattr(db_ai_msg.message_type, "value") else str(db_ai_msg.message_type),
                        "content": db_ai_msg.content,
                        "created_at": db_ai_msg.created_at.isoformat(),
                        "contact": {
                            "id": contact.id,
                            "first_name": contact.first_name,
                            "last_name": contact.last_name,
                            "phone": contact.phone,
                            "assigned_user_id": contact.assigned_user_id
                        }
                    }
                }
                try:
                    import redis.asyncio as redis_async
                    from app.config import settings
                    r_client = redis_async.from_url(settings.REDIS_URL, decode_responses=True)
                    await r_client.publish("crm_live_updates", json.dumps(ws_payload_ai, default=str))
                    await r_client.close()
                except Exception as r_err:
                    logger.error(f"Error publicando respuesta IA en Redis Pub/Sub: {r_err}")

                await manager.broadcast_to_all(ws_payload_ai)

                # Detección y creación automática de Citas en DB si Sofi confirmó agendamiento
                ai_reply_lower = ai_reply.lower()
                if any(k in ai_reply_lower for k in ["agendad", "llamada queda agendada", "agendamos tu llamada", "cita agendada", "llamada para mañana"]):
                    from app.models.base import Appointment, PipelineStage
                    import datetime
                    user_id = contact.assigned_user_id or 1
                    existing_app = db.query(Appointment).filter(Appointment.contact_id == contact.id, Appointment.status != "CANCELLED").first()
                    if not existing_app:
                        target_dt = datetime.datetime.utcnow() + datetime.timedelta(days=1)
                        target_dt = target_dt.replace(hour=14, minute=0, second=0, microsecond=0)
                        
                        new_app = Appointment(
                            contact_id=contact.id,
                            user_id=user_id,
                            datetime=target_dt,
                            status="CONFIRMED",
                            notes="Cita agendada automáticamente por Sofi IA."
                        )
                        db.add(new_app)
                        
                        stages = db.query(PipelineStage).all()
                        stage_map = {s.name: s.id for s in stages}
                        agendada_stage = stage_map.get("Llamada Agendada")
                        if agendada_stage:
                            contact.pipeline_stage_id = agendada_stage
                            db.add(contact)
                            
                        db.commit()
                        db.refresh(new_app)
                        
                        ws_app_payload = {
                            "event": "appointment_created",
                            "data": {
                                "id": new_app.id,
                                "contact_id": contact.id,
                                "user_id": user_id,
                                "datetime": new_app.datetime.isoformat(),
                                "notes": new_app.notes,
                                "status": new_app.status
                            }
                        }
                        await manager.broadcast(ws_app_payload)
                        logger.info(f"Cita creada automáticamente en DB para contacto #{contact.id} (ID cita #{new_app.id})")

    except Exception as e:
        logger.error(f"Error procesando la tarea de WhatsApp en segundo plano: {e}")
        db.rollback()
    finally:
        db.close()

async def crm_daily_backup_job(ctx):
    """
    Tarea cron diaria para realizar copia de seguridad de la base de datos y subirla a Google Drive.
    """
    logger.info("Iniciando tarea cron de copia de seguridad diaria del CRM...")
    db = SessionLocal()
    try:
        from app.services.backup_service import run_database_backup_to_drive
        await run_database_backup_to_drive(db)
    except Exception as e:
        logger.error(f"Error en tarea cron de copia de seguridad diaria: {e}")
    finally:
        db.close()

async def autopilot_sweeper_job(ctx):
    """
    Tarea cron ultra-ligera que se ejecuta cada minuto para garantizar que el 100% de los mensajes recibidos tengan respuesta.
    """
    db = SessionLocal()
    try:
        # Solo atender mensajes recientes de los últimos 15 minutos que hayan quedado sin responder
        import datetime as dt_swp
        cutoff_15m = dt_swp.datetime.utcnow() - dt_swp.timedelta(minutes=15)
        
        contacts = db.query(Contact).filter(
            Contact.chatbot_enabled == True,
            Contact.updated_at >= cutoff_15m
        ).all()
        for c in contacts:
            last_msg = db.query(Message).filter(Message.contact_id == c.id).order_by(Message.created_at.desc()).first()
            if last_msg and last_msg.sender_type == SenderType.CONTACT and last_msg.created_at >= cutoff_15m:
                if dt_swp.datetime.utcnow() - last_msg.created_at > dt_swp.timedelta(seconds=90):
                    # Evitar ráfagas: Si ya se respondió por cualquier vía en los últimos 90 segundos, omitir
                    recent_ai = db.query(Message).filter(
                        Message.contact_id == c.id,
                        Message.sender_type == SenderType.AI,
                        Message.created_at >= dt_swp.datetime.utcnow() - dt_swp.timedelta(seconds=90)
                    ).first()
                    if recent_ai:
                        continue

                    # Verificar si el lead ya se despidió o agradeció finalizando conversación
                    low_text = (last_msg.content or "").lower().strip()
                    goodbye_phrases = ["hasta luego", "hasta pronto", "chao", "adiós", "adios", "nos vemos", "no gracias", "no muchas gracias", "no, gracias", "listo gracias", "ok gracias", "gracias, hasta luego"]
                    if any(p in low_text for p in goodbye_phrases) or ("gracias" in low_text and len(low_text) < 30):
                        ai_last_6h = db.query(Message).filter(
                            Message.contact_id == c.id,
                            Message.sender_type == SenderType.AI,
                            Message.created_at >= dt_swp.datetime.utcnow() - dt_swp.timedelta(hours=6)
                        ).first()
                        if ai_last_6h:
                            logger.info(f"Autopilot Sweeper: Omitiendo {c.phone} (cierre de cortesía detectado).")
                            continue

                    logger.info(f"Autopilot Sweeper: Respondiendo chat desatendido de {c.phone} (ID #{c.id})")
                    ai_reply = await ai_engine.generate_autopilot_reply(db=db, contact=c, last_message=last_msg.content)
                    if ai_reply:
                        db_ai = Message(
                            contact_id=c.id,
                            sender_type=SenderType.AI,
                            channel=ChannelType.WHATSAPP,
                            message_type=MessageType.TEXT,
                            content=ai_reply,
                            status=MessageStatus.SENT
                        )
                        db.add(db_ai)
                        db.commit()
                        
                        is_prop = (c.scheduling_state == "AWAITING_CONFIRMATION") or any(w in ai_reply.lower() for w in ["¿te queda bien", "¿te viene bien", "horario para agendar", "confirmar tu asistencia", "coordinemos una llamada", "llamada informativa", "te agendamos tu cupo"])
                        if is_prop and not c.scheduling_state:
                            c.scheduling_state = "AWAITING_CONFIRMATION"
                            db.add(c)
                            db.commit()
                        if is_prop:
                            btns = [
                                {"id": "btn_confirm_slot", "title": "✅ Sí, confirmar"},
                                {"id": "btn_change_slot", "title": "📅 Cambiar hora"}
                            ]
                            await whatsapp_service.send_interactive_buttons(to_phone=c.phone, body_text=ai_reply, buttons=btns, header_text="ANCLA Special Projects", footer_text="Selecciona tu opción", db=db)
                        else:
                            await whatsapp_service.send_text_message(to_phone=c.phone, message_text=ai_reply, db=db)
    except Exception as e:
        logger.error(f"Error en Autopilot Sweeper job: {e}")
        db.rollback()
    finally:
        db.close()

async def morning_8am_broadcast_job(ctx):
    """
    Job programado de Sofi en la nube (Railway) que se dispara exactamente a las 8:00 AM (COT).
    Envía el mensaje oficial de Liliana León a los confirmados del Miércoles 29 de Julio.
    """
    logger.info("Sofi Worker: Iniciando recordatorio masivo matutino de las 8:00 AM...")
    db = SessionLocal()
    try:
        from app.routers.showroom import get_showroom_citas_json
        data = get_showroom_citas_json(db)
        wednesday_list = [x for x in data if "Miércoles 29" in x['day']]

        logger.info(f"Sofi Worker: Enviando a {len(wednesday_list)} confirmados...")

        for item in wednesday_list:
            phone = item['phone']
            name = item['name'].split()[0] if item['name'] else "Estimado/a"
            hour = item['time']

            msg_body = (
                f"¡Muy buenos días, {name}! 🏠✨\n\n"
                f"Te habla *Liliana León*, Directora Comercial de *ANCLA Special Projects*.\n\n"
                f"Es un gusto saludarte. Queremos recordar tu cita agendada para conocer nuestras soluciones modulares.\n\n"
                f"📍 *Tu cita*: Hoy a las *{hour}*\n"
                f"🏢 *Ubicación*: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n\n"
                f"¿Nos confirmas tu asistencia por favor?\n\n"
                f"¡Quedamos muy atentos a tu visita!\n"
                f"_Liliana León — Directora Comercial, ANCLA Special Projects_"
            )

            buttons = [
                {"id": "btn_confirm_today", "title": "📍 Confirmar Asistencia"},
                {"id": "btn_reschedule", "title": "⏰ Cambiar de Hora"},
                {"id": "btn_contact_liliana", "title": "📲 Hablar con Liliana"}
            ]

            contact_id = item['contact_id']
            db_msg = Message(
                contact_id=contact_id,
                sender_type=SenderType.AI,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=msg_body,
                status=MessageStatus.SENT
            )
            db.add(db_msg)
            db.commit()

            try:
                await whatsapp_service.send_interactive_buttons(
                    to_phone=phone,
                    body_text=msg_body,
                    buttons=buttons,
                    header_text="ANCLA Special Projects",
                    footer_text="Confirmación VIP Showroom Armenia",
                    db=db
                )
            except Exception:
                await whatsapp_service.send_text_message(
                    to_phone=phone,
                    message_text=msg_body,
                    db=db
                )

        logger.info("Sofi Worker: Recordatorio matutino de las 8:00 AM completado exitosamente.")
    except Exception as e:
        logger.error(f"Error en morning_8am_broadcast_job: {e}")
        db.rollback()
    finally:
        db.close()

async def appointment_2h_reminder_cron_job(ctx):
    """
    Tarea cron que se ejecuta cada 15 minutos en Railway para buscar citas programadas dentro de las próximas 2 horas.
    Envía el recordatorio de WhatsApp con botones interactivos y mapas GPS.
    """
    db = SessionLocal()
    try:
        import datetime as dt_mod
        colombia_now = dt_mod.datetime.utcnow() - dt_mod.timedelta(hours=5)
        window_start = colombia_now + dt_mod.timedelta(minutes=105)
        window_end = colombia_now + dt_mod.timedelta(minutes=135)
        
        upcoming_appts = db.query(Appointment).filter(
            Appointment.status == "CONFIRMED",
            Appointment.datetime >= window_start,
            Appointment.datetime <= window_end
        ).all()
        
        for appt in upcoming_appts:
            contact = db.query(Contact).filter(Contact.id == appt.contact_id).first()
            if not contact or not contact.phone:
                continue
                
            recent_reminder = db.query(Message).filter(
                Message.contact_id == contact.id,
                Message.sender_type == SenderType.AI,
                Message.content.ilike("%Te recordamos que hoy%")
            ).first()
            
            if recent_reminder:
                continue
                
            time_str = appt.datetime.strftime("%I:%M %p")
            is_presencial = (appt.appointment_type or "").upper() == "PRESENCIAL"
            
            name = contact.first_name or "Estimado cliente"
            if is_presencial:
                msg_body = (
                    f"¡Hola {name}! 🏠✨ Te recordamos que hoy a las **{time_str}** "
                    f"tenemos agendada tu **Visita Presencial en nuestro Showroom de Armenia** (Av. Centenario, frente a Pan y Miel).\n\n"
                    f"🚗 **Toca para abrir la ruta en tu aplicación preferida**:\n"
                    f"🔹 **Google Maps**: https://maps.google.com/?q=Armenia+Avenida+Centenario+Pan+y+Miel\n"
                    f"🔹 **Waze**: https://waze.com/ul?q=Avenida+Centenario+Armenia+Quindio\n\n"
                    f"¡Nos vemos en un par de horas! 🏡🤝"
                )
            else:
                msg_body = (
                    f"¡Hola {name}! 💻✨ Te recordamos que hoy a las **{time_str}** "
                    f"tenemos agendada tu **Asesoría Virtual (Google Meet / Zoom o Llamada Comercial)** con nuestro equipo de ANCLA Special Projects.\n\n"
                    f"¡En breve nos comunicaremos contigo! 📲🤝"
                )
                
            await whatsapp_service.send_text_message(to_phone=contact.phone, message_text=msg_body, db=db)
            
            db_msg = Message(
                contact_id=contact.id,
                sender_type=SenderType.AI,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=msg_body,
                status=MessageStatus.SENT
            )
            db.add(db_msg)
            db.commit()
    except Exception as e:
        logger.error(f"Error en appointment_2h_reminder_cron_job: {e}")
        db.rollback()
    finally:
        db.close()

async def appointment_24h_reminder_cron_job(ctx):
    """
    Tarea cron para enviar un recordatorio 24h antes de la cita.
    REGLA: Únicamente se envía si la cita fue reservada con MÁS de 24 horas de antelación
    ((datetime - created_at) > 86400 segundos). Si fue agendada en las últimas 24h, se omite.
    """
    db = SessionLocal()
    try:
        import datetime as dt_mod
        colombia_now = dt_mod.datetime.utcnow() - dt_mod.timedelta(hours=5)
        window_start = colombia_now + dt_mod.timedelta(hours=23)
        window_end = colombia_now + dt_mod.timedelta(hours=25)
        
        upcoming_appts = db.query(Appointment).filter(
            Appointment.status == "CONFIRMED",
            Appointment.datetime >= window_start,
            Appointment.datetime <= window_end
        ).all()
        
        for appt in upcoming_appts:
            contact = db.query(Contact).filter(Contact.id == appt.contact_id).first()
            if not contact or not contact.phone:
                continue

            # REGLA EXPLICITA: Si la cita se creó dentro de las últimas 24h previas a la fecha del compromiso, NO enviar 24h reminder
            if appt.created_at and (appt.datetime - appt.created_at).total_seconds() <= 86400:
                logger.info(f"Omite recordatorio 24h para cita #{appt.id}: fue agendada dentro de las 24h previas.")
                continue
                
            recent_reminder = db.query(Message).filter(
                Message.contact_id == contact.id,
                Message.sender_type == SenderType.AI,
                Message.content.ilike("%Mañana es el gran día%")
            ).first()
            
            if recent_reminder:
                continue
                
            time_str = appt.datetime.strftime("%I:%M %p").lstrip('0')
            is_presencial = (appt.appointment_type or "").upper() == "PRESENCIAL"
            name = contact.first_name or "Estimado cliente"
            
            days_es = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            months_es = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
            formatted_date = f"{days_es[appt.datetime.weekday()]} {appt.datetime.day} de {months_es[appt.datetime.month]}"

            if is_presencial:
                msg_body = (
                    f"¡Hola {name}! 🏡✨ Mañana es el gran día (**{formatted_date}** a las **{time_str}**) "
                    f"para tu **Visita Presencial en nuestro Showroom de Armenia** (Av. Centenario, frente a Pan y Miel).\n\n"
                    f"¿Nos confirmas tu asistencia para reservar la atención de nuestro asesor?"
                )
            else:
                msg_body = (
                    f"¡Hola {name}! 💻✨ Mañana es el gran día (**{formatted_date}** a las **{time_str}**) "
                    f"para tu **Asesoría Virtual (Google Meet / Llamada)** con nuestro equipo de ANCLA Special Projects.\n\n"
                    f"¿Nos confirmas tu disponibilidad para la sesión?"
                )

            buttons = [
                {"id": "btn_confirm_slot", "title": "✅ Sí, confirmo"},
                {"id": "btn_time_other", "title": "📅 Reagendar"}
            ]

            await whatsapp_service.send_interactive_buttons(
                to_phone=contact.phone,
                body_text=msg_body,
                buttons=buttons,
                header_text="ANCLA Special Projects",
                footer_text="Confirmación Cita VIP",
                db=db
            )

            db_msg = Message(
                contact_id=contact.id,
                sender_type=SenderType.AI,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=msg_body,
                status=MessageStatus.SENT
            )
            db.add(db_msg)
            db.commit()
    except Exception as e:
        logger.error(f"Error en appointment_24h_reminder_cron_job: {e}")
        db.rollback()
    finally:
        db.close()

class WorkerSettings:
    """Configuración que lee arq para lanzar el Worker"""
    functions = [process_whatsapp_message, crm_daily_backup_job, autopilot_sweeper_job, morning_8am_broadcast_job, appointment_2h_reminder_cron_job, appointment_24h_reminder_cron_job]
    cron_jobs = [
        cron(crm_daily_backup_job, hour=0, minute=0), # Todos los días a la medianoche
        cron(autopilot_sweeper_job, minute=set(range(60))), # Se ejecuta cada minuto automáticamente (0% sobrecarga)
        cron(appointment_2h_reminder_cron_job, minute=set(range(0, 60, 15))), # Cada 15 minutos
        cron(appointment_24h_reminder_cron_job, minute=set(range(0, 60, 30))) # Cada 30 minutos
    ]
    redis_settings = redis_settings
