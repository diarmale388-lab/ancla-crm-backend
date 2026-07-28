from sqlalchemy.orm import Session
from typing import Optional
from app.models.base import LeadActivityLog

def record_activity(
    db: Session,
    contact_id: int,
    activity_type: str,
    description: str,
    user_id: Optional[int] = None
) -> LeadActivityLog:
    """
    Records a lead activity log in the database.
    activity_type can be: stage_change, appointment_booked, appointment_cancelled,
    message_sent, advisor_reassigned, chatbot_toggle, internal_note, broadcast_sent
    """
    log_entry = LeadActivityLog(
        contact_id=contact_id,
        user_id=user_id,
        activity_type=activity_type,
        description=description
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    return log_entry
