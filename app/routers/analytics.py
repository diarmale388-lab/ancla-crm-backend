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
    # Una sola consulta agregada (GROUP BY) en lugar de un COUNT() por etapa (N+1).
    stages = db.query(PipelineStage).order_by(PipelineStage.position).all()
    contacts_per_stage = dict(
        db.query(Contact.pipeline_stage_id, func.count(Contact.id))
        .group_by(Contact.pipeline_stage_id)
        .all()
    )
    funnel_data = [
        {
            "stage_id": s.id,
            "stage_name": s.name,
            "count": contacts_per_stage.get(s.id, 0)
        }
        for s in stages
    ]

    # 2. Resumen de Citas (agregado por status en una sola consulta)
    appointments_by_status = dict(
        db.query(Appointment.status, func.count(Appointment.id))
        .group_by(Appointment.status)
        .all()
    )
    total_appointments = sum(appointments_by_status.values())
    active_appointments = appointments_by_status.get("CONFIRMED", 0)
    cancelled_appointments = appointments_by_status.get("CANCELLED", 0)

    # 3. Resumen de Mensajes (Eficacia IA) — agregado por sender_type en una sola consulta
    messages_by_sender_type = dict(
        db.query(Message.sender_type, func.count(Message.id))
        .group_by(Message.sender_type)
        .all()
    )
    msg_ai_count = messages_by_sender_type.get(SenderType.AI, 0)
    msg_human_count = messages_by_sender_type.get(SenderType.USER, 0)
    msg_contact_count = messages_by_sender_type.get(SenderType.CONTACT, 0)

    total_msgs = sum(messages_by_sender_type.values())
    ai_ratio = round((msg_ai_count / (msg_ai_count + msg_human_count) * 100), 1) if (msg_ai_count + msg_human_count) > 0 else 0.0

    # 4. Desempeño por Asesor
    # 3 consultas GROUP BY (una por métrica) en lugar de 3 COUNT() por asesor (1 + 3N).
    advisors = db.query(User).filter(User.is_active == True).all()

    leads_by_advisor = dict(
        db.query(Contact.assigned_user_id, func.count(Contact.id))
        .filter(Contact.assigned_user_id.isnot(None))
        .group_by(Contact.assigned_user_id)
        .all()
    )
    messages_by_advisor = dict(
        db.query(Message.sender_id, func.count(Message.id))
        .filter(Message.sender_type == SenderType.USER, Message.sender_id.isnot(None))
        .group_by(Message.sender_id)
        .all()
    )
    appointments_by_advisor = dict(
        db.query(Appointment.user_id, func.count(Appointment.id))
        .group_by(Appointment.user_id)
        .all()
    )

    advisor_performance = [
        {
            "advisor_id": adv.id,
            "full_name": adv.full_name,
            "role": adv.role,
            "assigned_leads": leads_by_advisor.get(adv.id, 0),
            "sent_messages": messages_by_advisor.get(adv.id, 0),
            "booked_appointments": appointments_by_advisor.get(adv.id, 0)
        }
        for adv in advisors
    ]

    return {
        "funnel": funnel_data,
        "kpis": {
            "total_leads": db.query(func.count(Contact.id)).scalar(),
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
