import json
from datetime import datetime
from app.database import SessionLocal, engine
from app.models.base import Base, Contact, Appointment, User

def seed_data():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.query(User).first()
        user_id = user.id if user else 1

        # Cargar full backup si existe
        try:
            with open("neon_db_backup_full.json", "r", encoding="utf-8") as f:
                backup = json.load(f)
                
                for c_data in backup.get("contacts", []):
                    phone = c_data.get("phone")
                    if not phone:
                        continue
                    existing = db.query(Contact).filter(Contact.phone == phone).first()
                    if not existing:
                        c = Contact(
                            id=c_data.get("id"),
                            first_name=c_data.get("first_name"),
                            last_name=c_data.get("last_name"),
                            phone=phone,
                            email=c_data.get("email"),
                            source=c_data.get("source"),
                            pipeline_stage_id=c_data.get("pipeline_stage_id", 1),
                            chatbot_enabled=c_data.get("chatbot_enabled", True),
                            qualification_level=c_data.get("qualification_level"),
                            qualification_notes=c_data.get("qualification_notes")
                        )
                        db.add(c)
                db.commit()
                print("Contactos de backup completo insertados.")

                for a_data in backup.get("appointments", []):
                    app_id = a_data.get("id")
                    contact_id = a_data.get("contact_id")
                    dt_str = a_data.get("datetime")
                    if not dt_str or not contact_id:
                        continue
                    existing_app = db.query(Appointment).filter(Appointment.id == app_id).first()
                    if not existing_app:
                        dt = datetime.fromisoformat(dt_str.replace("Z", ""))
                        app = Appointment(
                            id=app_id,
                            contact_id=contact_id,
                            user_id=user_id,
                            datetime=dt,
                            status=a_data.get("status", "CONFIRMED"),
                            notes=a_data.get("notes", "")
                        )
                        db.add(app)
                db.commit()
                print("Citas de backup completo insertadas.")
        except Exception as e:
            print(f"Aviso leyendo neon_db_backup_full.json: {e}")

        # Cargar classified_56.json para asegurar citas de showroom presenciales y Meets del 28/29 de Julio
        try:
            with open("classified_56.json", "r", encoding="utf-8") as f:
                cls_data = json.load(f)

                categories = [
                    ("presenciales", "Presencial Showroom Armenia"),
                    ("meets", "Virtual Google Meet / Llamada")
                ]

                for cat_key, default_note in categories:
                    items = cls_data.get(cat_key, [])
                    for item in items:
                        phone = str(item.get("phone", "")).strip()
                        if not phone:
                            continue
                        
                        contact = db.query(Contact).filter(Contact.phone == phone).first()
                        if not contact:
                            names = (item.get("name") or "Cliente").split(" ", 1)
                            fname = names[0]
                            lname = names[1] if len(names) > 1 else ""
                            contact = Contact(
                                first_name=fname,
                                last_name=lname,
                                phone=phone,
                                email=item.get("email") if "No provisto" not in (item.get("email") or "") else None,
                                source="Formulario Meta Ads",
                                pipeline_stage_id=1,
                                chatbot_enabled=True,
                                qualification_notes=f"Categoría: {default_note}. Registrado para Showroom."
                            )
                            db.add(contact)
                            db.commit()
                            db.refresh(contact)

                        dt_str = item.get("datetime_dt")
                        if dt_str:
                            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                            existing_app = db.query(Appointment).filter(
                                Appointment.contact_id == contact.id,
                                Appointment.datetime == dt
                            ).first()
                            if not existing_app:
                                app = Appointment(
                                    contact_id=contact.id,
                                    user_id=user_id,
                                    datetime=dt,
                                    status="CONFIRMED",
                                    notes=f"Cita {default_note} para {item.get('name')}"
                                )
                                db.add(app)
                db.commit()
                print("Citas y contactos de classified_56.json sincronizados.")

        except Exception as e:
            print(f"Aviso procesando classified_56.json: {e}")

        tot_c = db.query(Contact).count()
        tot_a = db.query(Appointment).count()
        print(f"Total en BD: {tot_c} contactos y {tot_a} citas agendadas.")

    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
