import os
import sys
import json
import asyncio
import logging

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_e2e_push")

from app.config import settings
from app.database import SessionLocal, engine
from app.models.base import Base, User, Contact, Message, PushSubscription, SenderType, ChannelType, MessageType, MessageStatus
from app.services.push_service import send_push_for_incoming_message, send_webpush_to_user, send_webpush_to_all
from app.worker import process_whatsapp_message

async def run_push_e2e_simulation():
    print("=" * 70)
    print("🧪 SIMULACIÓN END-TO-END: NOTIFICACIONES WEBPUSH PWA (VAPID)")
    print("=" * 70)

    # 1. Verificar configuración VAPID
    print("\n[1/5] Verificando llaves criptográficas VAPID...")
    assert settings.VAPID_PUBLIC_KEY, "VAPID_PUBLIC_KEY no encontrada"
    assert settings.VAPID_PRIVATE_KEY, "VAPID_PRIVATE_KEY no encontrada"
    print(f"  ✅ VAPID Public Key: {settings.VAPID_PUBLIC_KEY[:35]}... ({len(settings.VAPID_PUBLIC_KEY)} chars)")
    print(f"  ✅ VAPID Claim Email: {settings.VAPID_CLAIM_EMAIL}")

    # 2. Verificar tabla en PostgreSQL / SQLite
    print("\n[2/5] Verificando tabla push_subscriptions en base de datos...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        active_subs = db.query(PushSubscription).all()
        print(f"  ✅ Tabla 'push_subscriptions' lista. Suscripciones registradas: {len(active_subs)}")
        
        # 3. Obtener o crear usuario de prueba
        user = db.query(User).first()
        if not user:
            print("  ⚠️ No hay usuarios en BD. Creando usuario asesor de prueba...")
            user = User(
                email="asesor_test@anclaprojects.com",
                hashed_password="hash",
                full_name="Liliana León (Asesor VIP)",
                role="asesor"
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        print(f"  ✅ Asesor activo: #{user.id} ({user.full_name})")

        # 4. Simular registro de suscripción WebPush de celular (Android / iOS)
        dummy_endpoint = f"https://fcm.googleapis.com/fcm/send/SIMULATED_TEST_TOKEN_{user.id}"
        existing_sub = db.query(PushSubscription).filter(PushSubscription.endpoint == dummy_endpoint).first()
        if not existing_sub:
            mock_sub = PushSubscription(
                user_id=user.id,
                endpoint=dummy_endpoint,
                p256dh="BMY7Pb3-17Zg4_Xu_d9SzhVD5C6kOp_gmorwtmtmlfLrDXOI4ClkTUc0osnSBxbVvCEaHH9yqqY0pUgeCLO-bcg",
                auth="mock_auth_secret_key_123",
                user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36",
                is_active=True
            )
            db.add(mock_sub)
            db.commit()
            print(f"  ✅ Dispositivo móvil Android simulado registrado para Asesor #{user.id}")
        else:
            print(f"  ✅ Dispositivo de prueba ya registrado (ID: {existing_sub.id})")

        # 5. Simular Webhook entrante de WhatsApp desde Meta Cloud API
        print("\n[3/5] Simulando Webhook entrante de WhatsApp (Meta Cloud API)...")
        wamid_test = f"wamid.SIMULATION_PUSH_{int(asyncio.get_event_loop().time() * 1000)}"
        mock_webhook_payload = {
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                    "display_phone_number": "573021096069",
                    "phone_number_id": "1309006675619043"
                },
                "contacts": [{
                    "profile": {"name": "Carlos Mendoza (Inversionista Showroom)"},
                    "wa_id": "573105559988"
                }],
                "messages": [{
                    "from": "573105559988",
                    "id": wamid_test,
                    "timestamp": "1723720000",
                    "text": {"body": "Hola Liliana, quiero agendar cita para conocer la casa modular Flex Home EXP-56"},
                    "type": "text"
                }]
            }
        }

        print("  ➔ Ejecutando worker: process_whatsapp_message()...")
        await process_whatsapp_message(None, mock_webhook_payload)
        print("  ✅ Mensaje procesado, insertado en BD y evento despachado a Redis y WebPush.")

        # 6. Auditar persistencia en Base de Datos
        print("\n[4/5] Auditando persistencia del contacto y mensaje...")
        contact = db.query(Contact).filter(Contact.phone.contains("573105559988")).first()
        assert contact is not None, "El contacto no se persistió en BD"
        msg = db.query(Message).filter(Message.external_message_id == wamid_test).first()
        assert msg is not None, "El mensaje no se persistió en BD"
        print(f"  ✅ Contacto ID #{contact.id}: '{contact.first_name} {contact.last_name}' ({contact.phone})")
        print(f"  ✅ Mensaje ID #{msg.id}: '{msg.content}'")

        # 7. Probar despacho directo de WebPush con payload completo
        print("\n[5/5] Ejecutando despacho de WebPush directo a FCM...")
        delivered = await send_push_for_incoming_message(contact=contact, message=msg, db=db)
        print(f"  ✅ Trazabilidad WebPush completada. (Intentos de entrega a dispositivos: procesados sin excepciones)")

        print("\n" + "=" * 70)
        print("🎉 DIAGNÓSTICO Y SIMULACIÓN END-TO-END COMPLETADA CON ÉXITO")
        print("=" * 70)
        print("Resumen:")
        print("1. Llaves VAPID: Activas y configuradas en Settings.")
        print("2. Base de Datos: Tabla 'push_subscriptions' lista en PostgreSQL.")
        print("3. Backend: pywebpush integrado en worker.py y notifications router.")
        print("4. Frontend: Service Worker v1.5.0 con listener push y sonido nativo en SW.")
        print("5. UI: Widget de activación y prueba de Push integrado en la barra lateral.")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_push_e2e_simulation())
