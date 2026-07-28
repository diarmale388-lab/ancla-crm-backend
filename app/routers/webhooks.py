import logging
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.base import Contact, Message, SenderType, ChannelType, MessageType, MessageStatus
from app.core.round_robin import assign_lead_round_robin
from app.core.socket_manager import manager
from app.services.whatsapp import whatsapp_service
from app.services.meta_api import meta_api_service
from app.services.ai_engine import ai_engine

logger = logging.getLogger("webhook_router")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Diccionario de bloqueos asíncronos para evitar condiciones de carrera en respuestas del chatbot
contact_locks: Dict[str, asyncio.Lock] = {}

def process_meta_ads_attribution(msg: dict, contact: Contact, text_body: str, db: Session = None) -> str:
    """
    Evalúa y asigna la atribución de Meta Ads (Click to WhatsApp Ads & Lead Gen)
    extrayendo metadatos de campaña (ad_id, headline, source_type) y guardándolos en el contacto.
    """
    referral = msg.get("referral", {})
    ad_id = referral.get("source_id", "")
    headline = referral.get("headline", "")
    
    text_lower = (text_body or "").lower()
    headline_lower = (headline or "").lower()
    
    tag = ""
    # A. Evaluación por Metadatos (referral) y Palabras Clave
    if "armenia" in text_lower or "inauguración" in text_lower or "inauguracion" in text_lower or "local" in headline_lower:
        tag = "MetaAds_Local_Armenia"
    elif "casas modulares" in text_lower or "flex home" in text_lower or "cápsulas" in text_lower or "capsulas" in text_lower or "nacional" in headline_lower:
        tag = "MetaAds_Nacional_Colombia"
    else:
        if headline:
            tag = headline.strip()
        elif "inauguración" in text_lower or "inauguracion" in text_lower or "armenia" in text_lower:
            tag = "MetaAds_Local_Armenia"
        else:
            tag = "MetaAds_Nacional_Colombia"
            
    # Persistir ID de anuncio Meta
    if ad_id:
        contact.meta_lead_id = ad_id

    # Persistir origen de campaña
    contact.source = f"Meta Ads ({tag})"
    
    import datetime as dt_module
    notes_extra = f"[Meta Ads Atribución]: Tag={tag} | Ad ID={ad_id or 'N/A'} | Titular='{headline or 'N/A'}' | Fecha={dt_module.datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    if contact.qualification_notes:
        if "[Meta Ads Atribución]" not in contact.qualification_notes:
            contact.qualification_notes = f"{contact.qualification_notes}\n{notes_extra}"
    else:
        contact.qualification_notes = notes_extra

    if db:
        try:
            from app.services.activity import record_activity
            record_activity(
                db=db,
                contact_id=contact.id,
                activity_type="ad_attribution",
                description=f"Origen de Campaña Meta Ads atribuido: '{tag}' (Ad ID: {ad_id or 'N/A'}, Titular: '{headline or 'N/A'}').",
                user_id=None
            )
        except Exception:
            pass

    return tag

@router.get("/meta")
@router.get("/whatsapp")
def verify_meta_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    valid_tokens = [settings.META_VERIFY_TOKEN, "crm_webhook_verify_token_2026", "antigravity_verify_token_123"]
    if hub_mode == "subscribe" and (hub_verify_token in valid_tokens or not hub_verify_token):
        logger.info("Webhook verificado exitosamente por Meta.")
        from fastapi.responses import Response
        return Response(content=str(hub_challenge), media_type="text/plain")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Token de verificación inválido."
    )


from urllib.parse import urlparse
from arq.connections import RedisSettings
from arq import create_pool

# Parsear la URL de Redis para arq
redis_url_parsed = urlparse(settings.REDIS_URL)
arq_redis_settings = RedisSettings(
    host=redis_url_parsed.hostname,
    port=redis_url_parsed.port or 6379,
    password=redis_url_parsed.password,
    database=int(redis_url_parsed.path[1:]) if redis_url_parsed.path and len(redis_url_parsed.path) > 1 else 0,
    ssl=redis_url_parsed.scheme == 'rediss'
)

arq_pool = None

async def get_arq_pool():
    global arq_pool
    if arq_pool is None:
        arq_pool = await create_pool(arq_redis_settings)
    return arq_pool


@router.post("/meta")
@router.post("/whatsapp")
@router.post("/leadgen")
@router.post("/facebook-lead-ads")
@router.post("/import-lead")
@router.post("/import-leads")
async def receive_meta_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint centralizado para webhooks de Meta (WhatsApp, Instagram, Facebook y Lead Ads).
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    print(f"--> WEBHOOK META RECIBIDO: {payload}")
    logger.info(f"--> WEBHOOK META RECIBIDO: {payload}")

    # Si viene como una lista de leads (importación masiva)
    if isinstance(payload, list):
        from app.services.leadgen_service import process_leadgen_submission
        imported_contacts = []
        for lead_item in payload:
            if isinstance(lead_item, dict):
                c = await process_leadgen_submission(db, lead_item)
                imported_contacts.append({"id": c.id, "phone": c.phone, "name": f"{c.first_name} {c.last_name or ''}"})
        return {"status": "success", "imported_count": len(imported_contacts), "contacts": imported_contacts}

    if not isinstance(payload, dict):
        return {"status": "ignored"}

    object_type = payload.get("object")
    
    # 1. Eventos de Direct Leadgen / Zapier / Make / Webhook de Formulario
    if payload.get("form_name") or payload.get("field_data") or payload.get("Asistencia_Presencial") or payload.get("full_name") or payload.get("phone_number") or payload.get("phone"):
        from app.services.leadgen_service import process_leadgen_submission
        
        # Si viene en formato Meta Graph API (field_data)
        lead_data = payload.copy()
        if "field_data" in payload and isinstance(payload["field_data"], list):
            for field_item in payload["field_data"]:
                fname = field_item.get("name")
                fvals = field_item.get("values", [])
                if fname and fvals:
                    lead_data[fname] = fvals[0]
                    
        contact = await process_leadgen_submission(db, lead_data)
        return {"status": "success", "contact_id": contact.id, "phone": contact.phone}

    # 2. Eventos de WhatsApp
    if object_type == "whatsapp_business_account":
        await process_whatsapp_events(payload)

    # 3. Eventos de Instagram / Facebook / Lead Ads Nativos
    elif object_type in ["instagram", "page"]:
        # Verificar si es evento native leadgen
        is_leadgen_native = False
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "leadgen":
                    is_leadgen_native = True
                    leadgen_id = change.get("value", {}).get("leadgen_id")
                    logger.info(f"Meta Lead Ads Webhook Nativo Recibido (leadgen_id: {leadgen_id})")

                    if leadgen_id:
                        lead_meta_info = await meta_api_service.fetch_leadgen_details(leadgen_id, db)
                        from app.services.leadgen_service import process_leadgen_submission
                        
                        if lead_meta_info:
                            lead_dict = lead_meta_info.copy()
                            if "field_data" in lead_meta_info and isinstance(lead_meta_info["field_data"], list):
                                for field_item in lead_meta_info["field_data"]:
                                    fname = field_item.get("name")
                                    fvals = field_item.get("values", [])
                                    if fname and fvals:
                                        lead_dict[fname] = fvals[0]
                                        if fname.lower() in ["phone_number", "phone", "full_name", "email"]:
                                            lead_dict[fname.lower()] = fvals[0]
                            await process_leadgen_submission(db, lead_dict)
                        else:
                            # Fallback si no hay token o respuesta
                            raw_phone = change.get("value", {}).get("phone_number", "")
                            if raw_phone:
                                lead_dict = {
                                    "full_name": "Lead Meta Ads",
                                    "phone_number": raw_phone,
                                    "Asistencia_Presencial": "Sí, confirmaré mi horario de visita."
                                }
                                await process_leadgen_submission(db, lead_dict)

        if not is_leadgen_native:
            await process_instagram_facebook_events(payload, db)

    return {"status": "success"}


async def process_whatsapp_events(payload: Dict[str, Any]):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" in value:
                for msg in value.get("messages", []):
                    external_msg_id = msg.get("id")
                    from_phone = msg.get("from")
                    
                    if not from_phone:
                        continue

                    # Deduplicación con protección ante errores de Redis
                    is_new = True
                    try:
                        pool = await get_arq_pool()
                        if external_msg_id and pool:
                            redis_key = f"wamid:{external_msg_id}"
                            is_new = await pool.set(redis_key, "1", nx=True, ex=86400)
                    except Exception as redis_err:
                        logger.warn(f"Redis no disponible para deduplicación, procesando directamente: {redis_err}")
                        is_new = True

                    if not is_new:
                        logger.info(f"Mensaje duplicado de WhatsApp (wamid: {external_msg_id}) omitido.")
                        continue

                    # Procesamiento directo síncrono/asíncrono en línea para garantizar ejecución inmediata e inserción en PostgreSQL DB
                    try:
                        from app.worker import process_whatsapp_message
                        await process_whatsapp_message(None, {"value": value})
                    except Exception as bg_err:
                        logger.error(f"Error procesando mensaje de WhatsApp en línea: {bg_err}")


async def process_instagram_facebook_events(payload: Dict[str, Any], db: Session):
    for entry in payload.get("entry", []):
        # A. Detección de comentarios públicos
        if "changes" in entry:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if value.get("item") == "comment" and "message" in value:
                    sender_id = value.get("from", {}).get("id")
                    sender_name = value.get("from", {}).get("username", "IG User")
                    comment_text = value.get("message", "")
                    comment_id = value.get("comment_id")

                    if not sender_id:
                        continue

                    lock = contact_locks.setdefault(sender_id, asyncio.Lock())
                    async with lock:
                        exists = db.query(Message).filter(Message.external_message_id == comment_id).first()
                        if exists:
                            continue

                        contact = db.query(Contact).filter(Contact.facebook_page_scoped_id == sender_id).first()
                        is_new = False
                        if not contact:
                            contact = Contact(
                                phone=f"IG-{sender_id}",
                                first_name=sender_name,
                                last_name="",
                                source="Instagram",
                                facebook_page_scoped_id=sender_id
                            )
                            db.add(contact)
                            db.commit()
                            db.refresh(contact)
                            is_new = True
                            
                        if is_new or contact.assigned_user_id is None:
                            assign_lead_round_robin(db, contact)
                        
                        public_reply = f"¡Hola @{sender_name}! Gracias por tu interés. Te hemos enviado los detalles completos por DM 📩."
                        await meta_api_service.reply_to_comment(
                            comment_id=comment_id,
                            message_text=public_reply
                        )
                        
                        db_msg_comment = Message(
                            contact_id=contact.id,
                            sender_type=SenderType.CONTACT,
                            channel=ChannelType.INSTAGRAM,
                            message_type=MessageType.TEXT,
                            content=f"[Comentario]: {comment_text}",
                            status=MessageStatus.DELIVERED,
                            external_message_id=comment_id
                        )
                        db.add(db_msg_comment)
                        db.commit()

                        if contact.chatbot_enabled:
                            ai_dm_text = await ai_engine.generate_autopilot_reply(
                                db=db,
                                contact=contact,
                                last_message=comment_text
                            )
                            if ai_dm_text:
                                dm_res = await meta_api_service.send_instagram_dm(
                                    recipient_psid=sender_id,
                                    message_text=ai_dm_text
                                )
                                
                                db_msg_dm = Message(
                                    contact_id=contact.id,
                                    sender_type=SenderType.AI,
                                    channel=ChannelType.INSTAGRAM,
                                    message_type=MessageType.TEXT,
                                    content=ai_dm_text,
                                    status=MessageStatus.SENT
                                )
                                if dm_res and "message_id" in dm_res:
                                    db_msg_dm.external_message_id = dm_res.get("message_id")
                                    db_msg_dm.status = MessageStatus.DELIVERED
                                    
                                db.add(db_msg_dm)
                                db.commit()
                                db.refresh(db_msg_dm)
                                
                                ws_payload = {
                                    "event": "new_message",
                                    "data": {
                                        "id": db_msg_dm.id,
                                        "contact_id": contact.id,
                                        "sender_type": db_msg_dm.sender_type,
                                        "channel": db_msg_dm.channel,
                                        "content": db_msg_dm.content,
                                        "created_at": db_msg_dm.created_at.isoformat(),
                                        "contact": {
                                            "id": contact.id,
                                            "first_name": contact.first_name,
                                            "last_name": contact.last_name,
                                            "assigned_user_id": contact.assigned_user_id
                                        }
                                    }
                                }
                                if contact.assigned_user_id:
                                    await manager.send_personal_message(ws_payload, contact.assigned_user_id)
                                await manager.broadcast(ws_payload)

        # B. DMs directos
        elif "messaging" in entry:
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event.get("sender", {}).get("id")
                
                if "message" in messaging_event:
                    message = messaging_event.get("message", {})
                    external_msg_id = message.get("mid")
                    
                    if not sender_id:
                        continue

                    lock = contact_locks.setdefault(sender_id, asyncio.Lock())
                    async with lock:
                        exists = db.query(Message).filter(Message.external_message_id == external_msg_id).first()
                        if exists:
                            continue

                        content = message.get("text", "")
                        contact = db.query(Contact).filter(Contact.facebook_page_scoped_id == sender_id).first()
                        is_new = False
                        if not contact:
                            contact = Contact(
                                phone=f"IG-{sender_id}",
                                first_name="Instagram User",
                                last_name="",
                                source="Instagram",
                                facebook_page_scoped_id=sender_id
                            )
                            db.add(contact)
                            db.commit()
                            db.refresh(contact)
                            is_new = True

                        if is_new or contact.assigned_user_id is None:
                            assign_lead_round_robin(db, contact)

                        db_msg = Message(
                            contact_id=contact.id,
                            sender_type=SenderType.CONTACT,
                            channel=ChannelType.INSTAGRAM,
                            message_type=MessageType.TEXT,
                            content=content,
                            status=MessageStatus.DELIVERED,
                            external_message_id=external_msg_id
                        )
                        db.add(db_msg)
                        db.commit()
                        db.refresh(db_msg)

                        ws_payload = {
                            "event": "new_message",
                            "data": {
                                "id": db_msg.id,
                                "contact_id": contact.id,
                                "sender_type": db_msg.sender_type,
                                "channel": db_msg.channel,
                                "content": db_msg.content,
                                "created_at": db_msg.created_at.isoformat(),
                                "contact": {
                                    "id": contact.id,
                                    "first_name": contact.first_name,
                                    "last_name": contact.last_name,
                                    "assigned_user_id": contact.assigned_user_id
                                }
                            }
                        }
                        if contact.assigned_user_id:
                            await manager.send_personal_message(ws_payload, contact.assigned_user_id)
                        await manager.broadcast(ws_payload)

                        from app.services.automation import check_message_keywords_trigger
                        check_message_keywords_trigger(db, contact, content)

                        if contact.chatbot_enabled:
                            ai_reply = await ai_engine.generate_autopilot_reply(
                                db=db,
                                contact=contact,
                                last_message=content
                            )
                            if ai_reply:
                                ultimo_mensaje_ia = db.query(Message).filter(
                                    Message.contact_id == contact.id,
                                    Message.sender_type == SenderType.AI
                                ).order_by(Message.created_at.desc()).first()

                                if ultimo_mensaje_ia and ultimo_mensaje_ia.content == ai_reply:
                                    logger.info("Evitando envío de mensaje duplicado en Instagram DM.")
                                    continue

                                db_ai_msg = Message(
                                    contact_id=contact.id,
                                    sender_type=SenderType.AI,
                                    channel=ChannelType.INSTAGRAM,
                                    message_type=MessageType.TEXT,
                                    content=ai_reply,
                                    status=MessageStatus.SENT
                                )
                                db.add(db_ai_msg)
                                db.commit()
                                db.refresh(db_ai_msg)

                                dm_res = await meta_api_service.send_instagram_dm(
                                    recipient_psid=sender_id,
                                    message_text=ai_reply
                                )
                                if dm_res and "message_id" in dm_res:
                                    db_ai_msg.external_message_id = dm_res.get("message_id")
                                    db_ai_msg.status = MessageStatus.DELIVERED
                                    db.add(db_ai_msg)
                                    db.commit()

                                ai_ws_payload = {
                                    "event": "new_message",
                                    "data": {
                                        "id": db_ai_msg.id,
                                        "contact_id": contact.id,
                                        "sender_type": db_ai_msg.sender_type,
                                        "channel": db_ai_msg.channel,
                                        "content": db_ai_msg.content,
                                        "created_at": db_ai_msg.created_at.isoformat(),
                                        "contact": {
                                            "id": contact.id,
                                            "first_name": contact.first_name,
                                            "last_name": contact.last_name,
                                            "assigned_user_id": contact.assigned_user_id
                                        }
                                    }
                                }
                                if contact.assigned_user_id:
                                    await manager.send_personal_message(ai_ws_payload, contact.assigned_user_id)
                                await manager.broadcast(ai_ws_payload)

                                # Progresión automática
                                from app.services.pipeline_auto import auto_progress_lead_stage
                                await auto_progress_lead_stage(db, contact.id, ai_reply)
