from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Any
from app.database import get_db
from app.models.base import User, Contact, PipelineStage, Appointment, Message, SenderType, UserRole
from app.core.deps import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/summary")
def get_analytics_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Obtiene las métricas agregadas del CRM (solo para administradores).
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: Se requieren permisos de administrador."
        )

    # 1. Pipeline Funnel (Etapas del embudo)
    stages = db.query(PipelineStage).order_by(PipelineStage.position).all()
    funnel_data = []
    for s in stages:
        count = db.query(Contact).filter(Contact.pipeline_stage_id == s.id).count()
        funnel_data.append({
            "stage_id": s.id,
            "stage_name": s.name,
            "count": count
        })

    # 2. Resumen de Citas
    total_appointments = db.query(Appointment).count()
    active_appointments = db.query(Appointment).filter(Appointment.status == "CONFIRMED").count()
    cancelled_appointments = db.query(Appointment).filter(Appointment.status == "CANCELLED").count()

    # 3. Resumen de Mensajes (Eficacia IA)
    msg_ai_count = db.query(Message).filter(Message.sender_type == SenderType.AI).count()
    msg_human_count = db.query(Message).filter(Message.sender_type == SenderType.USER).count()
    msg_contact_count = db.query(Message).filter(Message.sender_type == SenderType.CONTACT).count()

    total_msgs = msg_ai_count + msg_human_count + msg_contact_count
    ai_ratio = round((msg_ai_count / (msg_ai_count + msg_human_count) * 100), 1) if (msg_ai_count + msg_human_count) > 0 else 0.0

    # 4. Desempeño por Asesor
    advisors = db.query(User).filter(User.is_active == True).all()
    advisor_performance = []
    for adv in advisors:
        assigned_leads = db.query(Contact).filter(Contact.assigned_user_id == adv.id).count()
        sent_messages = db.query(Message).filter(Message.sender_type == SenderType.USER, Message.sender_id == adv.id).count()
        booked_appointments = db.query(Appointment).filter(Appointment.user_id == adv.id).count()
        
        advisor_performance.append({
            "advisor_id": adv.id,
            "full_name": adv.full_name,
            "role": adv.role,
            "assigned_leads": assigned_leads,
            "sent_messages": sent_messages,
            "booked_appointments": booked_appointments
        })

    return {
        "funnel": funnel_data,
        "kpis": {
            "total_leads": db.query(Contact).count(),
            "active_appointments": active_appointments,
            "cancelled_appointments": cancelled_appointments,
            "total_appointments": total_appointments,
            "messages": {
                "total": total_msgs,
                "ai": msg_ai_count,
                "human": msg_human_count,
                "contact": msg_contact_count,
                "ai_ratio_pct": ai_ratio
            }
        },
        "advisor_performance": advisor_performance
    }
