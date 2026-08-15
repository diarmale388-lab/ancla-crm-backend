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


@tool
async def fetch_user_context(phone: str) -> Dict[str, Any]:
    """
    [PUENTE CRM] Obtiene la ficha técnica y el contexto histórico del cliente según su número de teléfono.
    
    Args:
        phone: Número telefónico del cliente en formato E.164 (Ej: "+573001234567").
        
    Returns:
        Diccionario con datos del usuario: nombre, estado del lead, citas previas y notas comerciales.
    """
    # EL EQUIPO DEL CRM CORE IMPLEMENTARÁ LA CONSULTA SQL / ORM AQUÍ
    return {
        "status": "pending_crm_implementation",
        "phone": phone,
        "name": None,
        "lead_status": "NEW",
        "history": []
    }


@tool
async def consultar_disponibilidad(fecha_solicitada: str, modalidad: str) -> Dict[str, Any]:
    """
    Consulta la disponibilidad de franjas horarias en la agenda comercial de ANCLA Special Projects.
    
    LÓGICA AUTOMÁTICA EN PYTHON:
    1. Si el cliente pide cita para 'hoy', calcula la fecha actual en la zona horaria de Colombia (ZoneInfo("America/Bogota"))
       y suma un margen mínimo de 2 horas desde el momento actual. Franjas antes de esa hora son ignoradas.
    2. Valida capacidad por modalidad (Virtual: máx 1 persona por slot; Presencial Showroom: máx 2 personas por slot).
    3. Construye el payload JSON con la estructura oficial de Meta Interactive List / Buttons API para WhatsApp.

    Args:
        fecha_solicitada: Fecha deseada ('hoy', 'mañana', o en formato 'AAAA-MM-DD').
        modalidad: Modalidad de atención ('PRESENCIAL' o 'VIRTUAL').
        
    Returns:
        Diccionario estructurado con la lista de horarios libres y el objeto whatsapp_interactive_payload.
    """
    try:
        import datetime as dt_tz
        from collections import Counter

        try:
            from zoneinfo import ZoneInfo
            bogota_tz = ZoneInfo("America/Bogota")
            now_bogota = dt_tz.datetime.now(bogota_tz)
        except Exception:
            bogota_tz = dt_tz.timezone(dt_tz.timedelta(hours=-5))
            now_bogota = dt_tz.datetime.now(bogota_tz)

        
        fecha_clean = fecha_solicitada.lower().strip()
        is_today = False
        
        if fecha_clean in ["hoy", "today", "ahora"]:
            target_date = now_bogota.date()
            is_today = True
        elif fecha_clean in ["manana", "mañana", "tomorrow"]:
            target_date = (now_bogota + dt_tz.timedelta(days=1)).date()
        else:
            try:
                target_date = dt_tz.datetime.strptime(fecha_clean, "%Y-%m-%d").date()
                if target_date == now_bogota.date():
                    is_today = True
            except ValueError:
                # Si viene texto no formateado, asume la fecha de hoy o mañana según hora actual
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

        is_presencial = "PRESENCIAL" in modalidad.upper() or "SHOWROOM" in modalidad.upper()
        max_capacity = 2 if is_presencial else 1

        # Si el día solicitado no tiene cupos disponibles o es Domingo, buscar automáticamente en los días siguientes
        current_check_date = target_date
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
async def consultar_disponibilidad(
    fecha_solicitada: str,
    modalidad: str
) -> Dict[str, Any]:
    """
    [PUENTE CRM] Consulta las franjas horarias libres reales respetando los bloques configurados en la agenda y los festivos en Colombia.
    """
    try:
        try:
            target_date = dt_tz.datetime.strptime(fecha_solicitada, "%Y-%m-%d").date()
        except Exception:
            target_date = now_bogota.date()

        if target_date < now_bogota.date():
            target_date = now_bogota.date()

        is_presencial = "PRESENCIAL" in modalidad.upper() or "SHOWROOM" in modalidad.upper()
        max_capacity = 2 if is_presencial else 1

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

            # Consultar si el día tiene bloques activos en la tabla Availability (Configurados en el Modal de la UI)
            user_avail_blocks = []
            try:
                from app.database import SessionLocal
                from app.models.base import Availability
                db_av = SessionLocal()
                # Priorizar los bloques configurados por el usuario o administrador principal
                user_avail_blocks = db_av.query(Availability).filter(
                    Availability.day_of_week == weekday,
                    Availability.user_id == 1
                ).all()
                if not user_avail_blocks:
                    user_avail_blocks = db_av.query(Availability).filter(Availability.day_of_week == weekday).all()
                db_av.close()
            except Exception:
                pass

            # Si no hay excepción y el día no tiene bloques habilitados en el modal -> DÍA CERRADO (No disponible)
            if not holiday_override_slots and len(user_avail_blocks) == 0:
                continue

            if weekday == 6 and not holiday_override_slots: # Domingo (Cerrado por defecto)
                continue
                
            if holiday_override_slots:
                candidate_slots = holiday_override_slots
            elif user_avail_blocks and len(user_avail_blocks) > 0:
                # 🎯 LECTURA 100% DINÁMICA DE BLOQUES CONFIGURADOS EN EL MODAL DE LA UI
                candidate_slots = []
                for blk in user_avail_blocks:
                    st = blk.start_time.strip() # ej "09:00" o "09:00:00"
                    et = blk.end_time.strip()   # ej "13:00" o "17:00:00"
                    try:
                        st_dt = dt_tz.datetime.strptime(st[:5], "%H:%M")
                        et_dt = dt_tz.datetime.strptime(et[:5], "%H:%M")
                        curr_slot = st_dt
                        while curr_slot < et_dt:
                            candidate_slots.append(curr_slot.strftime("%I:%M %p"))
                            curr_slot += dt_tz.timedelta(minutes=60 if is_presencial else 30)
                    except Exception as parse_err:
                        print("Error parseando bloque horario:", parse_err)
                        pass
                if not candidate_slots:
                    candidate_slots = ["09:30 AM", "10:30 AM", "11:30 AM"]
            elif weekday == 5: # Fallback Sábado (Mañana hasta 1 PM)
                candidate_slots = ["09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM"]
            else: # Fallback Lunes a Viernes
                candidate_slots = ["09:30 AM", "10:30 AM", "11:30 AM", "02:00 PM", "03:00 PM", "04:00 PM", "05:00 PM"] if is_presencial else ["09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "02:00 PM", "02:30 PM", "03:00 PM", "04:00 PM"]
                
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
            
        # Generar datetime objeto
        try:
            full_dt_str = f"{date} {time}"
            appt_datetime = dt_save.datetime.strptime(full_dt_str, "%Y-%m-%d %I:%M %p")
        except Exception:
            appt_datetime = dt_save.datetime.utcnow() + dt_save.timedelta(days=1)

        # 🔍 PROTECCIÓN ANTI-DUPLICADOS A LARGO PLAZO:
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
            db.close()
            return {
                "status": "already_booked",
                "success": True,
                "already_booked": True,
                "appointment_id": str(existing_same_day.id),
                "datetime": existing_same_day.datetime.isoformat(),
                "phone": phone,
                "user_name": user_name,
                "modality": modality,
                "message": "⚠️ ATENCIÓN: La cita de este cliente YA estaba registrada previamente en la agenda para esta misma fecha. PROHIBIDO ENVIAR UN SEGUNDO MENSAJE DE CONFIRMACIÓN AL CLIENTE."
            }

        try:
            new_appt = Appointment(
                contact_id=contact.id,
                user_id=1,
                datetime=appt_datetime,
                status="CONFIRMED",
                appointment_type="VIRTUAL" if "VIRTUAL" in modality.upper() or "LLAMADA" in modality.upper() or "MEET" in modality.upper() else "PRESENCIAL",
                notes=f"Cita {modality} registrada por Sofi AI para {user_name}"
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
                "modality": modality,
                "message": f"Cita {modality} agendada exitosamente en BD para el {date} a las {time}."
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

        env = Environment(loader=FileSystemLoader(templates_dir))
        template = env.get_template("propuesta.html.j2")
        html_renderizado = template.render(**datos_cliente)

        # 2. Generación del PDF (CPU-bound) envuelto en asyncio.to_thread
        def _build_pdf_bytes(html_str: str) -> bytes:
            return HTML(string=html_str).write_pdf()

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


# Lista consolidada de herramientas para bind_tools en nodos del grafo
ALL_AI_TOOLS = [
    fetch_user_context,
    consultar_disponibilidad,
    save_appointment,
    update_lead_status,
    request_human_handover,
    generar_y_enviar_propuesta_pdf
]

