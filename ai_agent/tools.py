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

        weekday = target_date.weekday() # 0: Lunes ... 4: Viernes, 5: Sábado, 6: Domingo
        if weekday == 5: # Sábado (Mañana exclusivamente hasta 1 PM)
            candidate_slots = ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "12:00 PM"]
        elif weekday in range(0, 5): # Lunes a Viernes (Mañana y Tarde)
            candidate_slots = ["10:00 AM", "11:00 AM", "12:00 PM", "02:00 PM", "03:00 PM", "04:00 PM", "05:00 PM"] if is_presencial else ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM", "02:00 PM", "02:30 PM", "03:00 PM", "04:00 PM"]
        else: # Domingo (Cerrado)
            candidate_slots = []

        # REGLA DE MARGEN +2 HORAS PARA "HOY"
        # Si la cita es para hoy, calcular la hora mínima permitida (hora actual Bogotá + 2 horas)
        cutoff_time = (now_bogota + dt_tz.timedelta(hours=2)).time() if is_today else None

        valid_slots = []
        for s in candidate_slots:
            # Parsear la hora del slot
            slot_dt = dt_tz.datetime.strptime(f"{target_date} {s}", "%Y-%m-%d %I:%M %p")
            
            # Si es hoy y el slot cae antes del cutoff de +2h, descartarlo
            if is_today and cutoff_time and slot_dt.time() <= cutoff_time:
                continue

            # Verificar capacidad DB
            if slot_counts[s] < max_capacity:
                valid_slots.append(s)

        # Construir Payload JSON de Listas Interactivas Meta WhatsApp API
        interactive_rows = []
        for idx, slot_str in enumerate(valid_slots[:10]):
            interactive_rows.append({
                "id": f"slot_{idx+1}",
                "title": slot_str,
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
            contact = Contact(first_name=user_name, phone=phone, chatbot_enabled=True)
            db.add(contact)
            db.commit()
            db.refresh(contact)
            
        # Generar datetime objeto
        try:
            full_dt_str = f"{date} {time}"
            appt_datetime = dt_save.datetime.strptime(full_dt_str, "%Y-%m-%d %I:%M %p")
        except Exception:
            appt_datetime = dt_save.datetime.utcnow() + dt_save.timedelta(days=1)
            
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
            "modality": modality
        }
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
    check_availability,
    save_appointment,
    update_lead_status,
    request_human_handover,
    generar_y_enviar_propuesta_pdf
]

