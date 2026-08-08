import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, ".."))
if os.path.exists(os.path.join(backend_dir, "app")):
    sys.path.insert(0, backend_dir)

from app.database import SessionLocal
from app.models.base import SystemSetting, Contact, Message

db = SessionLocal()
try:
    print("\n--- ALL SYSTEM SETTINGS IN DB ---")
    settings = db.query(SystemSetting).all()
    for s in settings:
        print(f"Key: {s.key}")
        print(f"Value: {s.value[:300] if s.value else None}\n")

    print("\n--- LAST 10 MESSAGES IN DB ---")
    msgs = db.query(Message).order_by(Message.id.desc()).limit(10).all()
    for m in reversed(msgs):
        print(f"ID:{m.id} | ContactID:{m.contact_id} | Sender:{m.sender_type} | Content:\n{m.content}\n---")

finally:
    db.close()
