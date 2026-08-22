from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.base import User, Contact, Message, AIKnowledgeApproval, UserRole
from app.schemas.ai import (
    AICopilotRequest, 
    AICopilotResponse, 
    AICopyRequest, 
    AICopyResponse,
    AIApprovalCreate,
    AIApprovalUpdate,
    AIApprovalResponse
)
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
    if current_user.role not in [UserRole.ADMIN, "admin", "ADMIN"] and contact.assigned_user_id != current_user.id:
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


# =========================================================================
# BANDEJA DE APROBACIÓN DE DIRECTRICES OFICIALES (CANDADOS 1 Y 2 SOFI AI)
# =========================================================================

def _verify_admin_access(user: User):
    if user.role not in [UserRole.ADMIN, "admin", "ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: Solo administradores pueden gestionar la Bandeja de Aprobación de Sofi AI."
        )

@router.get("/approvals", response_model=List[AIApprovalResponse])
def get_ai_approvals(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lista las directrices de conocimiento de Sofi AI (Pendientes, Aprobadas, Rechazadas).
    Restringido estrictamente a Administradores (Diego / Liliana).
    """
    _verify_admin_access(current_user)
    
    query = db.query(AIKnowledgeApproval)
    if status_filter:
        query = query.filter(AIKnowledgeApproval.status == status_filter.upper())
    return query.order_by(AIKnowledgeApproval.created_at.desc()).all()


@router.post("/approvals", response_model=AIApprovalResponse, status_code=status.HTTP_201_CREATED)
def create_ai_approval(
    payload: AIApprovalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Crea una nueva propuesta de directriz (desde León Investiga o creada manualmente por el Admin).
    """
    _verify_admin_access(current_user)

    item = AIKnowledgeApproval(
        topic=payload.topic.strip(),
        detected_question=payload.detected_question.strip(),
        official_answer=payload.official_answer.strip(),
        source=payload.source or "LEON_INVESTIGA",
        status="PENDING"
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/approvals/{item_id}/approve", response_model=AIApprovalResponse)
def approve_ai_knowledge_item(
    item_id: int,
    payload: Optional[AIApprovalUpdate] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Aprueba una directriz con 1 clic para que Sofi AI la use de inmediato en sus conversaciones oficiales.
    """
    _verify_admin_access(current_user)

    item = db.query(AIKnowledgeApproval).filter(AIKnowledgeApproval.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Directriz no encontrada")

    if payload:
        if payload.topic:
            item.topic = payload.topic.strip()
        if payload.detected_question:
            item.detected_question = payload.detected_question.strip()
        if payload.official_answer:
            item.official_answer = payload.official_answer.strip()

    item.status = "APPROVED"
    item.approved_by_user_id = current_user.id
    db.commit()
    db.refresh(item)
    return item


@router.put("/approvals/{item_id}/reject", response_model=AIApprovalResponse)
def reject_ai_knowledge_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Rechaza o descarta una directriz para que Sofi AI NUNCA la use.
    """
    _verify_admin_access(current_user)

    item = db.query(AIKnowledgeApproval).filter(AIKnowledgeApproval.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Directriz no encontrada")

    item.status = "REJECTED"
    db.commit()
    db.refresh(item)
    return item


@router.delete("/approvals/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_knowledge_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Elimina permanentemente una directriz.
    """
    _verify_admin_access(current_user)

    item = db.query(AIKnowledgeApproval).filter(AIKnowledgeApproval.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Directriz no encontrada")

    db.delete(item)
    db.commit()
    return None

