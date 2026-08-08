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
from app.models.base import Contact, Message

db = SessionLocal()
try:
    print("\n--- ULTIMOS 10 MENSAJES REGISTRADOS EN LA BD ---")
    msgs = db.query(Message).order_by(Message.id.desc()).limit(10).all()
    for m in reversed(msgs):
        print(f"ID: {m.id} | Contact: {m.contact_id} | Sender: {m.sender_type} | ExtID: {m.external_message_id} | Created: {m.created_at}")
        print(f"Content: {m.content[:150] if m.content else ''}\n---")

    print("\n--- ULTIMOS 5 CONTACTOS REGISTRADOS ---")
    contacts = db.query(Contact).order_by(Contact.id.desc()).limit(5).all()
    for c in contacts:
        print(f"ID: {c.id} | Phone: {c.phone} | Name: {c.first_name} {c.last_name} | Created: {c.created_at}")

finally:
    db.close()
