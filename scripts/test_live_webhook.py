import sys
import os
import asyncio
import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

async def test_meta_webhook():
    print("\n--- PROBANDO META WEBHOOK EN PRODUCCIÓN ---")
    url = "https://ancla-crm-backend-production.up.railway.app/api/v1/webhooks/whatsapp"
    
    # 1. Prueba de verificación GET (Meta Verification Challenge)
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "antigravity_verify_token_123",
        "hub.challenge": "1234567890"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res_get = await client.get(url, params=params)
            print(f"GET Hub Verification Status: {res_get.status_code}")
            print(f"GET Response: {res_get.text}")
        except Exception as e:
            print(f"Error en GET: {e}")

        # 2. Prueba de POST con mensaje simulado
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "1309006675619043",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "573021096069",
                            "phone_number_id": "1309006675619043"
                        },
                        "contacts": [{
                            "profile": {"name": "Diego Machado Test"},
                            "wa_id": "573177001670"
                        }],
                        "messages": [{
                            "from": "573177001670",
                            "id": "wamid.TEST_MANUAL_12345",
                            "timestamp": "1723136000",
                            "text": {"body": "Hola, prueba de webhook en vivo"},
                            "type": "text"
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }
        try:
            res_post = await client.post(url, json=payload)
            print(f"\nPOST Webhook Status: {res_post.status_code}")
            print(f"POST Response: {res_post.text}")
        except Exception as e:
            print(f"Error en POST: {e}")

if __name__ == "__main__":
    asyncio.run(test_meta_webhook())
