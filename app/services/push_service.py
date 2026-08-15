import json
import logging
import asyncio
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from pywebpush import webpush, WebPushException

from app.config import settings
from app.models.base import PushSubscription, Contact, Message, User

import os

logger = logging.getLogger("push_service")

def _get_vapid_claims() -> Dict[str, str]:
    return {
        "sub": settings.VAPID_CLAIM_EMAIL
    }

def _get_vapid_private_key() -> str:
    """
    Obtiene la ruta absoluta al archivo PEM de la clave privada VAPID
    para que pywebpush lo cargue de forma 100% confiable sin errores de deserialización.
    """
    # 1. Comprobar ruta directa configurada
    configured_path = getattr(settings, "VAPID_PRIVATE_KEY_PATH", "vapid_private.pem")
    if configured_path and os.path.exists(configured_path):
        return os.path.abspath(configured_path)

    # 2. Comprobar en el directorio raíz del backend
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    backend_pem = os.path.join(backend_dir, "vapid_private.pem")
    if os.path.exists(backend_pem):
        return backend_pem

    # 3. Si no existe en disco pero está en settings, escribirlo
    if settings.VAPID_PRIVATE_KEY:
        try:
            pem_content = settings.VAPID_PRIVATE_KEY.replace('\\n', '\n')
            with open(backend_pem, "w", encoding="utf-8") as f:
                f.write(pem_content)
            return backend_pem
        except Exception as write_err:
            logger.warning(f"No se pudo escribir vapid_private.pem temporal: {write_err}")
            return settings.VAPID_PRIVATE_KEY.replace('\\n', '\n')

    return "vapid_private.pem"

def _send_single_webpush_sync(sub_dict: Dict[str, Any], payload_str: str, endpoint: str) -> tuple[bool, Optional[int]]:
    """
    Función síncrona para ejecutar pywebpush en un hilo separado (para no bloquear el event loop).
    Incluye cabeceras Urgency: high (RFC 8030) para despertar celulares Android en Doze Mode.
    Retorna (éxito: bool, http_status_code: Optional[int]).
    """
    try:
        response = webpush(
            subscription_info=sub_dict,
            data=payload_str,
            vapid_private_key=_get_vapid_private_key(),
            vapid_claims=_get_vapid_claims(),
            headers={
                "Urgency": "high",
                "Topic": "crm_messages"
            },
            ttl=86400 # 24 horas de vigencia en el servidor de push (FCM / APNs)
        )
        status_code = getattr(response, "status_code", 201)
        logger.info(f"WebPush entregado con éxito a {endpoint[:40]}... (Status: {status_code})")
        return True, status_code
    except WebPushException as ex:
        status_code = None
        if ex.response is not None:
            status_code = ex.response.status_code
            logger.warning(f"WebPush error con código {status_code} para {endpoint[:40]}...: {ex}")
        else:
            logger.error(f"WebPush error de conexión: {ex}")
        return False, status_code
    except Exception as e:
        logger.error(f"Excepción inesperada en pywebpush: {e}")
        return False, None


async def send_webpush_to_subscription(
    subscription: PushSubscription,
    payload: Dict[str, Any],
    db: Optional[Session] = None
) -> bool:
    """
    Envía una notificación Push a una suscripción específica.
    Si el servidor FCM/APNs responde con 404 o 410 (suscripción expirada o revocada),
    la marca automáticamente como inactiva en la base de datos.
    """
    sub_dict = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth
        }
    }
    payload_str = json.dumps(payload, ensure_ascii=False)

    success, status_code = await asyncio.to_thread(
        _send_single_webpush_sync,
        sub_dict,
        payload_str,
        subscription.endpoint
    )

    # Si la suscripción expiró o el usuario la borró del navegador (404/410 Gone)
    if not success and status_code in [404, 410]:
        logger.info(f"Desactivando suscripción Push obsoleta (ID: {subscription.id}, Code: {status_code})")
        if db:
            try:
                subscription.is_active = False
                db.add(subscription)
                db.commit()
            except Exception as db_e:
                logger.error(f"Error desactivando suscripción en BD: {db_e}")

    return success


async def send_webpush_to_user(
    user_id: Optional[int],
    payload: Dict[str, Any],
    db: Session
) -> int:
    """
    Envía la notificación Push a todos los dispositivos registrados activos del usuario.
    Si user_id es None, se envía a todos los asesores/administradores registrados.
    Retorna el número de notificaciones enviadas con éxito.
    """
    query = db.query(PushSubscription).filter(PushSubscription.is_active == True)
    if user_id is not None:
        query = query.filter(PushSubscription.user_id == user_id)

    subscriptions: List[PushSubscription] = query.all()
    if not subscriptions:
        logger.info(f"No hay dispositivos registrados en Push para user_id={user_id}")
        return 0

    logger.info(f"Despachando WebPush a {len(subscriptions)} dispositivo(s) (user_id={user_id})...")
    
    tasks = [
        send_webpush_to_subscription(sub, payload, db)
        for sub in subscriptions
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    success_count = sum(1 for r in results if r is True)
    return success_count


async def send_webpush_to_all(
    payload: Dict[str, Any],
    db: Session
) -> int:
    """Envía notificación Push a todos los dispositivos registrados en el sistema."""
    return await send_webpush_to_user(user_id=None, payload=payload, db=db)


async def send_push_for_incoming_message(
    contact: Contact,
    message: Message,
    db: Session
) -> int:
    """
    Despacha la notificación Push nativa cuando un contacto envía un mensaje de WhatsApp u otro canal.
    Envía al asesor asignado Y a todos los administradores activos para garantizar supervisión en tiempo real.
    """
    sender_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
    if not sender_name or sender_name == "WhatsApp Contact":
        sender_name = contact.phone or "Nuevo Prospecto"

    body_preview = message.content or "Ha enviado un nuevo mensaje a ANCLA CRM"
    if len(body_preview) > 120:
        body_preview = body_preview[:117] + "..."

    push_payload = {
        "title": f"💬 {sender_name}",
        "body": body_preview,
        "icon": "/ancla_app_icon_192.png",
        "badge": "/notification-badge.png",
        "tag": f"msg_{contact.id}",
        "data": {
            "url": f"/?tab=chats&contact_id={contact.id}",
            "contact_id": contact.id,
            "message_id": message.id,
            "phone": contact.phone,
            "timestamp": message.created_at.isoformat() if message.created_at else None
        }
    }

    # 1. Obtener IDs de destinatarios: Asesor Asignado + Administradores
    target_user_ids = set()
    if contact.assigned_user_id:
        target_user_ids.add(contact.assigned_user_id)

    # Añadir administradores
    admins = db.query(User).filter(User.is_active == True).all()
    for admin in admins:
        role_str = str(getattr(admin.role, "value", admin.role)).lower()
        if "admin" in role_str:
            target_user_ids.add(admin.id)

    # 2. Despachar a los destinatarios objetivo
    total_delivered = 0
    if target_user_ids:
        for u_id in target_user_ids:
            delivered = await send_webpush_to_user(user_id=u_id, payload=push_payload, db=db)
            total_delivered += delivered

    # 3. Si nadie recibió (sin dispositivos en esos usuarios), difundir a todos los dispositivos registrados
    if total_delivered == 0:
        total_delivered = await send_webpush_to_all(payload=push_payload, db=db)

    return total_delivered

