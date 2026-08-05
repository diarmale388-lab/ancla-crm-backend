import logging
from datetime import datetime, timedelta, time
from typing import List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.base import User, Contact, Availability, Appointment, PipelineStage
from app.schemas.appointment import AppointmentBook, AppointmentResponse, SlotResponse
from app.core.deps import get_current_user
from app.core.socket_manager import manager

logger = logging.getLogger("appointments_router")

router = APIRouter(prefix="/appointments", tags=["appointments"])

def ensure_default_availability(db: Session, user_id: int):
    """
    Si el asesor no tiene horario de disponibilidad definido,
    crea un horario estándar por defecto de Lunes a Viernes de 9am a 5pm.
    """
    availabilities = db.query(Availability).filter(Availability.user_id == user_id).all()
    if not availabilities:
        # Lunes a Viernes (0 a 4)
        for day in range(5):
            av = Availability(
                user_id=user_id,
                day_of_week=day,
                start_time=time(9, 0, 0),
                end_time=time(17, 0, 0)
            )
            db.add(av)
        db.commit()
        availabilities = db.query(Availability).filter(Availability.user_id == user_id).all()
    return availabilities


@router.get("/slots", response_model=List[SlotResponse])
def get_available_slots(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Calcula los horarios disponibles del asesor asignado al lead para los próximos 7 días,
    cruzando su horario laboral con citas ya agendadas.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Si no tiene asesor asignado, usar el asesor logueado por defecto
    user_id = contact.assigned_user_id or current_user.id
    
    # Asegurar disponibilidad por defecto
    availabilities = ensure_default_availability(db, user_id)
    avail_by_day = {av.day_of_week: av for av in availabilities}

    # Obtener citas existentes de los próximos 7 días para ese asesor
    today = datetime.utcnow().date()
    end_date = today + timedelta(days=7)
    
    appointments = db.query(Appointment).filter(
        Appointment.user_id == user_id,
        Appointment.status == "CONFIRMED",
        Appointment.datetime >= datetime.combine(today, time.min),
        Appointment.datetime <= datetime.combine(end_date, time.max)
    ).all()
    
    reserved_times = {app.datetime for app in appointments}

    # Generar slots según tipo de cita (PRESENCIAL vs VIRTUAL/LLAMADA) y día de la semana
    slots = []
    current_time = datetime.utcnow()

    is_presencial = contact.source and any(w in contact.source.lower() for w in ["showroom", "local", "armenia", "presencial"])

    for i in range(1, 8):  # Próximos 7 días
        day_date = today + timedelta(days=i)
        day_of_week = day_date.weekday()  # 0 = Lunes, 5 = Sábado, 6 = Domingo

        if day_of_week == 6:
            continue  # Domingo no laborable

        if is_presencial:
            # 🟢 PRESENCIAL (Showroom Armenia): 9:30 AM - 12:00 PM y 2:00 PM - 4:00 PM (Máx 2 personas/citas por hora)
            morning_start = time(9, 30, 0)
            morning_end = time(12, 0, 0)
            afternoon_start = time(14, 0, 0) if day_of_week < 5 else None
            afternoon_end = time(16, 0, 0) if day_of_week < 5 else None
            interval_min = 30
            max_capacity_per_slot = 2
        else:
            # 💻 VIRTUAL / LLAMADA: L-V (10:00 AM - 12:00 PM y 2:00 PM - 4:30 PM), Sábados (10:00 AM - 12:00 PM únicamente)
            morning_start = time(10, 0, 0)
            morning_end = time(12, 0, 0)
            afternoon_start = time(14, 0, 0) if day_of_week < 5 else None
            afternoon_end = time(16, 30, 0) if day_of_week < 5 else None
            interval_min = 30
            max_capacity_per_slot = 1

        temp_dt = datetime.combine(day_date, morning_start)
        day_end_dt = datetime.combine(day_date, afternoon_end if afternoon_end else morning_end)

        while temp_dt <= day_end_dt:
            slot_time = temp_dt.time()
            is_in_morning = (morning_start <= slot_time <= morning_end)
            is_in_afternoon = (afternoon_start and afternoon_end and afternoon_start <= slot_time <= afternoon_end)

            if is_in_morning or is_in_afternoon:
                # Contar citas existentes en ese mismo slot
                slot_count = sum(1 for app in appointments if app.datetime == temp_dt)

                if slot_count < max_capacity_per_slot and temp_dt > current_time:
                    formatted_time = temp_dt.strftime("%A %d de %B, %I:%M %p")
                    day_translations = {
                        "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
                        "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
                        "January": "Enero", "February": "Febrero", "March": "Marzo", "April": "Abril",
                        "May": "Mayo", "June": "Junio", "July": "Julio", "August": "Agosto",
                        "September": "Septiembre", "October": "Octubre", "November": "Noviembre", "December": "Diciembre"
                    }
                    for en, es in day_translations.items():
                        formatted_time = formatted_time.replace(en, es)

                    slots.append(SlotResponse(
                        datetime=temp_dt,
                        formatted_time=formatted_time
                    ))

            temp_dt += timedelta(minutes=interval_min)
                
    return slots


@router.post("/book", response_model=AppointmentResponse)
async def book_appointment(
    payload: AppointmentBook,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Reserva formalmente una cita para un contacto y lo mueve automáticamente
    en el pipeline a la etapa 'Llamada Agendada'.
    """
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    user_id = contact.assigned_user_id or current_user.id

    # 1. Validar si el slot ya está ocupado
    existing = db.query(Appointment).filter(
        Appointment.user_id == user_id,
        Appointment.datetime == payload.datetime,
        Appointment.status == "CONFIRMED"
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Este horario ya está reservado.")

    # 2. Registrar cita
    db_appointment = Appointment(
        contact_id=payload.contact_id,
        user_id=user_id,
        datetime=payload.datetime,
        status="CONFIRMED",
        notes=payload.notes
    )
    db.add(db_appointment)

    # 3. Mover automáticamente a 'Llamada Agendada' en el pipeline
    stages = db.query(PipelineStage).all()
    stage_by_name = {s.name: s.id for s in stages}
    llamada_agendada_id = stage_by_name.get("Llamada Agendada")
    if llamada_agendada_id:
        contact.pipeline_stage_id = llamada_agendada_id
        db.add(contact)

    db.commit()
    db.refresh(db_appointment)

    # Registrar actividad
    from app.services.activity import record_activity
    formatted_dt = db_appointment.datetime.strftime("%Y-%m-%d %I:%M %p")
    note_details = f" con notas: '{db_appointment.notes}'" if db_appointment.notes else ""
    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="appointment_booked",
        description=f"Cita agendada para el {formatted_dt}{note_details}.",
        user_id=current_user.id
    )

    # Sincronización con Google Calendar y Google Drive
    from app.services.google_integration import create_google_calendar_event, upload_lead_report_to_google_drive
    try:
        await create_google_calendar_event(db, db_appointment, contact)
        await upload_lead_report_to_google_drive(db, contact, db_appointment)
    except Exception as e:
        logger.error(f"Error sincronizando con Google: {e}")

    # 4. Transmitir el agendamiento y cambio de fase por WebSocket
    ws_payload = {
        "event": "appointment_created",
        "data": {
            "id": db_appointment.id,
            "contact_id": contact.id,
            "user_id": user_id,
            "datetime": db_appointment.datetime.isoformat(),
            "contact_name": f"{contact.first_name or ''} {contact.last_name or ''}".strip() or contact.phone,
            "pipeline_stage_id": contact.pipeline_stage_id
        }
    }
    await manager.broadcast(ws_payload)

    return db_appointment


@router.get("/list", response_model=List[AppointmentResponse])
def list_appointments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Obtiene todas las citas de la agenda para el panel visual del Calendario.
    """
    query = db.query(Appointment).filter(Appointment.status == "CONFIRMED")
    if current_user.role != "admin":
        query = query.filter(Appointment.user_id == current_user.id)
        
    return query.order_by(Appointment.datetime).all()


@router.get("/availability")
def get_user_availability(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Obtiene el horario de disponibilidad del asesor logueado agrupado por días y sus intervalos de tiempo.
    """
    availabilities = db.query(Availability).filter(Availability.user_id == current_user.id).order_by(Availability.day_of_week, Availability.start_time).all()
    if not availabilities:
        availabilities = ensure_default_availability(db, current_user.id)
        
    # Agrupar por día de la semana
    by_day = {}
    for av in availabilities:
        day = av.day_of_week
        if day not in by_day:
            by_day[day] = []
        by_day[day].append({
            "start_time": av.start_time.strftime("%H:%M"),
            "end_time": av.end_time.strftime("%H:%M")
        })
        
    # Formatear respuesta de 0 (Lunes) a 6 (Domingo)
    result = []
    for day in range(7):
        result.append({
            "day_of_week": day,
            "intervals": by_day.get(day, [])
        })
    return result


@router.post("/availability")
def update_user_availability(
    payload: Any,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Actualiza la disponibilidad de horarios del asesor admitiendo múltiples intervalos por día (jornada partida).
    """
    # 1. Borrar disponibilidades previas del usuario
    db.query(Availability).filter(Availability.user_id == current_user.id).delete()
    
    # 2. Insertar las nuevas disponibilidades por cada intervalo activo de cada día
    days_data = payload.get("days", [])
    for d in days_data:
        day_of_week = d.get("day_of_week")
        intervals = d.get("intervals", [])
        
        for interval in intervals:
            start_str = interval.get("start_time")
            end_str = interval.get("end_time")
            if not start_str or not end_str:
                continue
                
            sh, sm = map(int, start_str.split(":"))
            eh, em = map(int, end_str.split(":"))
            
            av = Availability(
                user_id=current_user.id,
                day_of_week=day_of_week,
                start_time=time(sh, sm, 0),
                end_time=time(eh, em, 0)
            )
            db.add(av)
        
    db.commit()
    return {"status": "success", "message": "Disponibilidad de horarios actualizada exitosamente"}


@router.delete("/{appointment_id}")
async def delete_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Elimina o cancela una cita comercial agendada por su ID.
    """
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    # Control de acceso
    if current_user.role != "admin" and appointment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para cancelar esta cita."
        )

    contact_id = appointment.contact_id
    formatted_dt = appointment.datetime.strftime("%Y-%m-%d %I:%M %p")
    db.delete(appointment)
    db.commit()

    # Registrar actividad
    from app.services.activity import record_activity
    record_activity(
        db=db,
        contact_id=contact_id,
        activity_type="appointment_cancelled",
        description=f"Cita del {formatted_dt} fue cancelada.",
        user_id=current_user.id
    )

    # Notificar por WebSocket el borrado de la cita
    ws_payload = {
        "event": "appointment_deleted",
        "data": {
            "appointment_id": appointment_id,
            "contact_id": contact_id
        }
    }
    await manager.broadcast(ws_payload)

    return {"status": "success", "message": "Cita cancelada exitosamente"}

