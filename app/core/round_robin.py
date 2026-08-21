from datetime import datetime
from sqlalchemy.orm import Session
from app.models.base import User, UserRole, Contact

def get_next_asesor_for_assignment(db: Session) -> User:
    """
    Retorna el siguiente asesor disponible bajo un algoritmo de Round Robin Inteligente.
    Filtra por disponibilidad horaria en base a su tabla de Availability,
    y penaliza/evita asesores saturados (con más de 15 chats comerciales activos).
    """
    from app.models.base import Availability, PipelineStage
    import datetime
    
    # 1. Obtener ID del stage "Ganado / Cerrado" para no contar leads ya cerrados
    stage_ganado = db.query(PipelineStage).filter(PipelineStage.name == "Ganado / Cerrado").first()
    ganado_id = stage_ganado.id if stage_ganado else 5

    # 2. Buscar todos los asesores activos
    asesores = db.query(User).filter(
        User.role == UserRole.ASESOR,
        User.is_active == True
    ).all()
    
    if not asesores:
        # Administradores de respaldo
        asesores = db.query(User).filter(
            User.role == UserRole.ADMIN,
            User.is_active == True
        ).all()
        
    if not asesores:
        return None

    # Día y hora local para la validación horaria de Colombia
    local_now = datetime.datetime.now()
    day_of_week = local_now.weekday() # 0-6
    time_now = local_now.time()

    asesor_scores = []
    for user in asesores:
        # A. Carga de chats activos (leads que no están en fase Ganado / Cerrado)
        active_chats = db.query(Contact).filter(
            Contact.assigned_user_id == user.id,
            Contact.pipeline_stage_id != ganado_id
        ).count()
        
        # B. Comprobar disponibilidad horaria
        is_available = True
        avail = db.query(Availability).filter(
            Availability.user_id == user.id,
            Availability.day_of_week == day_of_week
        ).first()
        if avail:
            if not (avail.start_time <= time_now <= avail.end_time):
                is_available = False
        else:
            # Fallback a horario comercial clásico (8 AM a 6 PM)
            from datetime import time
            if not (time(8, 0, 0) <= time_now <= time(18, 0, 0)):
                is_available = False

        asesor_scores.append({
            "user": user,
            "is_available": is_available,
            "active_chats": active_chats,
            "last_assigned": user.last_assigned_at or datetime.datetime.min
        })

    # C. Criterio de ordenación multi-factor
    def sorting_key(item):
        available_val = 0 if item["is_available"] else 1
        saturation_val = 0 if item["active_chats"] < 15 else 1
        chats_val = item["active_chats"]
        last_assigned_val = item["last_assigned"]
        
        return (available_val, saturation_val, chats_val, last_assigned_val)

    best_item = min(asesor_scores, key=sorting_key)
    return best_item["user"]

def assign_lead_round_robin(db: Session, contact: Contact) -> Contact:
    """
    Asigna un lead (Contact) por defecto a la bandeja principal de Administración / Liliana León.
    Solo un Administrador o Liliana pueden delegar manualmente a un asesor comercial.
    """
    admin_user = db.query(User).filter(
        User.role == UserRole.ADMIN,
        (User.email.ilike("%liliana%") | User.full_name.ilike("%liliana%") | User.email.ilike("%diarmale%"))
    ).order_by(User.id.asc()).first()
    
    if not admin_user:
        admin_user = db.query(User).filter(User.role == UserRole.ADMIN).order_by(User.id.asc()).first()
        
    if admin_user:
        contact.assigned_user_id = admin_user.id
        admin_user.last_assigned_at = datetime.utcnow()
        db.add(contact)
        db.add(admin_user)
        db.commit()
        db.refresh(contact)
    return contact
