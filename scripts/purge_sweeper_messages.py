"""
scripts/purge_sweeper_messages.py
---------------------------------
Elimina de la base de datos todos los mensajes de contingencia que se despacharon
accidentalmente a los clientes antiguos a las 11:31 am.
"""

import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, ".."))
if os.path.exists(os.path.join(backend_dir, "app")):
    sys.path.insert(0, backend_dir)

from sqlalchemy import text
from app.database import SessionLocal
from app.models.base import Message, SenderType

TARGET_TEXT = "¡Hola! Con mucho gusto te asesoramos sobre nuestras casas modulares (Flex Home y Cápsula Living). ¿En qué ciudad o municipio proyectas tu construcción?"

db = SessionLocal()
try:
    print("\n--- BUSCANDO MENSAJES ERRÓNEOS DE LAS 11:31 AM ---")
    bad_msgs = db.query(Message).filter(
        Message.sender_type == SenderType.AI,
        Message.content.contains("¿En qué ciudad o municipio proyectas tu construcción?")
    ).all()

    print(f"Total mensajes encontrados para eliminar: {len(bad_msgs)}")
    for m in bad_msgs:
        print(f"  - Eliminando Msg ID #{m.id} del Contacto ID #{m.contact_id}")
        db.delete(m)

    db.commit()
    print("✅ Todos los mensajes erróneos fueron eliminados de la base de datos de producción.\n")

finally:
    db.close()
