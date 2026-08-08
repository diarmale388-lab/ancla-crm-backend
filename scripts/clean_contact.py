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

        # 1. Eliminar Citas
        db.query(Appointment).filter(Appointment.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.commit()
        print("[CLEANUP] Citas eliminadas.")

        # 2. Eliminar Mensajes
        db.query(Message).filter(Message.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.commit()
        print("[CLEANUP] Mensajes eliminados.")

        # 3. Eliminar tablas relacionadas por Foreign Key
        tables_to_clean = ["lead_activity_logs", "habeas_data_consent_logs", "event_audit_trail", "blackbox_audit_logs"]
        for tbl in tables_to_clean:
            try:
                db.execute(text(f"DELETE FROM {tbl} WHERE contact_id IN ({id_list_str})"))
                db.commit()
                print(f"[CLEANUP] Registros eliminados de '{tbl}'.")
            except Exception as tbl_err:
                db.rollback()
                print(f"[CLEANUP] Omitiendo '{tbl}': {tbl_err}")

        # 4. Eliminar los contactos de la tabla contacts
        db.query(Contact).filter(Contact.id.in_(contact_ids)).delete(synchronize_session=False)
        db.commit()

        print(f"[CLEANUP] ✅ Purga completada exitosamente. Contactos {contact_ids} y todos sus historiales fueron eliminados por completo.")

    except Exception as e:
        import traceback
        print(f"[CLEANUP ERROR]: {e}")
        print(traceback.format_exc())
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    clean_target_contacts()
