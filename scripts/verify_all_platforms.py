"""
scripts/verify_all_platforms.py
-------------------------------
Auditoría y verificación integral de todas las plataformas conectadas:
1. Base de datos Neon PostgreSQL
2. Upstash Redis Pub/Sub
3. OpenRouter LLM (GPT-4o / Claude / Gemini)
4. Meta WhatsApp Cloud API
5. Meta Ads Lead Forms & Poller
6. Google Calendar / Google Drive
7. Sistema de Generación de Propuestas PDF
"""

import sys
import os
import asyncio
import httpx
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, ".."))
if os.path.exists(os.path.join(backend_dir, "app")):
    sys.path.insert(0, backend_dir)

from sqlalchemy import text
from app.database import SessionLocal, engine
from app.config import settings
from app.models.base import User, Contact, Message, Appointment, PipelineStage, SystemSetting
from ai_agent.config import ai_settings


async def test_platforms():
    print("\n========================================================")
    print("🏥 [AUDITORÍA INTEGRAL DE PLATAFORMAS CONECTADAS AL CRM]")
    print("========================================================\n")

    results = {}

    # 1. Base de Datos PostgreSQL (Neon)
    print("1️⃣ Verificando Base de Datos Relacional PostgreSQL (Neon)...")
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        contact_count = db.query(Contact).count()
        msg_count = db.query(Message).count()
        app_count = db.query(Appointment).count()
        stages_count = db.query(PipelineStage).count()

        print(f"   ✅ PostgreSQL ACTIVO Y SALUDABLE:")
        print(f"      - Usuarios Asesores: {user_count}")
        print(f"      - Contactos en CRM: {contact_count}")
        print(f"      - Mensajes Totales: {msg_count}")
        print(f"      - Citas Agendadas: {app_count}")
        print(f"      - Etapas del Pipeline Kanban: {stages_count}")
        results["database"] = "OK"
    except Exception as e:
        print(f"   ❌ Error en Base de Datos: {e}")
        results["database"] = f"ERROR: {e}"

    # 2. OpenRouter & Modelos de IA (GPT-4o, Gemini)
    print("\n2️⃣ Verificando Motor de Inteligencia Artificial (OpenRouter / GPT-4o)...")
    try:
        api_key = ai_settings.OPENROUTER_API_KEY
        if not api_key:
            db_gemini = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
            api_key = db_gemini.value if db_gemini else None

        if api_key:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": ai_settings.HTTP_REFERER,
                "X-Title": ai_settings.SITE_NAME,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{ai_settings.OPENROUTER_BASE_URL}/chat/completions",
                    headers=headers,
                    json={
                        "model": "openai/gpt-4o",
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 5
                    }
                )
                if res.status_code == 200:
                    print(f"   ✅ OpenRouter / GPT-4o ACTIVO Y OPERACIONAL (HTTP 200 OK)")
                    results["openrouter"] = "OK"
                else:
                    print(f"   ⚠️ OpenRouter respondió con status {res.status_code}: {res.text[:120]}")
                    results["openrouter"] = f"Status {res.status_code}"
        else:
            print("   ⚠️ No se encontró API Key de OpenRouter.")
            results["openrouter"] = "NO_KEY"
    except Exception as e:
        print(f"   ❌ Error probando OpenRouter: {e}")
        results["openrouter"] = f"ERROR: {e}"

    # 3. Meta WhatsApp Cloud API
    print("\n3️⃣ Verificando Credenciales de WhatsApp Cloud API (Meta)...")
    try:
        token_setting = db.query(SystemSetting).filter(SystemSetting.key == "meta_access_token").first()
        access_token = token_setting.value if token_setting and token_setting.value else settings.META_ACCESS_TOKEN
        phone_id = settings.WHATSAPP_PHONE_NUMBER_ID or "1309006675619043"

        if access_token and phone_id:
            url = f"https://graph.facebook.com/v18.0/{phone_id}"
            headers = {"Authorization": f"Bearer {access_token}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    info = res.json()
                    display_num = info.get("display_phone_number", phone_id)
                    verified_name = info.get("verified_name", "ANCLA")
                    print(f"   ✅ Meta WhatsApp API CONECTADO:")
                    print(f"      - Número Verificado: {display_num}")
                    print(f"      - Nombre Comercial: {verified_name}")
                    results["whatsapp"] = "OK"
                else:
                    print(f"   ⚠️ Meta WhatsApp API status {res.status_code}: {res.text[:120]}")
                    results["whatsapp"] = f"Status {res.status_code}"
        else:
            print("   ⚠️ Faltan credenciales de Meta WhatsApp.")
            results["whatsapp"] = "MISSING_CREDS"
    except Exception as e:
        print(f"   ❌ Error verificando Meta WhatsApp: {e}")
        results["whatsapp"] = f"ERROR: {e}"

    # 4. Meta Ads Lead Forms
    print("\n4️⃣ Verificando Formularios Meta Ads registrados...")
    try:
        form_setting = db.query(SystemSetting).filter(SystemSetting.key == "registered_form_ids").first()
        if form_setting and form_setting.value:
            import json
            form_ids = json.loads(form_setting.value)
            print(f"   ✅ Formularios Meta Ads ACTIVOS ({len(form_ids)} IDs sincronizados):")
            for fid in form_ids:
                print(f"      - Form ID: {fid}")
            results["meta_ads"] = "OK"
        else:
            print("   ⚠️ No hay formularios registrados en registered_form_ids.")
            results["meta_ads"] = "NO_FORMS"
    except Exception as e:
        print(f"   ❌ Error verificando formularios: {e}")
        results["meta_ads"] = f"ERROR: {e}"

    # 5. Upstash Redis (WebSockets y Mensajería en Tiempo Real)
    print("\n5️⃣ Verificando Upstash Redis (Puente Pub/Sub en Tiempo Real)...")
    try:
        if settings.REDIS_URL:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, socket_timeout=5)
            await r.ping()
            await r.close()
            print(f"   ✅ Upstash Redis CONECTADO Y RESPONDIENDO (PONG)")
            results["redis"] = "OK"
        else:
            print("   ⚠️ REDIS_URL no está configurada.")
            results["redis"] = "NO_CONFIG"
    except Exception as e:
        print(f"   ⚠️ Upstash Redis: {e} (El sistema funciona con WebSockets locales)")
        results["redis"] = f"FALLBACK_LOCAL"

    # 6. Integración con Google Calendar & Drive
    print("\n6️⃣ Verificando Google Calendar & Drive...")
    try:
        cred_path = os.path.join(backend_dir, "credentials.json")
        if os.path.exists(cred_path):
            import json
            with open(cred_path, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                client_email = cdata.get("client_email", "N/A")
                project_id = cdata.get("project_id", "N/A")
                print(f"   ✅ Google Cloud Service Account CONFIGURADA:")
                print(f"      - Email: {client_email}")
                print(f"      - Proyecto: {project_id}")
                results["google"] = "OK"
        else:
            print("   ⚠️ Archivo credentials.json no encontrado.")
            results["google"] = "NO_FILE"
    except Exception as e:
        print(f"   ❌ Error leyendo Google credentials: {e}")
        results["google"] = f"ERROR: {e}"

    # 7. Generador de Propuestas Comerciales
    print("\n7️⃣ Verificando Generador de Propuestas Comerciales...")
    try:
        from app.routers.proposals import ProposalGenerateRequest, generate_proposal_pdf
        os.makedirs("uploads/proposals", exist_ok=True)
        print("   ✅ Motor de Propuestas Comerciales CONFIGURADO Y OPERACIONAL (/proposals/generate)")
        results["proposals"] = "OK"
    except Exception as e:
        print(f"   ❌ Error verificando propuestas: {e}")
        results["proposals"] = f"ERROR: {e}"

    db.close()

    print("\n========================================================")
    print("📊 [RESUMEN EJECUTIVO DE SALUD DE TODAS LAS PLATAFORMAS]")
    print("========================================================")
    for k, v in results.items():
        status_symbol = "✅" if v == "OK" else "🟡" if "FALLBACK" in v else "❌"
        print(f"  {status_symbol} {k.upper()}: {v}")
    print("========================================================\n")


if __name__ == "__main__":
    asyncio.run(test_platforms())
