from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Any
from app.database import get_db
from app.models.base import User, PipelineStage, Contact, Message
from app.schemas.pipeline import PipelineStageResponse, LeadPipelineResponse, LeadStageUpdate
from app.core.deps import get_current_user

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

def ensure_default_stages(db: Session) -> List[PipelineStage]:
    """
    Verifica si existen etapas en la base de datos y, si no o si hay inconsistencias/duplicaciones,
    limpia y recrea las 5 columnas por defecto para el pipeline de ventas de forma blindada.
    """
    stages = db.query(PipelineStage).order_by(PipelineStage.position).all()
    
    default_names = [
        "Nuevo Lead",
        "Contacto Iniciado",
        "Llamada Agendada",
        "Propuesta Enviada",
        "Ganado / Cerrado"
    ]
    
    # Validar si el número de etapas no es 5 o si hay nombres duplicados
    stage_names = [s.name for s in stages]
    has_duplicates = len(stage_names) != len(set(stage_names))
    
    if len(stages) != 5 or has_duplicates or any(name not in default_names for name in stage_names):
        # 1. Resetear el stage_id de los contactos temporalmente para evitar errores de llave foránea
        db.query(Contact).update({Contact.pipeline_stage_id: None})
        # 2. Eliminar todas las etapas existentes
        db.query(PipelineStage).delete()
        db.commit()
        
        # 3. Crear las 5 etapas limpias
        stages = []
        for i, name in enumerate(default_names):
            stage = PipelineStage(name=name, position=i)
            db.add(stage)
            stages.append(stage)
        db.commit()
        
        # Refrescar para obtener los nuevos IDs
        for s in stages:
            db.refresh(s)
            
    return stages


@router.get("/stages", response_model=List[PipelineStageResponse])
def get_pipeline_stages(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Recupera todas las columnas (etapas) del pipeline Kanban.
    Las inicializa con valores por defecto si la base de datos está vacía.
    """
    return ensure_default_stages(db)


@router.get("/leads", response_model=List[LeadPipelineResponse])
def get_pipeline_leads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Lista todos los contactos (leads) pertenecientes al pipeline del asesor logueado.
    Si algún contacto no tiene etapa asignada, se le asocia la primera columna por defecto.
    """
    stages = ensure_default_stages(db)
    first_stage_id = stages[0].id

    # Filtrar según rol
    query = db.query(Contact)
    if current_user.role != "admin":
        query = query.filter(Contact.assigned_user_id == current_user.id)
        
    contacts = query.all()
    
    # Asegurar que todos tengan un stage_id válido
    updated = False
    for contact in contacts:
        if contact.pipeline_stage_id is None:
            contact.pipeline_stage_id = first_stage_id
            db.add(contact)
            updated = True
            
    if updated:
        db.commit()
        # Refrescar datos
        contacts = query.all()
        
    results = []
    for contact in contacts:
        last_msg = db.query(Message)\
            .filter(Message.contact_id == contact.id)\
            .order_by(desc(Message.created_at))\
            .first()
            
        results.append({
            "id": contact.id,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "phone": contact.phone,
            "source": contact.source,
            "pipeline_stage_id": contact.pipeline_stage_id,
            "assigned_user_id": contact.assigned_user_id,
            "chatbot_enabled": contact.chatbot_enabled,
            "last_message_content": last_msg.content if last_msg else None,
            "last_message_time": last_msg.created_at if last_msg else None
        })
        
    return results


from fastapi import BackgroundTasks
from app.services.activity import record_activity
from app.services.automation import execute_stage_change_triggers

@router.patch("/leads/{contact_id}/stage", response_model=LeadPipelineResponse)
def update_lead_pipeline_stage(
    contact_id: int,
    payload: LeadStageUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Actualiza la etapa de pipeline de un contacto al arrastrarlo en el Kanban.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Control de acceso
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar este contacto."
        )

    # Verificar que el stage exista
    stage = db.query(PipelineStage).filter(PipelineStage.id == payload.pipeline_stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Etapa del pipeline no encontrada")

    old_stage_id = contact.pipeline_stage_id
    
    # --- MÁQUINA DE ESTADOS RÍGIDA Y VALIDACIONES DEL KANBAN ---
    
    # 0. Validación de Habeas Data
    if contact.habeas_data_authorized is False:
        if stage.name in ["Contacto Iniciado", "Llamada Agendada", "Propuesta Enviada", "Ganado / Cerrado"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tratamiento bloqueado: El cliente ha rechazado o revocado el consentimiento de datos (Habeas Data)."
            )
            
    # 1. Regla para "Llamada Agendada"
    if stage.name == "Llamada Agendada":
        from app.models.base import Appointment
        # Verificar si tiene alguna cita registrada en el sistema para este lead
        has_appointment = db.query(Appointment).filter(Appointment.contact_id == contact.id).first()
        if not has_appointment:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transición inválida: No puedes mover el lead a 'Llamada Agendada' sin registrar previamente una cita en el calendario comercial."
            )
            
    # 2. Regla para "Propuesta Enviada"
    elif stage.name == "Propuesta Enviada":
        if not contact.email or "@" not in contact.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transición inválida: Se requiere registrar un correo electrónico válido en la ficha del lead antes de avanzar a 'Propuesta Enviada'."
            )
            
    # 3. Regla para "Ganado / Cerrado"
    elif stage.name == "Ganado / Cerrado":
        if not contact.email or "@" not in contact.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transición inválida: Se requiere registrar un correo electrónico válido en la ficha del lead antes de cerrar la venta como 'Ganado'."
            )
            
        # Validar que exista al menos una propuesta generada previamente para este contacto
        from app.models.base import LeadActivityLog
        has_proposal_log = db.query(LeadActivityLog).filter(
            LeadActivityLog.contact_id == contact.id,
            LeadActivityLog.activity_type == "proposal_generated"
        ).first()
        if not has_proposal_log:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transición inválida: No puedes mover el lead a 'Ganado / Cerrado' sin haber generado previamente una propuesta comercial personalizada en PDF."
            )
            
    # --- FIN DE VALIDACIONES ---

    contact.pipeline_stage_id = payload.pipeline_stage_id
    db.add(contact)
    db.commit()
    db.refresh(contact)
    
    # 1. Registrar actividad del historial
    old_stage = db.query(PipelineStage).filter(PipelineStage.id == old_stage_id).first() if old_stage_id else None
    old_stage_name = old_stage.name if old_stage else "Sin Etapa"
    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="stage_change",
        description=f"Cambió de etapa: '{old_stage_name}' ➔ '{stage.name}'",
        user_id=current_user.id
    )

    # 2. Ejecutar triggers de cambio de etapa de forma asíncrona
    background_tasks.add_task(execute_stage_change_triggers, db, contact, payload.pipeline_stage_id, current_user.id)
    
    last_msg = db.query(Message)\
        .filter(Message.contact_id == contact.id)\
        .order_by(desc(Message.created_at))\
        .first()
        
    return {
        "id": contact.id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "phone": contact.phone,
        "source": contact.source,
        "pipeline_stage_id": contact.pipeline_stage_id,
        "assigned_user_id": contact.assigned_user_id,
        "chatbot_enabled": contact.chatbot_enabled,
        "last_message_content": last_msg.content if last_msg else None,
        "last_message_time": last_msg.created_at if last_msg else None
    }
