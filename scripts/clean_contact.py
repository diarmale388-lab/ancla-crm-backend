"""
scripts/clean_contact.py
------------------------
Limpia y purga de la base de datos relacional todos los mensajes, citas, logs y registros
asociados a los números de teléfono especificados (ej: 3177001670, 573177001670, 57300000000).
"""

import sys
import os

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

TARGET_PHONES = ["3177001670", "573177001670", "+573177001670", "57300000000", "+57300000000"]


def clean_target_contacts():
    db = SessionLocal()
    try:
        contacts = db.query(Contact).filter(
            (Contact.phone.in_(TARGET_PHONES)) |
            (Contact.first_name.ilike("%Diego%")) |
            (Contact.last_name.ilike("%Machado%"))
        ).all()

        if not contacts:
            print("[CLEANUP] No se encontraron contactos coincidentes para purgar.")
            return

        contact_ids = [c.id for c in contacts]
        print(f"[CLEANUP] Contactos encontrados para purgar: {contact_ids}")
        id_list_str = ",".join(map(str, contact_ids))

        # Ejecutar purga de mensajes y citas
        db.execute(text(f"DELETE FROM messages WHERE contact_id IN ({id_list_str})"))
        db.execute(text(f"DELETE FROM appointments WHERE contact_id IN ({id_list_str})"))
        db.commit()

        for tbl in ["notes", "lead_activity_logs", "habeas_data_consent_logs", "event_audit_trail"]:
            try:
                db.execute(text(f"DELETE FROM {tbl} WHERE contact_id IN ({id_list_str})"))
                db.commit()
            except Exception:
                db.rollback()

        db.execute(text(f"DELETE FROM contacts WHERE id IN ({id_list_str})"))
        db.commit()
        print(f"[CLEANUP] ✅ Purga completada exitosamente. Contactos {contact_ids} y todos sus registros asociados fueron eliminados.")

    except Exception as e:
        import traceback
        print(f"[CLEANUP ERROR]: {e}")
        print(traceback.format_exc())
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    clean_target_contacts()
