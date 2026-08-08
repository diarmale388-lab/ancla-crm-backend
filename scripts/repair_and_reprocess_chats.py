"""
scripts/repair_and_reprocess_chats.py
-------------------------------------
1. Elimina todos los mensajes de fallback de la base de datos para que los clientes no los vean.
2. Identifica los contactos recientes (Luis Alfonso, Carlos Gómez, William, Alberto, Clemencia, etc.).
3. Genera para cada uno la respuesta correcta, contextualizada e inteligente acorde con su formulario y última pregunta.
"""

import sys
import os
import asyncio

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, ".."))
if os.path.exists(os.path.join(backend_dir, "app")):
    sys.path.insert(0, backend_dir)

from sqlalchemy import text
from app.database import SessionLocal
from app.models.base import Contact, Message, SenderType, ChannelType, MessageType, MessageStatus
from app.services.ai_engine import ai_engine
from app.services.whatsapp import whatsapp_service


async def repair_and_reprocess():
    db = SessionLocal()
    print("\n========================================================")
    print("🧹 [PASO 1: ELIMINANDO MENSAJES ERRÓNEOS DE LA BD]")
    print("========================================================")

    # 1. Purgar cualquier mensaje con la frase de fallback
    try:
        deleted = db.query(Message).filter(
            Message.sender_type == SenderType.AI,
            Message.content.contains("¿En qué ciudad o municipio proyectas tu construcción?")
        ).delete(synchronize_session=False)
        db.commit()
        print(f"✅ Se eliminaron {deleted} mensajes erróneos de la base de datos.")
    except Exception as e:
        print(f"Aviso eliminando mensajes: {e}")
        db.rollback()

    # 2. Identificar contactos recientes que necesitan su respuesta correcta
    target_ids = [416, 417, 386, 384, 375, 458, 457, 456, 446, 454, 451, 434, 441]
    
    print("\n========================================================")
    print("🤖 [PASO 2: GENERANDO RESPUESTAS CORRECTAS Y CONTEXTUALES]")
    print("========================================================")

    for cid in target_ids:
        contact = db.query(Contact).filter(Contact.id == cid).first()
        if not contact:
            continue

        c_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        print(f"\n--- Procesando Contacto #{contact.id} ({c_name} | {contact.phone}) ---")

        # Obtener el último mensaje del contacto (o formulario)
        last_contact_msg = db.query(Message).filter(
            Message.contact_id == contact.id,
            Message.sender_type == SenderType.CONTACT
        ).order_by(Message.created_at.desc()).first()

        if not last_contact_msg:
            print("   Omitiendo: No tiene mensajes del usuario.")
            continue

        print(f"   Último mensaje recibido:\n   '{last_contact_msg.content[:140]}...'")

        # Generar respuesta contextual a través de Sofi AI (GPT-4o)
        ai_reply = await ai_engine.generate_autopilot_reply(
            db=db,
            contact=contact,
            last_message=last_contact_msg.content
        )

        if ai_reply:
            print(f"   🤖 Nueva respuesta generada por Sofi AI:")
            print(f"   '{ai_reply[:180]}...'")

            # Guardar en base de datos
            db_ai = Message(
                contact_id=contact.id,
                sender_type=SenderType.AI,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=ai_reply,
                status=MessageStatus.SENT
            )
            db.add(db_ai)
            db.commit()
            db.refresh(db_ai)
            print(f"   ✅ Mensaje registrado en BD con ID #{db_ai.id}")
        else:
            print("   ⚠️ La IA retornó None.")

    db.close()
    print("\n========================================================")
    print("✨ [PROCESO COMPLETADO EXITOSAMENTE]")
    print("========================================================\n")


if __name__ == "__main__":
    asyncio.run(repair_and_reprocess())
