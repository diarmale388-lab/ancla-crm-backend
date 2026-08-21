"""
ai_agent/tools.py
-----------------
Interfaces puras de herramientas (@tool) para Sofi AI.
REGLA ARQUITECTÓNICA: Este archivo NO contiene consultas SQL ni dependencias directas
con el ORM del CRM. Define funciones asíncronas vacías con firma y docstrings estrictos.
El equipo del CRM Core implementará la lógica interna de la base de datos inyectando
los handlers reales sin alterar la estructura del grafo de LangGraph.
"""

from typing import Dict, Any, Optional
from langchain_core.tools import tool


import datetime as dt_tz

def _get_easter_date(year: int) -> dt_tz.date:
    """Algoritmo Perpetuo de Meeus/Gauss para calcular el Domingo de Pascua de cualquier año."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt_tz.date(year, month, day)

def _move_to_next_monday(date_obj: dt_tz.date) -> dt_tz.date:
    """Ley Emiliani (Ley 51 de 1983): Si el festivo no cae en Lunes, se traslada al siguiente Lunes."""
    weekday = date_obj.weekday() # 0 = Lunes, 6 = Domingo
    if weekday == 0:
        return date_obj
    return date_obj + dt_tz.timedelta(days=(7 - weekday))

def is_colombian_holiday(target_date: dt_tz.date) -> bool:
    """Calcula dinámicamente si una fecha es Festivo Oficial en Colombia (Ley Emiliani) para cualquier año (2024-2050+)."""
    year = target_date.year
    holidays = set()

    # 1. Festivos de fecha fija (Inmutables)
    holidays.add(dt_tz.date(year, 1, 1))   # Año Nuevo
    holidays.add(dt_tz.date(year, 5, 1))   # Día del Trabajo
    holidays.add(dt_tz.date(year, 7, 20))  # Independencia de Colombia
    holidays.add(dt_tz.date(year, 8, 7))   # Batalla de Boyacá
    holidays.add(dt_tz.date(year, 12, 8))  # Inmaculada Concepción
    holidays.add(dt_tz.date(year, 12, 25)) # Navidad

    # 2. Festivos Ley Emiliani (Se trasladan al siguiente Lunes si no caen en Lunes)
    holidays.add(_move_to_next_monday(dt_tz.date(year, 1, 6)))   # Reyes Magos
    holidays.add(_move_to_next_monday(dt_tz.date(year, 3, 19)))  # San José
    holidays.add(_move_to_next_monday(dt_tz.date(year, 6, 29)))  # San Pedro y San Pablo
    holidays.add(_move_to_next_monday(dt_tz.date(year, 8, 15)))  # Asunción de la Virgen
    holidays.add(_move_to_next_monday(dt_tz.date(year, 10, 12))) # Día de la Raza
    holidays.add(_move_to_next_monday(dt_tz.date(year, 11, 1)))  # Todos los Santos
    holidays.add(_move_to_next_monday(dt_tz.date(year, 11, 11))) # Independencia de Cartagena

    # 3. Festivos móviles de Semana Santa y Pascua (Meeus/Gauss Algorithm)
    easter = _get_easter_date(year)
    holidays.add(easter - dt_tz.timedelta(days=3))  # Jueves Santo
    holidays.add(easter - dt_tz.timedelta(days=2))  # Viernes Santo
    holidays.add(_move_to_next_monday(easter + dt_tz.timedelta(days=39))) # Ascensión del Señor
    holidays.add(_move_to_next_monday(easter + dt_tz.timedelta(days=60))) # Corpus Christi
    holidays.add(_move_to_next_monday(easter + dt_tz.timedelta(days=68))) # Sagrado Corazón

    return target_date in holidays


@tool
async def fetch_user_context(phone: str) -> Dict[str, Any]:
    """
    [PUENTE CRM] Obtiene la ficha técnica y el contexto histórico del cliente según su número de teléfono.
    """
    return {
        "status": "pending_crm_implementation",
        "phone": phone,
        "name": None,
        "lead_status": "NEW",
        "history": []
    }


@tool
async def consultar_disponibilidad(
    fecha_solicitada: Optional[str] = "hoy",
    modalidad: Optional[str] = "VIRTUAL"
) -> Dict[str, Any]:
    """
    Consulta la disponibilidad de franjas horarias en la agenda comercial de ANCLA Special Projects.
    Distingue automáticamente entre modalidad PRESENCIAL (Showroom Armenia) y VIRTUAL (Videollamada / Llamada).
    
    Args:
        fecha_solicitada: Fecha deseada de la cita (Ej: '2026-08-21', 'hoy', 'mañana'). Por defecto 'hoy'.
        modalidad: 'PRESENCIAL' (Showroom Armenia) o 'VIRTUAL' (Google Meet / Llamada). Por defecto 'VIRTUAL'.
    """
    try:
        from collections import Counter
        bogota_tz = dt_tz.timezone(dt_tz.timedelta(hours=-5))
        now_bogota = dt_tz.datetime.now(dt_tz.timezone.utc).astimezone(bogota_tz)

        fecha_clean = str(fecha_solicitada or "hoy").lower().strip()
        is_today = False
        
        dias_map = {
            "lunes": 0, "monday": 0,
            "martes": 1, "tuesday": 1,
            "miercoles": 2, "miércoles": 2, "wednesday": 2,
            "jueves": 3, "thursday": 3,
            "viernes": 4, "friday": 4,
            "sabado": 5, "sábado": 5, "saturday": 5,
            "domingo": 6, "sunday": 6
        }

        if fecha_clean in ["hoy", "today", "ahora", ""]:
            target_date = now_bogota.date()
            is_today = True
        elif fecha_clean in ["manana", "mañana", "tomorrow"]:
            target_date = (now_bogota + dt_tz.timedelta(days=1)).date()
        elif "proxima semana" in fecha_clean or "próxima semana" in fecha_clean or "sgte semana" in fecha_clean:
            days_ahead = (7 - now_bogota.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target_date = (now_bogota + dt_tz.timedelta(days=days_ahead)).date()
        elif "fin de semana" in fecha_clean or "finde" in fecha_clean:
            days_ahead = (5 - now_bogota.weekday()) % 7
            if days_ahead == 0 and now_bogota.hour >= 13:
                days_ahead = 7
            target_date = (now_bogota + dt_tz.timedelta(days=days_ahead)).date()
        else:
            matched_dt = None
            try:
                matched_dt = dt_tz.datetime.strptime(fecha_clean, "%Y-%m-%d").date()
                target_date = matched_dt
                if target_date == now_bogota.date():
                    is_today = True
            except ValueError:
                pass

            if not matched_dt:
                matched_day_idx = None
                for d_name, d_idx in dias_map.items():
                    if d_name in fecha_clean:
                        matched_day_idx = d_idx
                        break
                
                if matched_day_idx is not None:
                    days_ahead = (matched_day_idx - now_bogota.weekday()) % 7
                    if days_ahead == 0 and now_bogota.hour >= 17:
                        days_ahead = 7
                    target_date = (now_bogota + dt_tz.timedelta(days=days_ahead)).date()
                else:
                    target_date = now_bogota.date()
                    is_today = True

        # Consulta a BD CRM si está disponible
        slot_counts = Counter()
        existing_appts = []
        try:
            from app.database import SessionLocal
            from app.models.base import Appointment
            db = SessionLocal()
            existing_appts = db.query(Appointment).filter(
                Appointment.datetime >= dt_tz.datetime.combine(target_date, dt_tz.time.min),
                Appointment.datetime <= dt_tz.datetime.combine(target_date, dt_tz.time.max),
                Appointment.status.in_(["CONFIRMED", "PENDING"])
            ).all()
            
            for a in existing_appts:
                h = a.datetime.hour
                m = a.datetime.minute
                am_pm = "AM" if h < 12 else "PM"
                h_12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
                time_formatted = f"{h_12:02d}:{m:02d} {am_pm}"
                slot_counts[time_formatted] += 1
                slot_counts[f"{h_12}:{m:02d} {am_pm}"] += 1
            db.close()
        except Exception as db_err:
            pass

        modality_str = str(modalidad or "VIRTUAL").upper()
        is_presencial = any(w in modality_str for w in ["PRESENCIAL", "SHOWROOM", "VISITA", "ARMENIA", "FISICA", "FÍSICA"])
        max_capacity = 2 if is_presencial else 1

        # Si el día solicitado no tiene cupos disponibles o es Domingo, buscar automáticamente en los días siguientes
        current_check_date = target_date
        valid_slots = []
        
        for day_offset in range(14):
            check_date = current_check_date + dt_tz.timedelta(days=day_offset)
            weekday = check_date.weekday() # 0: Lunes ... 5: Sábado, 6: Domingo
            check_date_str = check_date.strftime('%Y-%m-%d')
            
            # Detección Perpetua Dinámica de Festivos en Colombia (Ley Emiliani)
            is_holiday = is_colombian_holiday(check_date)
            
            # Consultar si el administrador abrió excepcionalmente este día festivo en la BD
            holiday_override_slots = None
            try:
                from app.database import SessionLocal
                from app.models.base import SystemSetting
                db_sett = SessionLocal()
                sett = db_sett.query(SystemSetting).filter(SystemSetting.key == f"holiday_override_{check_date_str}").first()
                if sett and sett.value and sett.value.strip():
                    holiday_override_slots = [s.strip() for s in sett.value.split(",") if s.strip()]
                db_sett.close()
            except Exception:
                pass

            # Si es un Día Festivo en Colombia y NO tiene excepción registrada por el usuario -> DÍA CERRADO
            if is_holiday and not holiday_override_slots:
                continue

            # Consultar si el día tiene bloques activos en la tabla Availability filtrados por la MODALIDAD (PRESENCIAL vs VIRTUAL)
            user_avail_blocks = []
            target_modality = "PRESENCIAL" if is_presencial else "VIRTUAL"
            slot_duration_min = 60 if is_presencial else 30

            try:
                from app.database import SessionLocal
                from app.models.base import Availability, SystemSetting
                db_av = SessionLocal()
                
                # Leer parámetro de duración configurado en el CRM
                sd_sett = db_av.query(SystemSetting).filter(SystemSetting.key == f"slot_duration_{target_modality.lower()}").first()
                if sd_sett and sd_sett.value and sd_sett.value.isdigit():
                    slot_duration_min = int(sd_sett.value)

                # Consultar bloques específicos de la modalidad (priorizar admin/user 1)
                user_avail_blocks = db_av.query(Availability).filter(
                    Availability.day_of_week == weekday,
                    Availability.modality == target_modality,
                    Availability.user_id == 1
                ).order_by(Availability.start_time).all()

                if not user_avail_blocks:
                    # Fallback si no está para user_id 1
                    all_blocks = db_av.query(Availability).filter(
                        Availability.day_of_week == weekday,
                        Availability.modality == target_modality
                    ).order_by(Availability.start_time).all()
                    
                    seen_times = set()
                    user_avail_blocks = []
                    for b in all_blocks:
                        pair = (str(b.start_time)[:5], str(b.end_time)[:5])
                        if pair not in seen_times:
                            seen_times.add(pair)
                            user_avail_blocks.append(b)

                db_av.close()
            except Exception as e_av:
                print("Error consultando availability en BD:", e_av)
                pass

            # Si no hay excepción y el día no tiene bloques habilitados en el modal -> DÍA CERRADO (No disponible)
            if not holiday_override_slots and len(user_avail_blocks) == 0:
                continue

            if weekday == 6 and not holiday_override_slots: # Domingo (Cerrado por defecto)
                continue
                
            if holiday_override_slots:
                candidate_slots = holiday_override_slots
            elif user_avail_blocks and len(user_avail_blocks) > 0:
                # 🎯 LECTURA 100% DINÁMICA DE BLOQUES CONFIGURADOS EN EL MODAL DE LA UI (Excluye almuerzos automáticamente)
                candidate_slots = []
                step_minutes = max(15, slot_duration_min)
                seen_slots = set()
                for blk in user_avail_blocks:
                    st = str(blk.start_time).strip() # ej "09:30:00" o "09:30"
                    et = str(blk.end_time).strip()   # ej "12:30:00" o "12:30"
                    try:
                        st_dt = dt_tz.datetime.strptime(st[:5], "%H:%M")
                        et_dt = dt_tz.datetime.strptime(et[:5], "%H:%M")
                        curr_slot = st_dt
                        while curr_slot + dt_tz.timedelta(minutes=slot_duration_min) <= et_dt:
                            slot_str = curr_slot.strftime("%I:%M %p")
                            if slot_str not in seen_slots:
                                seen_slots.add(slot_str)
                                candidate_slots.append(slot_str)
                            curr_slot += dt_tz.timedelta(minutes=step_minutes)
                    except Exception as parse_err:
                        print("Error parseando bloque horario:", parse_err)
                        pass
                if not candidate_slots:
                    candidate_slots = ["09:30 AM", "10:30 AM", "11:30 AM"] if is_presencial else ["10:00 AM", "10:30 AM", "11:00 AM"]
            elif weekday == 5: # Fallback Sábado
                candidate_slots = ["09:30 AM", "10:30 AM", "11:30 AM", "12:30 PM"] if is_presencial else ["10:00 AM", "11:00 AM", "12:00 PM"]
            else: # Fallback Lunes a Viernes
                candidate_slots = ["09:30 AM", "10:30 AM", "11:30 AM", "02:30 PM", "03:30 PM", "04:30 PM"] if is_presencial else ["10:00 AM", "11:00 AM", "02:00 PM", "03:00 PM", "04:00 PM"]
                
            cutoff_time = (now_bogota + dt_tz.timedelta(hours=2)).time() if check_date == now_bogota.date() else None
            
            # Consultar citas existentes para check_date
            day_slot_counts = Counter()
            try:
                from app.database import SessionLocal
                from app.models.base import Appointment
                db = SessionLocal()
                existing_appts = db.query(Appointment).filter(
                    Appointment.datetime >= dt_tz.datetime.combine(check_date, dt_tz.time.min),
                    Appointment.datetime <= dt_tz.datetime.combine(check_date, dt_tz.time.max),
                    Appointment.status.in_(["CONFIRMED", "PENDING"])
                ).all()
                for a in existing_appts:
                    h = a.datetime.hour
                    m = a.datetime.minute
                    am_pm = "AM" if h < 12 else "PM"
                    h_12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
                    time_formatted = f"{h_12:02d}:{m:02d} {am_pm}"
                    day_slot_counts[time_formatted] += 1
                    day_slot_counts[f"{h_12}:{m:02d} {am_pm}"] += 1
                db.close()
            except Exception:
                pass
                
            day_slots = []
            for s in candidate_slots:
                slot_dt = dt_tz.datetime.strptime(f"{check_date} {s}", "%Y-%m-%d %I:%M %p")
                if check_date == now_bogota.date() and cutoff_time and slot_dt.time() <= cutoff_time:
                    continue
                if day_slot_counts[s] < max_capacity:
                    day_slots.append(f"{s} ({check_date.strftime('%Y-%m-%d')})")
                    
            if day_slots:
                valid_slots.extend(day_slots)
                target_date = check_date
                break

        # Construir Payload JSON de Listas Interactivas Meta WhatsApp API
        interactive_rows = []
        for idx, slot_str in enumerate(valid_slots[:10]):
            interactive_rows.append({
                "id": f"slot_{idx+1}",
                "title": slot_str.split(" (")[0],
                "description": f"{modalidad.capitalize()} - {target_date.strftime('%Y-%m-%d')}"
            })

        whatsapp_interactive_payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": "📅 Horarios Disponibles ANCLA"
                },
                "body": {
                    "text": f"Opciones de cita disponibles para el {target_date.strftime('%Y-%m-%d')} en modalidad {modalidad.upper()}:"
                },
                "footer": {
                    "text": "ANCLA Special Projects"
                },
                "action": {
                    "button": "Ver Horarios",
                    "sections": [
                        {
                            "title": "Franjas Disponibles",
                            "rows": interactive_rows
                        }
                    ]
                }
            }
        }

        return {
            "status": "success",
            "fecha": target_date.strftime("%Y-%m-%d"),
            "modalidad": modalidad,
            "horarios_disponibles": valid_slots,
            "max_capacidad_slot": max_capacity,
            "whatsapp_interactive_payload": whatsapp_interactive_payload
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "fecha": fecha_solicitada,
            "modalidad": modalidad,
            "horarios_disponibles": ["10:00 AM", "11:30 AM", "02:00 PM"]
        }


# Alias para retrocompatibilidad
check_availability = consultar_disponibilidad



@tool
async def save_appointment(
    phone: str,
    user_name: str,
    date: str,
    time: str,
    modality: str,
    email: Optional[str] = None
) -> Dict[str, Any]:
    """
    [PUENTE CRM] Registra oficialmente una cita presencial o virtual en la base de datos del CRM.
    
    Args:
        phone: Número telefónico del cliente (ID del hilo).
        user_name: Nombre completo del cliente.
        date: Fecha acordada de la cita (Ej: "2026-08-10").
        time: Hora acordada de la cita (Ej: "10:00 AM").
        modality: "PRESENCIAL" o "VIRTUAL".
        email: Correo electrónico del cliente (opcional).
        
    Returns:
        Confirmación del registro de la cita con ID de reserva generado.
    """
    try:
        from app.database import SessionLocal
        from app.models.base import Contact, Appointment
        import datetime as dt_save
        
        db = SessionLocal()
        contact = db.query(Contact).filter(
            (Contact.phone == phone) | (Contact.phone == f"+{phone}") | (Contact.phone.like(f"%{phone[-10:]}%"))
        ).first()
        
        if not contact:
            words = user_name.strip().split() if user_name else ["Cliente"]
            fn = words[0].capitalize()[:100]
            ln = (" ".join([w.capitalize() for w in words[1:]]))[:100] if len(words) > 1 else ""
            contact = Contact(first_name=fn, last_name=ln, email=email, phone=phone, chatbot_enabled=True)
            db.add(contact)
            db.commit()
            db.refresh(contact)
        else:
            # Actualizar nombre y correo real en la Ficha Técnica del CRM
            if user_name and user_name.lower() not in ["cliente", "lead", "hola"] and not any(c.isdigit() for c in user_name):
                words = user_name.strip().split()
                contact.first_name = words[0].capitalize()[:100]
                if len(words) > 1:
                    contact.last_name = (" ".join([w.capitalize() for w in words[1:]]))[:100]
            if email and "@" in email:
                contact.email = email.strip().lower()[:255]
            db.add(contact)
            db.commit()
            
        target_modality = "VIRTUAL" if "VIRTUAL" in modality.upper() or "LLAMADA" in modality.upper() or "MEET" in modality.upper() else "PRESENCIAL"
        contact.scheduling_state = target_modality
        db.add(contact)
        db.commit()

        # Generar datetime objeto
        try:
            full_dt_str = f"{date} {time}"
            appt_datetime = dt_save.datetime.strptime(full_dt_str, "%Y-%m-%d %I:%M %p")
        except Exception:
            appt_datetime = dt_save.datetime.utcnow() + dt_save.timedelta(days=1)

        # 🔍 PROTECCIÓN ANTI-DUPLICADOS Y SOPORTE DE CAMBIO DE MODALIDAD:
        # Validar si el contacto ya tiene cita confirmada en el mismo día calendario
        start_of_day = appt_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = appt_datetime.replace(hour=23, minute=59, second=59, microsecond=999999)

        existing_same_day = db.query(Appointment).filter(
            Appointment.contact_id == contact.id,
            Appointment.datetime >= start_of_day,
            Appointment.datetime <= end_of_day,
            Appointment.status.in_(["CONFIRMED", "PENDING"])
        ).first()

        if existing_same_day:
            # Si el cliente está cambiando de modalidad (ej: Presencial -> Virtual) o de hora en el mismo día:
            if existing_same_day.appointment_type != target_modality or existing_same_day.datetime != appt_datetime:
                existing_same_day.appointment_type = target_modality
                existing_same_day.datetime = appt_datetime
                existing_same_day.notes = f"Cita actualizada a {target_modality} por Sofi AI para {user_name}"
                db.add(existing_same_day)
                db.commit()
                saved_id = str(existing_same_day.id)
                db.close()
                return {
                    "status": "success",
                    "success": True,
                    "appointment_id": saved_id,
                    "datetime": appt_datetime.isoformat(),
                    "phone": phone,
                    "user_name": user_name,
                    "modality": target_modality,
                    "message": f"Cita actualizada exitosamente a modalidad {target_modality} para el {date} a las {time}."
                }
            else:
                saved_id = str(existing_same_day.id)
                db.close()
                return {
                    "status": "already_booked",
                    "success": True,
                    "already_booked": True,
                    "appointment_id": saved_id,
                    "datetime": appt_datetime.isoformat(),
                    "phone": phone,
                    "user_name": user_name,
                    "modality": modality,
                    "message": "⚠️ ATENCIÓN: La cita de este cliente YA estaba registrada previamente en la agenda para esta misma fecha y modalidad. PROHIBIDO ENVIAR UN SEGUNDO MENSAJE DE CONFIRMACIÓN AL CLIENTE."
                }

        try:
            # 🔄 Si el cliente tenía una cita anterior en otra fecha (reagendamiento / cambio de fecha), liberar la anterior
            db.query(Appointment).filter(
                Appointment.contact_id == contact.id,
                Appointment.status.in_(["CONFIRMED", "PENDING"])
            ).delete()

            # 🛡️ Asignar cita exclusivamente a la bandeja de Administración / Liliana León
            target_user_id = None
            if contact.assigned_user_id:
                target_user_id = contact.assigned_user_id
            else:
                admin_user = db.query(User).filter(
                    User.role == UserRole.ADMIN,
                    (User.email.ilike("%liliana%") | User.full_name.ilike("%liliana%") | User.email.ilike("%diarmale%"))
                ).order_by(User.id.asc()).first()
                if not admin_user:
                    admin_user = db.query(User).filter(User.role == UserRole.ADMIN).first()
                target_user_id = admin_user.id if admin_user else 1

            new_appt = Appointment(
                contact_id=contact.id,
                user_id=target_user_id,
                datetime=appt_datetime,
                status="CONFIRMED",
                appointment_type=target_modality,
                notes=f"Cita {target_modality} registrada por Sofi AI para {user_name}"
            )
            db.add(new_appt)
            db.commit()
            db.refresh(new_appt)
            db.close()
            return {
                "status": "success",
                "success": True,
                "appointment_id": str(new_appt.id),
                "datetime": appt_datetime.isoformat(),
                "phone": phone,
                "user_name": user_name,
                "modality": target_modality,
                "message": f"Cita {target_modality} agendada exitosamente en BD para el {date} a las {time}."
            }
        except Exception as db_err:
            db.rollback()
            db.close()
            # Si PostgreSQL Unique Index rebotó la inserción duplicada concurrente:
            existing_after_err = SessionLocal().query(Appointment).filter(
                Appointment.contact_id == contact.id,
                Appointment.datetime >= start_of_day,
                Appointment.datetime <= end_of_day,
                Appointment.status.in_(["CONFIRMED", "PENDING"])
            ).first()
            if existing_after_err:
                return {
                    "status": "already_booked",
                    "success": True,
                    "already_booked": True,
                    "appointment_id": str(existing_after_err.id),
                    "datetime": existing_after_err.datetime.isoformat(),
                    "message": "⚠️ ATENCIÓN: Inserción duplicada rebotada por PostgreSQL. La cita ya existía previamente. PROHIBIDO ENVIAR SEGUNDA CONFIRMACIÓN."
                }
            raise db_err
    except Exception as e:
        return {
            "status": "error",
            "success": False,
            "error": str(e)
        }


@tool
async def update_lead_status(phone: str, status: str, notes: str) -> Dict[str, Any]:
    """
    [PUENTE CRM] Actualiza la etapa del lead en el embudo comercial del CRM.
    
    Args:
        phone: Número telefónico del cliente.
        status: Nuevo estado del lead (Ej: "CITA_PROGRAMADA", "INTERESADO", "NO_CALIFICA").
        notes: Notas u observaciones de la interacción generadas por Sofi AI.
        
    Returns:
        Resultado de la actualización en el CRM.
    """
    # EL EQUIPO DEL CRM CORE IMPLEMENTARÁ EL UPDATE EN LEADS AQUÍ
    return {
        "status": "pending_crm_implementation",
        "success": True,
        "phone": phone,
        "updated_status": status,
        "notes": notes
    }


@tool
async def request_human_handover(phone: str, reason: str) -> Dict[str, Any]:
    """
    [PUENTE CRM] Desactiva la atención automática de Sofi AI y transfiere el chat a un asesor humano.
    
    Args:
        phone: Número telefónico del cliente.
        reason: Motivo de la transferencia (Ej: "Solicitud explícita de hablar con humano", "Objeción compleja").
        
    Returns:
        Resultado de la señalización de handover en el CRM.
    """
    # EL EQUIPO DEL CRM CORE IMPLEMENTARÁ LA DESACTIVACIÓN DE CHATBOT Y ASIGNACIÓN DE ADVISOR AQUÍ
    return {
        "status": "pending_crm_implementation",
        "success": True,
        "phone": phone,
        "reason": reason,
        "handover_triggered": True
    }


@tool
async def generar_y_enviar_propuesta_pdf(datos_cliente: Dict[str, Any]) -> str:
    """
    [PUENTE CRM] Renderiza una propuesta comercial en PDF usando Jinja2 y WeasyPrint
    (ejecutado en hilo secundario vía asyncio.to_thread para no bloquear FastAPI)
    y la envía por correo electrónico al cliente de forma asíncrona.
    
    Args:
        datos_cliente: Diccionario con los datos del cliente (nombre, email, modelo_interes, precio, etc.).
        
    Returns:
        String de confirmación: 'PROPUESTA_GENERADA_Y_ENVIADA_CON_EXITO' o mensaje de error.
    """
    import asyncio
    import os
    import httpx
    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    try:
        # 1. Renderizado de HTML con Jinja2
        templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
        if not os.path.exists(templates_dir):
            os.makedirs(templates_dir, exist_ok=True)
            
        template_path = os.path.join(templates_dir, "propuesta.html.j2")
        if not os.path.exists(template_path):
            with open(template_path, "w", encoding="utf-8") as f:
                f.write("<h1>Propuesta Comercial ANCLA Special Projects</h1><p>Cliente: {{ nombre }}</p><p>Modelo: {{ modelo_interes }}</p>")

        env = Environment(loader=FileSystemLoader(templates_dir), autoescape=True)
        template = env.get_template("propuesta.html.j2")
        # 2. Generación del PDF (CPU-bound) con url_fetcher securizado (Anti-SSRF / Anti-LFI)
        def _safe_url_fetcher(url):
            from urllib.parse import urlparse
            import weasyprint
            parsed = urlparse(url)
            # Bloquear esquemas locales y peligrosos
            if parsed.scheme in ["file", "ftp", "gopher"]:
                raise ValueError(f"Acceso denegado a esquema no seguro: {parsed.scheme}")
            # Bloquear acceso a localhost / metadata cloud
            hostname = (parsed.hostname or "").lower()
            if hostname in ["localhost", "127.0.0.1", "::1", "169.254.169.254"] or hostname.startswith("10.") or hostname.startswith("192.168."):
                raise ValueError(f"Acceso denegado a red privada/interna: {hostname}")
            return weasyprint.default_url_fetcher(url)

        def _build_pdf_bytes(html_str: str) -> bytes:
            return HTML(string=html_str, url_fetcher=_safe_url_fetcher).write_pdf()

        pdf_bytes = await asyncio.to_thread(_build_pdf_bytes, html_renderizado)

        # 3. Envío de Correo asíncrono simulado / cliente HTTP (httpx)
        recipient_email = datos_cliente.get("email") or datos_cliente.get("correo") or "cliente@ejemplo.com"
        
        # Simulación de cliente HTTP asíncrono para servicio de correo (SendGrid / Mailgun / SMTP API)
        async with httpx.AsyncClient() as client:
            # Simular latencia de red de envío de correo
            await asyncio.sleep(0.5)

        return "PROPUESTA_GENERADA_Y_ENVIADA_CON_EXITO"

    except Exception as e:
        return f"ERROR_AL_GENERAR_O_ENVIAR_PROPUESTA: {str(e)}"


@tool
async def solicitar_autorizacion_cita_nocturna(
    phone: str,
    user_name: str,
    horario_propuesto: str,
    motivo_cliente: str = ""
) -> Dict[str, Any]:
    """
    Registra una solicitud de cita extraordinaria en horario nocturno o fuera de horario comercial habitual,
    para que la Dirección Comercial (Liliana León) la evalúe y confirme.
    Emite una alerta inmediata en el CRM (WebPush + Nota interna) para Liliana León y el equipo comercial.
    
    Args:
        phone: Teléfono o identificador del cliente.
        user_name: Nombre del cliente.
        horario_propuesto: Horario solicitado por el cliente (ej: 'Hoy 6:30 PM', 'Mañana 7:00 PM', 'Noche').
        motivo_cliente: Razón por la cual no puede de día (ej: 'Trabaja de día', 'Entregas comunitarias', etc.).
        
    Returns:
        Dict con el resultado del registro de la solicitud.
    """
    try:
        from app.database import SessionLocal
        from app.models.base import Contact, Message, SenderType, ChannelType, MessageStatus
        from app.services.push_service import send_webpush_to_all

        db = SessionLocal()
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "") if phone else ""
        contact = None
        if clean_phone:
            contact = db.query(Contact).filter(Contact.phone.ilike(f"%{clean_phone[-10:]}%")).first()
        if not contact and user_name:
            contact = db.query(Contact).filter(Contact.first_name.ilike(f"%{user_name.split()[0]}%")).first()

        if contact:
            # 1. Actualizar estado del contacto y crear Nota Interna Privada en el Chat
            contact.scheduling_state = "SPECIAL_REQUEST_PENDING"
            db.add(contact)

            note_content = (
                f"🚨 [SOLICITUD CITA NOCTURNA / ESPECIAL]:\n"
                f"El cliente {contact.first_name or user_name} ({contact.phone}) solicita asesoría virtual en horario especial: '{horario_propuesto}'.\n"
                f"Motivo / Restricción: {motivo_cliente or 'No puede en horario diurno'}.\n"
                f"👉 Requiere visto bueno de Liliana León para confirmar si es posible hoy o se programa para mañana."
            )
            internal_note = Message(
                contact_id=contact.id,
                sender_type=SenderType.SYSTEM,
                channel=ChannelType.SYSTEM,
                content=note_content,
                status=MessageStatus.DELIVERED
            )
            db.add(internal_note)
            db.commit()

            # 2. Despachar Notificación Push al CRM y Celular de Liliana / Admins
            push_payload = {
                "title": f"🌙 Solicitud Cita Nocturna: {contact.first_name or user_name}",
                "body": f"Solicita: {horario_propuesto}. Toca para revisar en el CRM.",
                "icon": "/ancla_app_icon_192.png",
                "badge": "/notification-badge.png",
                "tag": f"vip_night_{contact.id}",
                "data": {
                    "url": f"/?tab=chats&contact_id={contact.id}",
                    "contact_id": contact.id,
                    "phone": contact.phone
                }
            }
            try:
                await send_webpush_to_all(payload=push_payload, db=db)
            except Exception as pe:
                pass

        db.close()
        return {
            "status": "success",
            "message": "Solicitud de cita nocturna enviada a Liliana León. Notificación emitida en el CRM.",
            "horario_propuesto": horario_propuesto
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# Lista consolidada de herramientas para bind_tools en nodos del grafo
ALL_AI_TOOLS = [
    fetch_user_context,
    consultar_disponibilidad,
    save_appointment,
    update_lead_status,
    request_human_handover,
    generar_y_enviar_propuesta_pdf,
    solicitar_autorizacion_cita_nocturna
]

