import logging
from datetime import datetime, timedelta, time
from typing import List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.base import User, Contact, Availability, Appointment, PipelineStage, UserRole
from app.schemas.appointment import AppointmentBook, AppointmentResponse, SlotResponse
from app.core.deps import get_current_user
from app.core.socket_manager import manager

logger = logging.getLogger("appointments_router")

router = APIRouter(prefix="/appointments", tags=["appointments"])

def ensure_default_availability(db: Session, user_id: int, modality: str = "VIRTUAL"):
    """
    Si el asesor no tiene horario de disponibilidad definido para la modalidad,
    crea un horario estándar por defecto.
    """
    availabilities = db.query(Availability).filter(
        Availability.user_id == user_id,
        Availability.modality == modality
    ).all()
    if not availabilities:
        if modality == "PRESENCIAL":
            # 🏢 Showroom Armenia: L-V (09:30-12:30 y 14:00-17:00), Sábados (09:30-13:00)
            for day in range(5):
                db.add(Availability(user_id=user_id, day_of_week=day, start_time=time(9, 30, 0), end_time=time(12, 30, 0), modality="PRESENCIAL"))
                db.add(Availability(user_id=user_id, day_of_week=day, start_time=time(14, 0, 0), end_time=time(17, 0, 0), modality="PRESENCIAL"))
            db.add(Availability(user_id=user_id, day_of_week=5, start_time=time(9, 30, 0), end_time=time(13, 0, 0), modality="PRESENCIAL"))
        else:
            # 💻 Virtual / Llamada: L-V (10:00-12:00 y 14:00-17:00), Sábados (10:00-12:00)
            for day in range(5):
                db.add(Availability(user_id=user_id, day_of_week=day, start_time=time(10, 0, 0), end_time=time(12, 0, 0), modality="VIRTUAL"))
                db.add(Availability(user_id=user_id, day_of_week=day, start_time=time(14, 0, 0), end_time=time(17, 0, 0), modality="VIRTUAL"))
            db.add(Availability(user_id=user_id, day_of_week=5, start_time=time(10, 0, 0), end_time=time(12, 0, 0), modality="VIRTUAL"))
        db.commit()
        availabilities = db.query(Availability).filter(Availability.user_id == user_id, Availability.modality == modality).all()
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
    today = (datetime.utcnow() - timedelta(hours=5)).date()
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
    colombia_now = datetime.utcnow() - timedelta(hours=5)
    current_time = colombia_now

    is_presencial = False
    if contact.scheduling_state:
        st = contact.scheduling_state.upper()
        is_presencial = "PRESENCIAL" in st or "SHOWROOM" in st or "VISITA" in st

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

    # 1. Validar si el contacto ya tiene cita confirmada en ese mismo día calendario (Evitar duplicados)
    dt_val = payload.datetime if isinstance(payload.datetime, datetime) else datetime.fromisoformat(str(payload.datetime).replace('Z', ''))
    start_of_day = dt_val.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = dt_val.replace(hour=23, minute=59, second=59, microsecond=999999)

    same_day_existing = db.query(Appointment).filter(
        Appointment.contact_id == payload.contact_id,
        Appointment.datetime >= start_of_day,
        Appointment.datetime <= end_of_day,
        Appointment.status == "CONFIRMED"
    ).first()

    if same_day_existing:
        return same_day_existing

    # Validar si el slot está ocupado por otro usuario
    slot_taken = db.query(Appointment).filter(
        Appointment.user_id == user_id,
        Appointment.datetime == payload.datetime,
        Appointment.status == "CONFIRMED"
    ).first()

    if slot_taken:
        raise HTTPException(status_code=400, detail="Este horario ya está reservado por otro cliente.")

    # 2. Reagendamiento automático: si el contacto ya tenía una cita previa activa, se libera la anterior
    db.query(Appointment).filter(
        Appointment.contact_id == payload.contact_id,
        Appointment.status.in_(["CONFIRMED", "PENDING"])
    ).delete()

    # 3. Registrar nueva cita
    db_appointment = Appointment(
        contact_id=payload.contact_id,
        user_id=user_id,
        datetime=payload.datetime,
        appointment_type=payload.appointment_type or "PRESENCIAL",
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
    Obtiene todas las citas de la agenda para el panel visual del Calendario del CRM.
    """
    from sqlalchemy import or_
    query = db.query(Appointment).filter(Appointment.status == "CONFIRMED")
    role_str = str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role).lower()
    if role_str not in ["admin", "userrole.admin"]:
        query = query.join(Contact, Appointment.contact_id == Contact.id).filter(
            or_(Appointment.user_id == current_user.id, Contact.assigned_user_id == current_user.id)
        )
    return query.order_by(Appointment.datetime).all()


@router.get("/availability")
def get_user_availability(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Obtiene el horario de disponibilidad separado por modalidades (PRESENCIAL vs VIRTUAL/LLAMADA)
    con duración de slot y tiempo de descanso entre citas.
    """
    from app.models.base import SystemSetting
    
    # Asegurar disponibilidades por defecto si no existen
    ensure_default_availability(db, current_user.id, "PRESENCIAL")
    ensure_default_availability(db, current_user.id, "VIRTUAL")
    
    def get_modality_data(mod: str):
        avs = db.query(Availability).filter(
            Availability.user_id == current_user.id,
            Availability.modality == mod
        ).order_by(Availability.day_of_week, Availability.start_time).all()
        
        by_day = {}
        for av in avs:
            day = av.day_of_week
            if day not in by_day:
                by_day[day] = []
            by_day[day].append({
                "start_time": av.start_time.strftime("%H:%M"),
                "end_time": av.end_time.strftime("%H:%M")
            })
        
        days_result = []
        for day in range(7):
            days_result.append({
                "day_of_week": day,
                "intervals": by_day.get(day, [])
            })
        
        dur_sett = db.query(SystemSetting).filter(SystemSetting.key == f"slot_duration_{mod.lower()}").first()
        buf_sett = db.query(SystemSetting).filter(SystemSetting.key == f"buffer_time_{mod.lower()}").first()
        
        default_dur = 60 if mod == "PRESENCIAL" else 30
        default_buf = 15 if mod == "PRESENCIAL" else 10
        
        return {
            "days": days_result,
            "slot_duration": int(dur_sett.value) if dur_sett and dur_sett.value and dur_sett.value.isdigit() else default_dur,
            "buffer_time": int(buf_sett.value) if buf_sett and buf_sett.value and buf_sett.value.isdigit() else default_buf
        }

    presencial_data = get_modality_data("PRESENCIAL")
    virtual_data = get_modality_data("VIRTUAL")

    return {
        "presencial": presencial_data,
        "virtual": virtual_data,
        "days": virtual_data["days"]  # Compatibilidad con clientes antiguos
    }


def parse_time_str(time_val: Any) -> Optional[time]:
    if not time_val:
        return None
    if isinstance(time_val, time):
        return time_val
    t_str = str(time_val).strip().lower()
    
    is_pm = "p. m." in t_str or "pm" in t_str or "p.m." in t_str
    is_am = "a. m." in t_str or "am" in t_str or "a.m." in t_str
    
    clean = "".join([c for c in t_str if c.isdigit() or c == ":"]).strip()
    if not clean:
        return None
    parts = clean.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if is_pm and h < 12:
            h += 12
        elif is_am and h == 12:
            h = 0
        return time(min(max(0, h), 23), min(max(0, m), 59), 0)
    except Exception:
        return None


@router.post("/availability")
def update_user_availability(
    payload: Any = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Actualiza la disponibilidad de horarios separada por modalidades (PRESENCIAL vs VIRTUAL),
    con soporte para hora de almuerzo, múltiples bloques y duración de cita.
    """
    role_str = str(getattr(current_user.role, "value", current_user.role)).lower()
    is_admin = "admin" in role_str

    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: Solo los administradores pueden configurar los horarios comerciales de atención."
        )

    from app.models.base import SystemSetting
    target_users = db.query(User).all()

    def save_modality_schedule(mod_key: str, mod_data: dict):
        db.query(Availability).filter(Availability.modality == mod_key).delete()
        
        days_list = mod_data.get("days", [])
        for u in target_users:
            for d in days_list:
                day_of_week = d.get("day_of_week")
                intervals = d.get("intervals", [])
                for interval in intervals:
                    start_str = interval.get("start_time")
                    end_str = interval.get("end_time")
                    if not start_str or not end_str:
                        continue
                    st = parse_time_str(start_str)
                    et = parse_time_str(end_str)
                    if st and et:
                        av = Availability(
                            user_id=u.id,
                            day_of_week=day_of_week,
                            start_time=st,
                            end_time=et,
                            modality=mod_key
                        )
                        db.add(av)
        
        # Guardar duración de cita y tiempo de descanso (buffer)
        if "slot_duration" in mod_data and str(mod_data["slot_duration"]).isdigit():
            sd_sett = db.query(SystemSetting).filter(SystemSetting.key == f"slot_duration_{mod_key.lower()}").first()
            if not sd_sett:
                db.add(SystemSetting(key=f"slot_duration_{mod_key.lower()}", value=str(mod_data["slot_duration"])))
            else:
                sd_sett.value = str(mod_data["slot_duration"])
                db.add(sd_sett)

        if "buffer_time" in mod_data and str(mod_data["buffer_time"]).isdigit():
            bt_sett = db.query(SystemSetting).filter(SystemSetting.key == f"buffer_time_{mod_key.lower()}").first()
            if not bt_sett:
                db.add(SystemSetting(key=f"buffer_time_{mod_key.lower()}", value=str(mod_data["buffer_time"])))
            else:
                bt_sett.value = str(mod_data["buffer_time"])
                db.add(bt_sett)

    if isinstance(payload, dict) and ("presencial" in payload or "virtual" in payload):
        if "presencial" in payload:
            save_modality_schedule("PRESENCIAL", payload["presencial"])
        if "virtual" in payload:
            save_modality_schedule("VIRTUAL", payload["virtual"])
    else:
        # Formato plano legado
        save_modality_schedule("VIRTUAL", payload if isinstance(payload, dict) else {"days": payload})

    db.commit()
    return {"status": "success", "message": "Disponibilidad de horarios actualizada exitosamente para ambas modalidades"}


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

    # Control de acceso estricto RBAC / BOLA
    is_admin = current_user.role in [UserRole.ADMIN, "admin", "ADMIN"]
    if not is_admin and appointment.user_id != current_user.id:
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


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    appointment_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Actualiza la modalidad (PRESENCIAL, VIRTUAL, LLAMADA) u otros datos de una cita comercial.
    """
    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    # Control de acceso estricto RBAC / BOLA
    is_admin = current_user.role in [UserRole.ADMIN, "admin", "ADMIN"]
    if not is_admin and appointment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar esta cita."
        )

    appt_type = payload.get("appointment_type") or payload.get("modality") or payload.get("type")
    if appt_type:
        appointment.appointment_type = appt_type

    if "datetime" in payload and payload["datetime"]:
        if isinstance(payload["datetime"], str):
            from datetime import datetime as dt_class
            dt_clean = payload["datetime"].replace("Z", "").split("+")[0]
            appointment.datetime = dt_class.fromisoformat(dt_clean)
        else:
            appointment.datetime = payload["datetime"]

    if "notes" in payload:
        appointment.notes = payload["notes"]
    if "status" in payload:
        appointment.status = payload["status"]
    if "user_id" in payload:
        appointment.user_id = payload["user_id"]

    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    ws_payload = {
        "event": "appointment_updated",
        "data": {
            "id": appointment.id,
            "contact_id": appointment.contact_id,
            "appointment_type": appointment.appointment_type,
            "status": appointment.status
        }
    }
    try:
        await manager.broadcast(ws_payload)
    except Exception:
        pass

    return appointment


@router.get("/holiday-override/{date_str}")
def get_holiday_override(date_str: str, db: Session = Depends(get_db)):
    from app.models.base import SystemSetting
    sett = db.query(SystemSetting).filter(SystemSetting.key == f"holiday_override_{date_str}").first()
    return {"date": date_str, "slots": sett.value if sett else ""}


@router.post("/holiday-override/{date_str}")
def save_holiday_override(
    date_str: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    role_str = str(getattr(current_user.role, "value", current_user.role)).lower()
    if "admin" not in role_str:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: Solo los administradores pueden abrir horarios excepcionales o festivos."
        )

    from app.models.base import SystemSetting
    slots_str = payload.get("slots", "").strip()
    sett = db.query(SystemSetting).filter(SystemSetting.key == f"holiday_override_{date_str}").first()
    if not sett:
        sett = SystemSetting(key=f"holiday_override_{date_str}", value=slots_str)
        db.add(sett)
    else:
        sett.value = slots_str
        db.add(sett)
    db.commit()
    return {"status": "success", "date": date_str, "slots": slots_str}


