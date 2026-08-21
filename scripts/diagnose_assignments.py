import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine
from app.models.base import Contact, User, Appointment, Message, LeadActivityLog, PipelineStage, SenderType

def run_diagnosis():
    db = SessionLocal()
    try:
        print("=" * 70)
        print("🔍 DIAGNÓSTICO PREVIO DE ASIGNACIONES (BASE DE DATOS)")
        print("=" * 70)

        # 1. Usuarios
        users = db.query(User).all()
        user_map = {u.id: u for u in users}
        print(f"\n👥 USUARIOS REGISTRADOS EN BD ({len(users)} en total):")
        liliana_user_ids = []
        admin_user_ids = []
        for u in users:
            role_str = str(u.role).upper()
            is_liliana = "LILIANA" in (u.full_name or "").upper() or "LILIANA" in (u.email or "").upper()
            is_admin = "ADMIN" in role_str or is_liliana
            if is_liliana:
                liliana_user_ids.append(u.id)
            if is_admin:
                admin_user_ids.append(u.id)
            print(f"  • ID #{u.id} | Nombre: '{u.full_name}' | Email: '{u.email}' | Rol: {u.role} | Activo: {u.is_active} {'⭐ (Liliana León)' if is_liliana else ''}")

        # 2. Contactos totales y distribución de asignaciones
        contacts = db.query(Contact).all()
        total_contacts = len(contacts)
        unassigned_contacts = [c for c in contacts if c.assigned_user_id is None]
        assigned_contacts = [c for c in contacts if c.assigned_user_id is not None]

        print(f"\n📱 CONTACTOS TOTALES EN CRM: {total_contacts}")
        print(f"  • Sin Asignar (assigned_user_id = NULL): {len(unassigned_contacts)}")
        print(f"  • Actualmente Asignados: {len(assigned_contacts)}")

        # Desglose por asesor
        assignment_breakdown = {}
        for c in assigned_contacts:
            uid = c.assigned_user_id
            assignment_breakdown[uid] = assignment_breakdown.get(uid, []) + [c]

        print("\n📊 DESGLOSE DE ASIGNACIONES ACTUALES POR ASESOR:")
        for uid, c_list in assignment_breakdown.items():
            u_name = user_map[uid].full_name if uid in user_map else f"Usuario #{uid}"
            print(f"  • Asesor: '{u_name}' (ID: {uid}) ➔ {len(c_list)} contactos")

        # 3. Revisar logs de actividad para encontrar asignaciones manuales de Liliana León / Admins
        reassign_logs = db.query(LeadActivityLog).filter(
            (LeadActivityLog.activity_type == "advisor_reassigned") |
            (LeadActivityLog.activity_type == "agent_assigned") |
            (LeadActivityLog.description.ilike("%asignado%")) |
            (LeadActivityLog.description.ilike("%reasignado%"))
        ).all()

        print(f"\n📜 REGISTROS DE ACTIVIDAD DE REASIGNACIÓN ENCONTRADOS: {len(reassign_logs)}")
        manually_assigned_contact_ids = set()
        for log in reassign_logs:
            actor = user_map.get(log.user_id)
            actor_name = actor.full_name if actor else f"Usuario #{log.user_id}"
            is_manual_by_admin = log.user_id in admin_user_ids or log.user_id in liliana_user_ids
            print(f"  - Log #{log.id} | Contacto #{log.contact_id} | Ejecutado por: '{actor_name}' (ID: {log.user_id}) | Fecha: {log.created_at} | '{log.description}'")
            if is_manual_by_admin:
                manually_assigned_contact_ids.add(log.contact_id)

        # 4. Revisar notas internas del sistema
        system_notes = db.query(Message).filter(
            Message.sender_type == SenderType.SYSTEM,
            (Message.content.ilike("%asignado a%")) | (Message.content.ilike("%reasignado a%"))
        ).all()
        for sn in system_notes:
            print(f"  - Nota #{sn.id} | Contacto #{sn.contact_id} | '{sn.content[:100]}...'")

        # 5. Citas asociadas
        appointments = db.query(Appointment).all()
        print(f"\n📅 TOTAL DE CITAS (APPOINTMENTS): {len(appointments)}")
        for appt in appointments:
            c = db.query(Contact).filter(Contact.id == appt.contact_id).first()
            c_name = f"{c.first_name or ''} {c.last_name or ''}".strip() if c else "Sin Contacto"
            u_name = user_map[appt.user_id].full_name if appt.user_id in user_map else f"User #{appt.user_id}"
            print(f"  • Cita #{appt.id} | Contacto #{appt.contact_id} ({c_name}) | Asignado a: '{u_name}' (ID: {appt.user_id}) | Fecha: {appt.datetime} | Estado: {appt.status}")

        print("\n" + "=" * 70)
        print("🎯 RESUMEN DE IMPACTO PROYECTADO:")
        print(f"  1. Total contactos en CRM: {total_contacts}")
        print(f"  2. Contactos que preservarán asesor (Manuales Liliana/Admin): {len(manually_assigned_contact_ids)}")
        print(f"  3. Contactos que pasarán a 'Sin Asignar' (assigned_user_id = NULL): {len(assigned_contacts) - len(manually_assigned_contact_ids)}")
        print("=" * 70)

        return {
            "total_contacts": total_contacts,
            "assigned_contacts": len(assigned_contacts),
            "manually_assigned_contact_ids": list(manually_assigned_contact_ids),
            "admin_user_ids": admin_user_ids,
            "liliana_user_ids": liliana_user_ids
        }
    finally:
        db.close()

if __name__ == "__main__":
    run_diagnosis()
