import sys, asyncio, datetime
sys.path.append('c:/Users/diarm/Documents/Liliana Leon/CMR/backend')
from app.database import SessionLocal
from app.models.base import Contact, Message, SenderType, ChannelType, MessageType, MessageStatus
from app.services.ai_engine import ai_engine
from app.services.whatsapp import whatsapp_service

sys.stdout.reconfigure(encoding='utf-8')
db = SessionLocal()

async def process_all_unreplied():
    print("=== AUDITORÍA Y RESPUESTA AUTOMÁTICA EN VIVO ===")
    
    # 1. Habilitar chatbot_enabled=True para contactos recientes que quedaron apagados
    recent_contacts = db.query(Contact).order_by(Contact.id.desc()).limit(50).all()
    for c in recent_contacts:
        if not c.chatbot_enabled:
            c.chatbot_enabled = True
            db.add(c)
            print(f"🔧 Chatbot REACTIVADO para ID {c.id} | {c.first_name} ({c.phone})")
    db.commit()
    
    # 2. Buscar contactos con mensajes pendientes de respuesta del cliente
    for c in recent_contacts:
        last_msg = db.query(Message).filter(
            Message.contact_id == c.id
        ).order_by(Message.created_at.desc()).first()
        
        if not last_msg:
            continue
            
        if last_msg.sender_type == SenderType.CONTACT:
            name_display = f"{c.first_name or ''} {c.last_name or ''}".strip() or "Cliente"
            print(f"\n📩 PROCESANDO ID {c.id} | {name_display} ({c.phone})")
            print(f"   Último mensaje recibido: {repr(last_msg.content[:80])}")
            
            # Generar respuesta de Sofi con el nuevo motor blindado
            reply_dict = await ai_engine.generate_autopilot_reply(db, c, last_msg.content)
            
            if reply_dict and "response" in reply_dict:
                reply_text = reply_dict["response"]
                print(f"   🤖 Sofi responde: {repr(reply_text[:80])}")
                
                # Enviar mensaje por WhatsApp API
                res = await whatsapp_service.send_text_message(
                    to_phone=c.phone,
                    message_text=reply_text,
                    db=db
                )
                print(f"   Meta API Status: {res}")
            else:
                print("   ⚠️ No se generó respuesta de IA.")

asyncio.run(process_all_unreplied())
print("\n=== ¡PROCESAMIENTO COMPLETO DE TODOS LOS CHATS PENDIENTES! ===")
