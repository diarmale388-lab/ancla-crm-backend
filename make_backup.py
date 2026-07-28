import sys, json, datetime, os
sys.path.append('c:/Users/diarm/Documents/Liliana Leon/CMR/backend')
from app.database import SessionLocal
from app.models.base import Contact, Message, Appointment, SystemSetting, KnowledgeChunk

sys.stdout.reconfigure(encoding='utf-8')
db = SessionLocal()

def generate_db_backup():
    now_str = datetime.datetime.now().strftime("%Y_%m_%d_%H%M%S")
    backup_filename = f"c:/Users/diarm/Documents/Liliana Leon/CMR/backend/backups/backup_db_{now_str}.json"
    os.makedirs("c:/Users/diarm/Documents/Liliana Leon/CMR/backend/backups", exist_ok=True)
    
    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "contacts": [],
        "messages": [],
        "appointments": [],
        "settings": []
    }
    
    # Export Contacts
    for c in db.query(Contact).all():
        data["contacts"].append({
            "id": c.id,
            "first_name": c.first_name,
            "last_name": c.last_name,
            "phone": c.phone,
            "email": c.email,
            "source": c.source,
            "qualification_notes": c.qualification_notes,
            "scheduling_state": c.scheduling_state,
            "proposed_datetime": c.proposed_datetime.isoformat() if c.proposed_datetime else None,
            "chatbot_enabled": c.chatbot_enabled,
            "created_at": c.created_at.isoformat() if c.created_at else None
        })
        
    # Export Messages
    for m in db.query(Message).all():
        data["messages"].append({
            "id": m.id,
            "contact_id": m.contact_id,
            "sender_type": m.sender_type.value if hasattr(m.sender_type, 'value') else str(m.sender_type),
            "channel": m.channel.value if hasattr(m.channel, 'value') else str(m.channel),
            "message_type": m.message_type.value if hasattr(m.message_type, 'value') else str(m.message_type),
            "content": m.content,
            "status": m.status.value if hasattr(m.status, 'value') else str(m.status),
            "created_at": m.created_at.isoformat() if m.created_at else None
        })

    # Export Appointments
    for a in db.query(Appointment).all():
        data["appointments"].append({
            "id": a.id,
            "contact_id": a.contact_id,
            "user_id": a.user_id,
            "datetime": a.datetime.isoformat() if a.datetime else None,
            "status": a.status,
            "notes": a.notes,
            "created_at": a.created_at.isoformat() if a.created_at else None
        })
        
    with open(backup_filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ RESPALDO DE SEGURIDAD EXPORTADO EXITOSAMENTE:")
    print(f"📁 Archivo: {backup_filename}")
    print(f"📊 Estadísticas: {len(data['contacts'])} Contactos | {len(data['messages'])} Mensajes | {len(data['appointments'])} Citas")

generate_db_backup()
