from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.base import User, Contact, Message
from app.schemas.ai import AICopilotRequest, AICopilotResponse, AICopyRequest, AICopyResponse
from app.core.deps import get_current_user
from app.services.ai_engine import ai_engine

router = APIRouter(prefix="/ai", tags=["ai"])

@router.post("/suggest-reply", response_model=AICopilotResponse)
async def suggest_reply(
    payload: AICopilotRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Endpoint del Copiloto de IA: Sugiere una respuesta para que el asesor la use en el chat.
    """
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Control de acceso
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver este chat."
        )

    # Recuperar el historial de mensajes
    messages = db.query(Message)\
        .filter(Message.contact_id == contact.id)\
        .order_by(Message.created_at)\
        .all()

    # Formatear el historial para el motor de IA
    history = []
    for msg in messages:
        history.append({
            "sender_type": msg.sender_type,
            "content": msg.content
        })

    suggestion = await ai_engine.generate_copilot_suggestion(history)
    return {"suggestion": suggestion}


@router.post("/generate-copy", response_model=AICopyResponse)
async def generate_copy(
    payload: AICopyRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Laboratorio Creativo: Genera copys persuasivos de anuncios publicitarios para Meta Ads.
    """
    copy_result = await ai_engine.generate_ad_copy(
        product_description=payload.description,
        tone=payload.tone
    )
    return copy_result
