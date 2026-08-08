"""
scripts/live_monitor.py
-----------------------
Monitor en tiempo real conectado directamente a la base de datos PostgreSQL de producción (Neon).
Observa nuevos contactos, mensajes entrantes de WhatsApp, llamadas a herramientas de Sofi AI y citas.
"""

import sys
import os
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, ".."))
if os.path.exists(os.path.join(backend_dir, "app")):
    sys.path.insert(0, backend_dir)

from sqlalchemy import text
from app.database import SessionLocal
from app.models.base import Contact, Message, Appointment

print("\n========================================================")
print("🔴 [MONITOR EN VIVO CONECTADO A NEON POSTGRESQL / SOFI AI]")
print("========================================================")
print("📡 Escuchando nuevos mensajes, contactos y citas en tiempo real...\n")

db = SessionLocal()
last_msg_id = 0
last_contact_id = 0
last_app_id = 0

try:
    max_m = db.query(Message).order_by(Message.id.desc()).first()
    if max_m:
        last_msg_id = max_m.id
    max_c = db.query(Contact).order_by(Contact.id.desc()).first()
    if max_c:
        last_contact_id = max_c.id
    max_a = db.query(Appointment).order_by(Appointment.id.desc()).first()
    if max_a:
        last_app_id = max_a.id
    print(f"Estado inicial de sincronización: Último Msg ID={last_msg_id}, Contacto ID={last_contact_id}\n")
finally:
    db.close()

while True:
    db = SessionLocal()
    try:
        # 1. Nuevos contactos
        new_contacts = db.query(Contact).filter(Contact.id > last_contact_id).order_by(Contact.id.asc()).all()
        for c in new_contacts:
            last_contact_id = c.id
            print(f"👤 [NUEVO CONTACTO #{c.id}]")
            print(f"   Nombre: {c.first_name} {c.last_name}")
            print(f"   Teléfono: {c.phone}")
            print(f"   Origen: {c.source}")
            print(f"   Chatbot Enabled: {c.chatbot_enabled}\n")

        # 2. Nuevos mensajes
        new_msgs = db.query(Message).filter(Message.id > last_msg_id).order_by(Message.id.asc()).all()
        for m in new_msgs:
            last_msg_id = m.id
            sender = str(m.sender_type).replace("SenderType.", "")
            tag = "📩 [CLIENTE ENTRADA]" if sender.upper() == "CONTACT" else "🤖 [SOFI AI RESPUESTA]" if sender.upper() == "AI" else "💻 [SISTEMA]"
            print(f"{tag} (Msg ID #{m.id} | Contacto #{m.contact_id}):")
            print(f"   Hora: {m.created_at}")
            print(f"   Contenido:\n{m.content}\n")

        # 3. Nuevas citas agendadas
        new_apps = db.query(Appointment).filter(Appointment.id > last_app_id).order_by(Appointment.id.asc()).all()
        for a in new_apps:
            last_app_id = a.id
            print(f"📅 [NUEVA CITA AGENDADA #{a.id}]")
            print(f"   Contacto ID: {a.contact_id}")
            print(f"   Fecha/Hora: {a.datetime}")
            print(f"   Modalidad: {a.appointment_type or 'VIRTUAL'}")
            print(f"   Estado: {a.status}\n")

    except Exception as e:
        pass
    finally:
        db.close()

    time.sleep(2)
