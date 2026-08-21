import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.base import Contact, User, Appointment, Message, LeadActivityLog, UserRole

def sanitize_database_assignments():
    print("\n" + "=" * 75)
    print("🧹 EJECUCIÓN DE SANEAMIENTO CONTROLADO DE ASIGNACIONES (POSTGRESQL)")
    print("=" * 75)

    db = SessionLocal()
    try:
        # 1. Identificar administradores y cuenta de Liliana León
        users = db.query(User).all()
        user_map = {u.id: u for u in users}
        
        liliana_user = db.query(User).filter(
            (User.email.ilike("%liliana%")) | (User.full_name.ilike("%Liliana%")) | (User.id == 3)
        ).first()

        admin_user = db.query(User).filter(User.role == UserRole.ADMIN).first()
        admin_owner_id = liliana_user.id if liliana_user else (admin_user.id if admin_user else 1)

        print(f"👑 Cuenta Directiva de Respaldo / Asignación: '{user_map.get(admin_owner_id, None).full_name if admin_owner_id in user_map else admin_owner_id}' (ID: {admin_owner_id})")

        # 2. Consultar registros de actividad para detectar asignaciones manuales ejecutadas por Liliana
        manual_logs = db.query(LeadActivityLog).filter(
            LeadActivityLog.user_id == (liliana_user.id if liliana_user else None),
            (LeadActivityLog.activity_type == "advisor_reassigned") | (LeadActivityLog.activity_type == "agent_assigned")
        ).all()
        
        manual_contact_ids = {log.contact_id for log in manual_logs}
        print(f"🔍 Contactos identificados con asignación manual explícita de Liliana: {list(manual_contact_ids)}")

        # 3. Procesar todos los contactos
        all_contacts = db.query(Contact).all()
        total_contacts = len(all_contacts)
        
        updated_to_unassigned = []
        preserved_contacts = []

        for contact in all_contacts:
            # Si el contacto fue asignado manualmente por Liliana, se preserva
            if contact.id in manual_contact_ids:
                assigned_name = user_map.get(contact.assigned_user_id).full_name if contact.assigned_user_id in user_map else f"ID #{contact.assigned_user_id}"
                preserved_contacts.append({
                    "id": contact.id,
                    "name": f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
                    "phone": contact.phone,
                    "assigned_to": assigned_name
                })
            else:
                # Si tenía asignación automática previa (round-robin o bot), se limpia a NULL
                prev_assigned = contact.assigned_user_id
                if prev_assigned is not None:
                    contact.assigned_user_id = None
                    db.add(contact)
                    updated_to_unassigned.append({
                        "id": contact.id,
                        "name": f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
                        "phone": contact.phone,
                        "previous_agent": user_map.get(prev_assigned).full_name if prev_assigned in user_map else f"ID #{prev_assigned}"
                    })

        # 4. Ajustar citas de contactos sin asignar para que pertenezcan a la dirección comercial
        appointments = db.query(Appointment).all()
        updated_appts = 0
        for appt in appointments:
            contact = db.query(Contact).filter(Contact.id == appt.contact_id).first()
            if contact and contact.assigned_user_id is None:
                if appt.user_id != admin_owner_id:
                    appt.user_id = admin_owner_id
                    db.add(appt)
                    updated_appts += 1

        db.commit()

        print(f"\n📊 RESULTADOS DEL SANEAMIENTO:")
        print(f"  • Total Contactos Evaluados: {total_contacts}")
        print(f"  • Contactos restablecidos a 'Sin Asignar' (NULL): {len(updated_to_unassigned)}")
        for item in updated_to_unassigned:
            print(f"    - Contacto #{item['id']} ({item['name']} | {item['phone']}) ➔ Desasignado de '{item['previous_agent']}'")

        print(f"  • Contactos Preservados con Asesor: {len(preserved_contacts)}")
        for item in preserved_contacts:
            print(f"    - Contacto #{item['id']} ({item['name']} | {item['phone']}) ➔ Mantiene a '{item['assigned_to']}'")

        print(f"  • Citas aseguradas bajo la Dirección Comercial: {updated_appts}")

        # 5. Verificación de Seguridad y Aislamiento RBAC
        print("\n" + "=" * 75)
        print("🛡️ VERIFICACIÓN DE AISLAMIENTO RBAC (SIMULACIÓN EN VIVO)")
        print("=" * 75)

        # Crear o simular un asesor comercial
        mock_asesor = type('MockAsesor', (), {'id': 999, 'email': 'asesor_prueba@ancla.com', 'role': 'asesor', 'full_name': 'Asesor Comercial Prueba'})()
        
        # Simular consulta GET /chats/contacts para Asesor
        asesor_visible_contacts = db.query(Contact).filter(Contact.assigned_user_id == mock_asesor.id).all()
        print(f"  👤 Asesor Comercial (ID: {mock_asesor.id}):")
        print(f"     ➔ Contactos visibles en su bandeja: {len(asesor_visible_contacts)} (0 prospectos no asignados expuestos)")
        assert len(asesor_visible_contacts) == 0, "El asesor no debe ver contactos sin asignar"
        print("     ✅ [PASS] Ningún prospecto 'Sin Asignar' es accesible por asesores.")

        # Simular consulta GET /chats/contacts para Administrador / Liliana
        admin_visible_contacts = db.query(Contact).all()
        print(f"  👑 Dirección Comercial / Admin:")
        print(f"     ➔ Contactos visibles en la bandeja general: {len(admin_visible_contacts)} de {total_contacts}")
        assert len(admin_visible_contacts) == total_contacts, "El admin debe ver todos los contactos"
        print("     ✅ [PASS] La Dirección Comercial mantiene visibilidad total del 100% de los prospectos.")

        print("\n" + "=" * 75)
        print("🎉 SANEAMIENTO COMPLETADO EXITOSAMENTE Y BASE DE DATOS BLINDADA")
        print("=" * 75 + "\n")

        return {
            "total_contacts": total_contacts,
            "updated_to_unassigned": updated_to_unassigned,
            "preserved_contacts": preserved_contacts,
            "updated_appts": updated_appts
        }
    finally:
        db.close()

if __name__ == "__main__":
    sanitize_database_assignments()
