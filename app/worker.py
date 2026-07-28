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
    Transcribe una nota de voz/audio recibida en WhatsApp usando el Speech-to-Text de Google Gemini.
    """
    if not file_bytes:
        return None
        
    try:
        import base64
        import httpx
        from app.models.base import SystemSetting
        
        # 1. Obtener la clave API de Gemini
        api_key = None
        db_key = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
        if db_key and db_key.value:
            api_key = db_key.value
        if not api_key:
            api_key = settings.GEMINI_API_KEY
            
        if not api_key:
            logger.error("No se pudo obtener la clave API para la transcripción del audio.")
            return None
            
        # Si es una clave de OpenRouter, usaremos la clave nativa de Gemini
        if api_key.startswith("sk-or-v1"):
            api_key = settings.GEMINI_API_KEY
            
        if not api_key:
            logger.error("No hay una clave API válida de Gemini para el transcriptor nativo.")
            return None

        # 2. Formatear y preparar el payload multimodal para Gemini
        base64_audio = base64.b64encode(file_bytes).decode('utf-8')
        
        # Mime type por defecto para notas de voz en WhatsApp es audio/ogg
        clean_mime = mime_type.split(";")[0] if mime_type else "audio/ogg"
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Por favor, transcribe esta nota de voz a texto en español de forma precisa y directa. "
                                "Devuelve ÚNICAMENTE la transcripción limpia sin comentarios tuyos, saludos ni aclaraciones."
                            )
                        },
                        {
                            "inlineData": {
                                "mimeType": clean_mime,
                                "data": base64_audio
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0
            }
        }
        
        # 3. Consultar la API
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, timeout=25.0)
            if res.status_code == 200:
                data = res.json()
                transcription = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                logger.info(f"Transcripción exitosa del audio: '{transcription[:50]}...'")
                return transcription
            else:
                logger.error(f"Error llamando a Gemini transcripción (status {res.status_code}): {res.text}")
                return None
                
    except Exception as e:
        logger.error(f"Excepción en la transcripción de audio: {e}")
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
                await manager.broadcast(ws_payload)
    except Exception as e:
        logger.error(f"Error en process_ai_response_after_consent: {e}")
    finally:
        db.close()


async def process_whatsapp_message(ctx, payload: dict):
    """
    Tarea asíncrona para procesar el evento de WhatsApp recibido desde Meta.
    Realiza validación de Habeas Data, persistencia, asignación, RAG, e IA.
    """
    logger.info("Iniciando procesamiento de tarea de WhatsApp en segundo plano...")
    
    value = payload.get("value", {})
    messages = value.get("messages", [])
    if not messages:
        logger.info("No se encontraron mensajes en el payload.")
        return
        
    msg = messages[0]
    external_msg_id = msg.get("id")
    from_phone = msg.get("from")
    
    if not from_phone:
        logger.info("El mensaje no tiene teléfono de origen.")
        return

    # Abrir sesión de base de datos síncrona
    db: Session = SessionLocal()
    try:
        # 1. Comprobar duplicado en la base de datos relacional
        exists = db.query(Message).filter(Message.external_message_id == external_msg_id).first()
        if exists:
            logger.info(f"Mensaje duplicado de WhatsApp omitido en worker: {external_msg_id}")
            return

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
            
            # Transcribir audio asíncronamente usando Gemini
            transcription = None
            if file_bytes:
                transcription = await transcribe_whatsapp_audio(file_bytes, mime_type, db)
                
            if transcription:
                content = f"[Media ID: {target_id}]\n[🎙️ Nota de voz recibida]: \"{transcription}\""
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
        else:
            # Garantizar que Piloto IA permanezca activo a menos que haya pedido un humano
            if not contact.chatbot_enabled:
                msg_lower_check = (content or "").lower()
                human_requests = ["hablar con humano", "asesor humano", "persona real", "/humano"]
                if not any(h in msg_lower_check for h in human_requests):
                    contact.chatbot_enabled = True
                    db.add(contact)
                    db.commit()

        # 3. Procesar Atribución de Meta Ads
        referral = msg.get("referral")
        if referral or is_new or "Meta Ads" not in (contact.source or ""):
            process_meta_ads_attribution(msg, contact, content, db)
            db.add(contact)
            db.commit()

        # 4. Asignación de lead por Round Robin si es nuevo
        if is_new or contact.assigned_user_id is None:
            assign_lead_round_robin(db, contact)
            db.add(contact)
            db.commit()

        # Determinar el tipo de mensaje en BD
        db_msg_type = MessageType.TEXT
        if msg_type in ["audio", "voice"]:
            db_msg_type = MessageType.AUDIO
            if media_id:
                logger.info(f"Procesando transcripción de audio para {contact.phone} (Media ID: {media_id})...")
                try:
                    local_audio_path = await whatsapp_service.download_media(media_id, db)
                    if local_audio_path:
                        from app.services.transcription import transcribe_audio_file
                        transcript = await transcribe_audio_file(local_audio_path)
                        if transcript:
                            content = transcript
                            logger.info(f"Audio transcripto con éxito para {contact.phone}: '{content}'")
                except Exception as audio_err:
                    logger.error(f"Error procesando transcripción de audio: {audio_err}")
        elif msg_type == "document":
            db_msg_type = MessageType.DOCUMENT
        elif msg_type == "video":
            db_msg_type = MessageType.VIDEO
        elif msg_type == "image":
            db_msg_type = MessageType.IMAGE

        # 5. Guardar mensaje recibido en BD
        db_msg = Message(
            contact_id=contact.id,
            sender_type=SenderType.CONTACT,
            channel=ChannelType.WHATSAPP,
            message_type=db_msg_type,
            content=content,
            status=MessageStatus.DELIVERED,
            external_message_id=external_msg_id
        )
        db.add(db_msg)
        db.commit()
        db.refresh(db_msg)

        # Transmitir en tiempo real
        ws_payload = {
            "event": "new_message",
            "assigned_user_id": contact.assigned_user_id,
            "data": {
                "id": db_msg.id,
                "contact_id": contact.id,
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

        # 7. Evaluar Respuestas a Botones de Habeas Data
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
        contact.chatbot_enabled = True
        db.add(contact)
        db.commit()

        # 9. Disparadores de automatizaciones de palabras clave
        from app.services.automation import check_message_keywords_trigger
        check_message_keywords_trigger(db, contact, content)

        # 10. Piloto Automático de la Inteligencia Artificial (Sofi) con Debounce de Acumulación (60.0 Segundos)
        if contact.chatbot_enabled and msg_type in ["text", "audio", "voice", "interactive", "button", "list_reply", "button_reply"]:
            # Debounce: Esperar 60.0 segundos para agrupar mensajes consecutivos del mismo cliente
            await asyncio.sleep(60.0)
            
            # Verificar si llegó un mensaje MÁS RECIENTE del mismo contacto
            newer_msg = db.query(Message).filter(
                Message.contact_id == contact.id,
                Message.sender_type == SenderType.CONTACT,
                Message.created_at > db_msg.created_at
            ).first()

            if newer_msg:
                logger.info(f"Debounce: Omitiendo respuesta parcial de mensaje ID {db_msg.id} porque {contact.phone} envió un mensaje posterior.")
                return

            # Concatenar mensajes recientes de los últimos 60 segundos
            import datetime as dt_debounce
            recent_msgs = db.query(Message).filter(
                Message.contact_id == contact.id,
                Message.sender_type == SenderType.CONTACT,
                Message.created_at >= db_msg.created_at - dt_debounce.timedelta(seconds=60)
            ).order_by(Message.created_at.asc()).all()

            accumulated_text = " ".join([m.content for m in recent_msgs if m.content]).strip() or content

            ai_reply = await ai_engine.generate_autopilot_reply(
                db=db,
                contact=contact,
                last_message=accumulated_text
            )
            if ai_reply:
                # Evitar envíos duplicados por el chatbot y spam (cooldown de 45s)
                import datetime as dt_cooldown
                ultimo_mensaje_ia = db.query(Message).filter(
                    Message.contact_id == contact.id,
                    Message.sender_type == SenderType.AI
                ).order_by(Message.created_at.desc()).first()

                if ultimo_mensaje_ia:
                    if ultimo_mensaje_ia.content == ai_reply or (dt_cooldown.datetime.utcnow() - ultimo_mensaje_ia.created_at < dt_cooldown.timedelta(seconds=45)):
                        logger.info("Evitando duplicado o ráfaga de chatbot en worker (anti-spam 45s).")
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

                # Enviar a la API de WhatsApp de Meta (con envío automático de botones interactivos para propuestas)
                try:
                    is_initial_greeting = any(w in ai_reply.lower() for w in ["showroom presencial", "fechas de exhibición", "cupo de visita presencial", "selecciona el día de tu preferencia", "gracias por registrarte a la gran inauguración", "selecciona el día que prefieres visitarnos"])
                    is_time_selection = "para tu atención presencial el" in ai_reply.lower() or "selecciona la hora de tu preferencia" in ai_reply.lower()
                    is_secondary_hours = "contamos también con los siguientes horarios" in ai_reply.lower() or "cuál de estos tres te queda mejor" in ai_reply.lower()
                    is_proposal = (contact.scheduling_state == "AWAITING_CONFIRMATION") or any(w in ai_reply.lower() for w in ["¿te queda bien", "¿te viene bien", "horario para agendar", "confirmar tu asistencia", "coordinemos una llamada", "llamada informativa", "te agendamos tu cupo"])
                    
                    if (is_proposal or is_time_selection or is_secondary_hours) and not contact.scheduling_state:
                        contact.scheduling_state = "AWAITING_CONFIRMATION"
                        db.add(contact)
                        db.commit()
                    
                    if is_secondary_hours or is_time_selection:
                        sections = [
                            {
                                "title": "Horarios de la Mañana",
                                "rows": [
                                    {"id": "btn_time_1000", "title": "10:00 AM", "description": "Atención Showroom Armenia"},
                                    {"id": "btn_time_1130", "title": "11:30 AM", "description": "Atención Showroom Armenia"}
                                ]
                            },
                            {
                                "title": "Horarios de la Tarde",
                                "rows": [
                                    {"id": "btn_time_1400", "title": "02:00 PM", "description": "Atención Showroom Armenia"},
                                    {"id": "btn_time_1600", "title": "04:00 PM", "description": "Atención Showroom Armenia"},
                                    {"id": "btn_time_1700", "title": "05:00 PM", "description": "Atención Showroom Armenia"}
                                ]
                            }
                        ]
                        await whatsapp_service.send_interactive_list(
                            to_phone=contact.phone,
                            header_text="Horarios Disponibles",
                            body_text=ai_reply,
                            button_text="📅 Ver Horarios",
                            sections=sections,
                            footer_text="Ancla Special Projects",
                            db=db
                        )
                    elif is_initial_greeting:
                        buttons = [
                            {"id": "btn_day_mar28", "title": "📍 Martes 28 Julio"},
                            {"id": "btn_day_mie29", "title": "📍 Miérc 29 Julio"}
                        ]
                        await whatsapp_service.send_interactive_buttons(
                            to_phone=contact.phone,
                            body_text=ai_reply,
                            buttons=buttons,
                            header_text="ANCLA Special Projects",
                            footer_text="Selecciona el día de tu preferencia",
                            db=db
                        )
                    elif is_proposal:
                        buttons = [
                            {"id": "btn_confirm_slot", "title": "✅ Sí, confirmar"},
                            {"id": "btn_change_slot", "title": "📅 Cambiar hora"}
                        ]
                        await whatsapp_service.send_interactive_buttons(
                            to_phone=contact.phone,
                            body_text=ai_reply,
                            buttons=buttons,
                            header_text="ANCLA Special Projects",
                            footer_text="Selecciona tu opción",
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
                    logger.error(f"Error al enviar mensaje por WhatsApp API: {send_err}")
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
        contacts = db.query(Contact).filter(Contact.chatbot_enabled == True).all()
        for c in contacts:
            last_msg = db.query(Message).filter(Message.contact_id == c.id).order_by(Message.created_at.desc()).first()
            if last_msg and last_msg.sender_type == SenderType.CONTACT:
                import datetime as dt_swp
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

class WorkerSettings:
    """Configuración que lee arq para lanzar el Worker"""
    functions = [process_whatsapp_message, crm_daily_backup_job, autopilot_sweeper_job]
    cron_jobs = [
        cron(crm_daily_backup_job, hour=0, minute=0), # Todos los días a la medianoche
        cron(autopilot_sweeper_job, minute=set(range(60))) # Se ejecuta cada minuto automáticamente (0% sobrecarga)
    ]
    redis_settings = redis_settings
