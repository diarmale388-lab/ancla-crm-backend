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
    c = db.query(Contact).filter(Contact.id == 497).first()
    if c:
        print(f"Contact 497:")
        print(f"  Phone: {c.phone}")
        print(f"  Name: {c.first_name} {c.last_name}")
        print(f"  Source: {c.source}")
        print(f"  SchedulingState: {c.scheduling_state}")
        print(f"  ChatbotEnabled: {c.chatbot_enabled}")
        print(f"  Notes: {c.qualification_notes}\n")

    m_user = db.query(Message).filter(Message.id == 3549).first()
    if m_user:
        print(f"Message 3549 (User):")
        print(f"  Created: {m_user.created_at}")
        print(f"  ExternalID: {m_user.external_message_id}")
        print(f"  Content: {m_user.content}\n")

    m_ai = db.query(Message).filter(Message.id == 3550).first()
    if m_ai:
        print(f"Message 3550 (AI):")
        print(f"  Created: {m_ai.created_at}")
        print(f"  ExternalID: {m_ai.external_message_id}")
        print(f"  Status: {m_ai.status}")
        print(f"  Content: {m_ai.content}\n")

    print("--- EVENT AUDIT TRAIL FOR 497 ---")
    audits = db.execute(text("SELECT id, timestamp, source, event_type, execution_path, payload FROM event_audit_trail WHERE contact_id = 497 ORDER BY id ASC")).fetchall()
    for a in audits:
        print(f"Audit {a[0]}: Source={a[2]} | Event={a[3]} | ExecPath={a[4]} | Payload:\n{a[5]}")

finally:
    db.close()
