"""
scripts/simulate_pipeline.py
-----------------------------
Script de Simulación Local del Backend de Sofi AI.
Permite simular una conversación localmente sin depender de los webhooks de Meta.

Uso:
  .venv\\Scripts\\python.exe scripts/simulate_pipeline.py --phone "57300000000" --message "Hola, cuánto cuesta la Flex Home?"
"""

import sys
import os
import argparse
import asyncio
from datetime import datetime

# Forzar codificación UTF-8 en la salida de consola de Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Asegurar que el directorio 'backend' esté en sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, ".."))
if os.path.exists(os.path.join(backend_dir, "app")):
    sys.path.insert(0, backend_dir)
elif os.path.exists(os.path.join(script_dir, "app")):
    sys.path.insert(0, script_dir)

from app.database import SessionLocal
from app.models.base import Contact, Message, SenderType, ChannelType, MessageType, MessageStatus
from app.services.ai_engine import ai_engine


async def run_simulation(phone: str, message: str):
    print(f"\n========================================================")
    print(f"🚀 [SIMULADOR DE PIPELINE LOCAL SOFI AI]")
    print(f"========================================================")
    print(f"📱 Teléfono: {phone}")
    print(f"💬 Mensaje: '{message}'")
    print(f"========================================================\n")

    db = SessionLocal()
    try:
        # Step 1: Cargar o Crear Contacto
        print(f"[SIMULATION] Paso 1: Cargar/Crear contacto en base de datos PostgreSQL/SQLite...")
        clean_phone = "".join(filter(str.isdigit, str(phone)))
        contact = db.query(Contact).filter(
            (Contact.phone == clean_phone) |
            (Contact.phone == f"+{clean_phone}") |
            (Contact.phone == phone)
        ).first()

        if not contact:
            contact = Contact(
                phone=phone,
                first_name="Diego (Simulación)",
                last_name="Test",
                source="Simulador Local Terminal",
                chatbot_enabled=True,
                habeas_data_authorized=True
            )
            db.add(contact)
            db.commit()
            db.refresh(contact)
            print(f"[SIMULATION] ✅ Contacto CREADO ID #{contact.id} ({contact.phone}) | Chatbot Enabled: {contact.chatbot_enabled}")
        else:
            contact.chatbot_enabled = True
            db.add(contact)
            db.commit()
            print(f"[SIMULATION] ✅ Contacto ENCONTRADO ID #{contact.id} ({contact.phone}) | Chatbot Enabled: {contact.chatbot_enabled}")

        # Step 2: Guardar mensaje del usuario en DB
        print(f"\n[SIMULATION] Paso 2: Registrando mensaje del usuario en la tabla 'messages'...")
        user_msg = Message(
            contact_id=contact.id,
            sender_type=SenderType.CONTACT,
            channel=ChannelType.WHATSAPP,
            message_type=MessageType.TEXT,
            content=message,
            status=MessageStatus.DELIVERED,
            external_message_id=f"sim_{int(datetime.utcnow().timestamp())}"
        )
        db.add(user_msg)
        db.commit()
        db.refresh(user_msg)
        print(f"[SIMULATION] ✅ Mensaje usuario registrado con ID #{user_msg.id}")

        # Step 3: Invocar ai_engine
        print(f"\n[SIMULATION] Paso 3: Invocando motor autónomo de IA (ai_engine.generate_autopilot_reply)...")
        start_time = datetime.now()
        ai_reply = await ai_engine.generate_autopilot_reply(
            db=db,
            contact=contact,
            last_message=message
        )
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"[SIMULATION] ⏱️ Tiempo de respuesta de IA: {elapsed:.2f} segundos")

        if ai_reply:
            print(f"\n========================================================")
            print(f"🤖 [RESPUESTA GENERADA POR SOFI AI]:")
            print(f"========================================================")
            print(f"{ai_reply}")
            print(f"========================================================\n")

            # Guardar respuesta de la IA en DB
            ai_msg = Message(
                contact_id=contact.id,
                sender_type=SenderType.AI,
                channel=ChannelType.WHATSAPP,
                message_type=MessageType.TEXT,
                content=ai_reply,
                status=MessageStatus.SENT
            )
            db.add(ai_msg)
            db.commit()
            print(f"[SIMULATION] ✅ Respuesta de IA registrada en la base de datos con ID #{ai_msg.id}")
        else:
            print(f"\n❌ [SIMULATION ERROR]: El motor de IA retornó None.")

    except Exception as e:
        import traceback
        print(f"\n❌ [SIMULATION CRASH]: Excepción durante la simulación: {e}")
        print(traceback.format_exc())
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Simulador local de pipeline para Sofi AI.")
    parser.add_argument("--phone", type=str, default="57300000000", help="Número de teléfono para simular")
    parser.add_argument("--message", type=str, default="Hola, cuánto cuesta la Flex Home?", help="Mensaje entrante del cliente")
    args = parser.parse_args()

    asyncio.run(run_simulation(args.phone, args.message))


if __name__ == "__main__":
    main()
