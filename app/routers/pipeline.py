from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc, text
from typing import List, Any, Optional
from pydantic import BaseModel
from app.database import get_db
from app.models.base import User, PipelineStage, Contact, Message
from app.schemas.pipeline import PipelineStageResponse, LeadPipelineResponse, LeadStageUpdate
from app.core.deps import get_current_user
from app.services.activity import record_activity
from app.services.automation import execute_stage_change_triggers

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

def ensure_default_stages(db: Session) -> List[PipelineStage]:
    """
    Recupera las 6 etapas comerciales por defecto de forma ultrarrápida.
    """
    stages = db.query(PipelineStage).order_by(PipelineStage.position).all()
    if not stages or len(stages) < 6:
        db.execute(text("UPDATE pipeline_stages SET name = 'Lead Nuevo', position = 0 WHERE name IN ('Nuevo Lead', 'Lead Nuevo');"))
        db.execute(text("UPDATE pipeline_stages SET name = 'Contacto Iniciado', position = 1 WHERE name = 'Contacto Iniciado';"))
        db.execute(text("UPDATE pipeline_stages SET name = 'Cita Agendada', position = 2 WHERE name IN ('Llamada Agendada', 'Cita Agendada');"))
        db.execute(text("UPDATE pipeline_stages SET name = 'Propuesta Enviada', position = 3 WHERE name = 'Propuesta Enviada';"))
        db.execute(text("UPDATE pipeline_stages SET name = 'Ganado', position = 4 WHERE name IN ('Ganado / Cerrado', 'Ganado');"))
        
        cold = db.execute(text("SELECT id FROM pipeline_stages WHERE name = 'Lead Frío';")).fetchone()
        if not cold:
            max_id = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM pipeline_stages;")).scalar()
            db.execute(text("INSERT INTO pipeline_stages (id, name, position, created_at) VALUES (:id, 'Lead Frío', 5, NOW());"), {"id": max_id + 1})
            db.execute(text("SELECT setval('pipeline_stages_id_seq', (SELECT MAX(id) FROM pipeline_stages));"))
        db.commit()
        stages = db.query(PipelineStage).order_by(PipelineStage.position).all()
    return stages


@router.get("/stages", response_model=List[PipelineStageResponse])
def get_pipeline_stages(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    return ensure_default_stages(db)


@router.get("/leads", response_model=List[LeadPipelineResponse])
def get_pipeline_leads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Lista todos los contactos (leads) pertenecientes al pipeline.
    """
    stages = ensure_default_stages(db)
    stages_map = {s.name: s.id for s in stages}

    stage_nuevo = stages_map.get("Lead Nuevo", stages[0].id)
    stage_contacto = stages_map.get("Contacto Iniciado", stages[1].id if len(stages) > 1 else stages[0].id)
    stage_cita = stages_map.get("Cita Agendada", stages[2].id if len(stages) > 2 else stages[0].id)
    stage_propuesta = stages_map.get("Propuesta Enviada", stages[3].id if len(stages) > 3 else stages[0].id)

    first_stage_id = stage_nuevo

    # Cargar citas y mensajes en memoria en 1 sola consulta veloz (<0.01s)
    appt_contacts = set(row[0] for row in db.execute(text("SELECT DISTINCT contact_id FROM appointments;")).fetchall())

    query = db.query(Contact)
    role_str = str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role).lower()
    if role_str not in ["admin", "userrole.admin"]:
        query = query.filter(Contact.assigned_user_id == current_user.id)
        
    contacts = query.all()
    
    last_messages_raw = db.execute(text("""
        SELECT DISTINCT ON (contact_id) contact_id, content, created_at
        FROM messages
        ORDER BY contact_id, created_at DESC
    """)).fetchall()
    last_msg_map = {row[0]: {"content": row[1], "created_at": row[2]} for row in last_messages_raw}

    users_raw = db.query(User).all()
    user_map = {u.id: u.full_name for u in users_raw}
        
    results = []
    for contact in contacts:
        lmsg = last_msg_map.get(contact.id)
        stage_id = contact.pipeline_stage_id
        if not stage_id or stage_id == first_stage_id:
            if contact.id in appt_contacts:
                stage_id = stage_cita
            elif lmsg:
                stage_id = stage_contacto
            else:
                stage_id = stage_nuevo

        results.append({
            "id": contact.id,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "phone": contact.phone,
            "email": contact.email,
            "source": contact.source,
            "pipeline_stage_id": stage_id,
            "assigned_user_id": contact.assigned_user_id,
            "assigned_user_name": user_map.get(contact.assigned_user_id, "Sin Asignar") if contact.assigned_user_id else "Sin Asignar",
            "interest_product": contact.interest_product or "Flex Home",
            "lot_status": contact.lot_status or "Por definir",
            "lot_city": contact.lot_city or None,
            "estimated_budget": contact.estimated_budget or 0.0,
            "chatbot_enabled": contact.chatbot_enabled,
            "last_message_content": lmsg["content"] if lmsg else None,
            "last_message_time": lmsg["created_at"] if lmsg else None,
            "created_at": contact.created_at,
            "updated_at": contact.updated_at
        })

    return results


class ContactDetailsUpdatePayload(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    interest_product: Optional[str] = None
    lot_status: Optional[str] = None
    lot_city: Optional[str] = None
    estimated_budget: Optional[float] = None
    assigned_user_id: Optional[int] = None


@router.patch("/leads/{contact_id}/details", response_model=LeadPipelineResponse)
def update_lead_details(
    contact_id: int,
    payload: ContactDetailsUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    role_str = str(getattr(current_user.role, "value", current_user.role)).lower()
    is_admin = role_str in ["admin", "userrole.admin"]

    # Validación de acceso al lead
    if not is_admin and contact.assigned_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Acceso denegado: No tienes autorización sobre este prospecto.")

    if payload.first_name is not None: contact.first_name = payload.first_name
    if payload.last_name is not None: contact.last_name = payload.last_name
    if payload.email is not None: contact.email = payload.email
    if payload.interest_product is not None: contact.interest_product = payload.interest_product
    if payload.lot_status is not None: contact.lot_status = payload.lot_status
    if payload.lot_city is not None: contact.lot_city = payload.lot_city
    if payload.estimated_budget is not None: contact.estimated_budget = payload.estimated_budget

    # Reasignación de asesor (Exclusivo Administrador)
    if payload.assigned_user_id is not None:
        if not is_admin:
            raise HTTPException(status_code=403, detail="Solo los administradores y Liliana León pueden asignar prospectos.")
        new_assigned_id = payload.assigned_user_id if payload.assigned_user_id > 0 else None
        contact.assigned_user_id = new_assigned_id

    db.add(contact)
    db.commit()
    db.refresh(contact)

    last_msg = db.query(Message)\
        .filter(Message.contact_id == contact.id)\
        .order_by(desc(Message.created_at))\
        .first()

    assigned_user_name = "Sin Asignar"
    if contact.assigned_user_id:
        u = db.query(User).filter(User.id == contact.assigned_user_id).first()
        if u:
            assigned_user_name = u.full_name

    return {
        "id": contact.id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "phone": contact.phone,
        "email": contact.email,
        "source": contact.source,
        "pipeline_stage_id": contact.pipeline_stage_id,
        "assigned_user_id": contact.assigned_user_id,
        "assigned_user_name": assigned_user_name,
        "interest_product": contact.interest_product or "Flex Home",
        "lot_status": contact.lot_status or "Por definir",
        "lot_city": contact.lot_city or None,
        "estimated_budget": contact.estimated_budget or 0.0,
        "chatbot_enabled": contact.chatbot_enabled,
        "last_message_content": last_msg.content if last_msg else None,
        "last_message_time": last_msg.created_at if last_msg else None,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at
    }


@router.patch("/leads/{contact_id}/stage", response_model=LeadPipelineResponse)
def update_lead_pipeline_stage(
    contact_id: int,
    payload: LeadStageUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar este contacto."
        )

    stage = db.query(PipelineStage).filter(PipelineStage.id == payload.pipeline_stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Etapa del pipeline no encontrada")

    old_stage_id = contact.pipeline_stage_id
    
    # --- VALIDACIONES DE NEGOCIO ---
    if contact.habeas_data_authorized is False:
        if stage.name in ["Contacto Iniciado", "Cita Agendada", "Llamada Agendada", "Propuesta Enviada", "Ganado", "Ganado / Cerrado"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tratamiento bloqueado: El cliente ha rechazado el consentimiento de datos (Habeas Data)."
            )
            
    if stage.name in ["Cita Agendada", "Llamada Agendada"]:
        from app.models.base import Appointment
        has_appointment = db.query(Appointment).filter(Appointment.contact_id == contact.id).first()
        if not has_appointment:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transición inválida: Se requiere registrar previamente una cita en el calendario antes de mover a Cita Agendada."
            )
            
    elif stage.name == "Propuesta Enviada":
        if not contact.email or "@" not in contact.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transición inválida: Se requiere registrar un correo electrónico válido antes de avanzar a Propuesta Enviada."
            )
            
    elif stage.name in ["Ganado", "Ganado / Cerrado"]:
        if not contact.email or "@" not in contact.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transición inválida: Se requiere un correo electrónico registrado para marcar como Ganado."
            )
            
    # --- FIN DE VALIDACIONES ---

    contact.pipeline_stage_id = payload.pipeline_stage_id
    db.add(contact)
    db.commit()
    db.refresh(contact)
    
    old_stage = db.query(PipelineStage).filter(PipelineStage.id == old_stage_id).first() if old_stage_id else None
    old_stage_name = old_stage.name if old_stage else "Sin Etapa"
    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="stage_change",
        description=f"Cambió de etapa: '{old_stage_name}' ➔ '{stage.name}'",
        user_id=current_user.id
    )

    background_tasks.add_task(execute_stage_change_triggers, db, contact, payload.pipeline_stage_id, current_user.id)
    
    last_msg = db.query(Message)\
        .filter(Message.contact_id == contact.id)\
        .order_by(desc(Message.created_at))\
        .first()

    assigned_user_name = "Sin Asignar"
    if contact.assigned_user_id:
        u = db.query(User).filter(User.id == contact.assigned_user_id).first()
        if u:
            assigned_user_name = u.full_name

    return {
        "id": contact.id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "phone": contact.phone,
        "email": contact.email,
        "source": contact.source,
        "pipeline_stage_id": contact.pipeline_stage_id,
        "assigned_user_id": contact.assigned_user_id,
        "assigned_user_name": assigned_user_name,
        "interest_product": contact.interest_product or "Flex Home",
        "lot_status": contact.lot_status or "Por definir",
        "lot_city": contact.lot_city or None,
        "estimated_budget": contact.estimated_budget or 0.0,
        "chatbot_enabled": contact.chatbot_enabled,
        "last_message_content": last_msg.content if last_msg else None,
        "last_message_time": last_msg.created_at if last_msg else None,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at
    }
