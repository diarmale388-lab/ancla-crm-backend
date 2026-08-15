import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.base import User, PushSubscription
from app.core.deps import get_current_user
from app.services.push_service import send_webpush_to_user

logger = logging.getLogger("notifications_router")

router = APIRouter(prefix="/notifications", tags=["notifications"])

class PushKeysSchema(BaseModel):
    p256dh: str
    auth: str

class PushSubscribeSchema(BaseModel):
    endpoint: str
    keys: PushKeysSchema
    user_agent: Optional[str] = None

class PushUnsubscribeSchema(BaseModel):
    endpoint: str

@router.get("/vapid-public-key")
def get_vapid_public_key():
    """
    Retorna la clave pública VAPID para que el cliente PWA pueda suscribirse con PushManager.
    """
    return {
        "status": "success",
        "public_key": settings.VAPID_PUBLIC_KEY
    }

@router.post("/subscribe")
def subscribe_push_device(
    data: PushSubscribeSchema,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Registra o actualiza la suscripción WebPush de un asesor/usuario en PostgreSQL.
    """
    endpoint = data.endpoint.strip()
    if not endpoint:
        raise HTTPException(status_code=400, detail="Endpoint de suscripción inválido.")

    user_agent = data.user_agent or request.headers.get("user-agent", "Unknown Device")[:500]

    # Verificar si el endpoint ya existe
    existing_sub = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    if existing_sub:
        existing_sub.user_id = current_user.id
        existing_sub.p256dh = data.keys.p256dh
        existing_sub.auth = data.keys.auth
        existing_sub.user_agent = user_agent
        existing_sub.is_active = True
        db.add(existing_sub)
        db.commit()
        db.refresh(existing_sub)
        logger.info(f"Suscripción Push actualizada para usuario #{current_user.id} ({current_user.full_name})")
        return {"status": "success", "message": "Dispositivo actualizado con éxito.", "subscription_id": existing_sub.id}
    else:
        new_sub = PushSubscription(
            user_id=current_user.id,
            endpoint=endpoint,
            p256dh=data.keys.p256dh,
            auth=data.keys.auth,
            user_agent=user_agent,
            is_active=True
        )
        db.add(new_sub)
        db.commit()
        db.refresh(new_sub)
        logger.info(f"Nueva suscripción Push registrada para usuario #{current_user.id} ({current_user.full_name})")
        return {"status": "success", "message": "Dispositivo registrado con éxito para notificaciones en segundo plano.", "subscription_id": new_sub.id}

@router.post("/unsubscribe")
def unsubscribe_push_device(
    data: PushUnsubscribeSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Desactiva la suscripción WebPush para este endpoint.
    """
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == data.endpoint).first()
    if sub:
        sub.is_active = False
        db.add(sub)
        db.commit()
        logger.info(f"Suscripción Push desactivada para usuario #{current_user.id}")
    return {"status": "success", "message": "Dispositivo desuscrito."}

@router.post("/test-push")
async def test_push_notification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Envía una notificación Push de prueba en vivo a todos los dispositivos registrados del usuario.
    """
    test_payload = {
        "title": "🔔 ANCLA CRM - Prueba de Notificación Push",
        "body": f"¡Hola {current_user.full_name}! Las notificaciones con pantalla bloqueada y en segundo plano están 100% activas y funcionando.",
        "icon": "/ancla_app_icon_192.png",
        "badge": "/notification-badge.png",
        "tag": "test_push_notification",
        "data": {
            "url": "/",
            "type": "test_notification"
        }
    }

    delivered_count = await send_webpush_to_user(
        user_id=current_user.id,
        payload=test_payload,
        db=db
    )

    if delivered_count == 0:
        return {
            "status": "warning",
            "message": "No se encontraron dispositivos activos registrados para tu usuario o el navegador denegó la entrega.",
            "delivered_count": 0
        }

    return {
        "status": "success",
        "message": f"¡Notificación Push de prueba enviada exitosamente a {delivered_count} dispositivo(s)!",
        "delivered_count": delivered_count
    }

@router.get("/status")
def get_user_push_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Devuelve la cantidad de dispositivos activos registrados para el usuario.
    """
    active_count = db.query(PushSubscription).filter(
        PushSubscription.user_id == current_user.id,
        PushSubscription.is_active == True
    ).count()

    return {
        "status": "success",
        "user_id": current_user.id,
        "active_devices_count": active_count
    }
