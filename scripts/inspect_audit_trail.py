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

db = SessionLocal()
try:
    print("--- EVENT AUDIT TRAIL FOR CONTACT 496 ---")
    rows = db.execute(text("SELECT id, timestamp, source, event_type, execution_path, payload FROM event_audit_trail WHERE contact_id = 496 ORDER BY id ASC")).fetchall()
    for r in rows:
        print(f"ID:{r[0]} | TS:{r[1]} | Source:{r[2]} | Event:{r[3]} | ExecPath:{r[4]} | Payload:\n{r[5]}\n")

    print("--- ALL AUDIT EVENTS FROM LAST 30 MINUTES ---")
    recent = db.execute(text("SELECT id, contact_id, timestamp, source, event_type, execution_path, payload FROM event_audit_trail ORDER BY id DESC LIMIT 20")).fetchall()
    for r in reversed(recent):
        print(f"ID:{r[0]} | Contact:{r[1]} | TS:{r[2]} | Source:{r[3]} | Event:{r[4]} | ExecPath:{r[5]} | Payload:\n{r[6]}\n")

finally:
    db.close()
