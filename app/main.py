import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.core.socket_manager import manager
from app.database import engine, get_db
from sqlalchemy.orm import Session
from app.models.base import Base, User
from app.core.deps import get_current_user
from app.routers import auth, chats, webhooks, ai, meta_ads, pipeline, appointments, settings as settings_router, google_auth, analytics, broadcasts, proposals, sse, showroom, notifications
 
from contextlib import asynccontextmanager
from app.core.socket_manager import manager, RedisPubSubBridge

redis_bridge = RedisPubSubBridge(settings.REDIS_URL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crear tablas y ejecutar seed asíncronamente en el arranque para evitar bloquear el boot
    try:
        Base.metadata.create_all(bind=engine)
        from check_users import inspect_and_seed
        inspect_and_seed()
        try:
            from seed_from_backup import seed_data
            seed_data()
        except Exception as e_seed:
            print(f"Advertencia seeding backup: {e_seed}")
    except Exception as e_db:
        print(f"Advertencia en inicio de BD: {e_db}")
    
    # Iniciar poller automático de leads de Meta Ads en segundo plano
    try:
        from app.services.meta_lead_poller import poll_meta_leads_loop
        asyncio.create_task(poll_meta_leads_loop())
    except Exception as e_poller:
        print(f"Advertencia iniciando poller de leads: {e_poller}")

    # Iniciar monitor de SLA de 15 minutos en segundo plano
    try:
        from app.services.sla_monitor import sla_monitor_loop
        asyncio.create_task(sla_monitor_loop())
    except Exception as e_sla:
        print(f"Advertencia iniciando monitor SLA: {e_sla}")

    # Iniciar Background Worker de Recordatorios Automáticos Anti-No-Show (24h, 2h, 15m)
    try:
        from app.services.reminder_service import appointment_reminder_loop
        asyncio.create_task(appointment_reminder_loop())
    except Exception as e_reminder:
        print(f"Advertencia iniciando loop de recordatorios: {e_reminder}")

    await redis_bridge.start()
    yield
    await redis_bridge.stop()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="CRM Omnicanal con IA integrado con Meta Ads, WhatsApp y Pipeline Kanban.",
    version="1.0.0",
    lifespan=lifespan
)
 
# Configuración de CORS Blindado
ALLOWED_ORIGINS = [
    "https://anclaspecialprojects.com",
    "https://www.anclaspecialprojects.com",
    "https://ancla-crm-frontend.vercel.app",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|.*anclaspecialprojects\.com)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.core.security_headers import SecurityHeadersMiddleware
from app.core.audit_middleware import SecurityAuditMiddleware

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SecurityAuditMiddleware)

 
# Registrar Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(chats.router, prefix=settings.API_V1_STR)
app.include_router(webhooks.router, prefix=settings.API_V1_STR)
app.include_router(ai.router, prefix=settings.API_V1_STR)
app.include_router(meta_ads.router, prefix=settings.API_V1_STR)
app.include_router(pipeline.router, prefix=settings.API_V1_STR)
app.include_router(appointments.router, prefix=settings.API_V1_STR)
app.include_router(settings_router.router, prefix=settings.API_V1_STR)
app.include_router(google_auth.router, prefix=settings.API_V1_STR)
app.include_router(analytics.router, prefix=settings.API_V1_STR)
app.include_router(broadcasts.router, prefix=settings.API_V1_STR)
app.include_router(proposals.router, prefix=settings.API_V1_STR)
app.include_router(sse.router, prefix=settings.API_V1_STR)
app.include_router(notifications.router, prefix=settings.API_V1_STR)
app.include_router(showroom.router)

# Router dedicado para reconfirmacion de asistentes al Showroom
from app.routers import showroom_confirm
app.include_router(showroom_confirm.router, prefix=settings.API_V1_STR)

# Módulo de IA Autónomo Sofi AI (/ai_agent)
from ai_agent.router import router as ai_agent_router
app.include_router(ai_agent_router)


@app.get("/api/v1/public/audit-logs")
def get_public_audit_logs_root(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.services.audit_logger import audit_logs
    from sqlalchemy import text

    system_logs = list(audit_logs)
    try:
        sql = """
            SELECT a.id, a.trace_id, a.contact_id, a.timestamp, a.source, a.event_type, a.execution_path, a.payload, c.first_name, c.phone
            FROM event_audit_trail a
            LEFT JOIN contacts c ON a.contact_id = c.id
            ORDER BY a.id DESC LIMIT 50
        """
        db_rows = db.execute(text(sql)).fetchall()
        db_logs = []
        for r in reversed(db_rows):
            ts = r[3].strftime("%I:%M:%S %p") if r[3] else "00:00:00 AM"
            source = r[4] or "SYSTEM"
            event_type = r[5] or "INFO"
            exec_path = r[6] or "N/A"
            payload_str = str(r[7] or "")
            contact_str = f"Cliente #{r[2]} ({r[8] or ''} {r[9] or ''})".strip() if r[2] else "Sistema"
            level = "error" if "error" in event_type.lower() or "fail" in event_type.lower() else "success" if "success" in event_type.lower() or "send" in event_type.lower() else "info"
            msg_type = "ai" if "ai" in source.lower() else "webhook" if "webhook" in source.lower() or "meta" in source.lower() or "whatsapp" in source.lower() else "system"
            formatted_msg = f"🔎 [{source}] {contact_str} ➔ {event_type} | Código: {exec_path} | Metadatos: {payload_str[:160]}"
            db_logs.append({
                "id": r[0] + 100000,
                "timestamp": ts,
                "type": msg_type,
                "level": level,
                "message": formatted_msg
            })
        return system_logs + db_logs
    except Exception:
        return system_logs


@app.get("/")
def read_root():
    return {"message": f"Bienvenido al backend de {settings.PROJECT_NAME}"}

@app.get("/privacy")
@app.get("/politicadeprivacidad")
def read_privacy():
    return {"status": "ok", "policy": "Política de Privacidad de ANCLA Special Projects / CRM. Cumplimiento con Ley 1581 de Habeas Data y directivas de privacidad de Meta."}

@app.get("/terms")
@app.get("/condiciones")
def read_terms():
    return {"status": "ok", "terms": "Términos y Condiciones de Uso del servicio CRM Omnicanal de ANCLA Special Projects."}

@app.get("/data-deletion")
@app.get("/eliminacion-datos")
def read_data_deletion():
    return {"status": "ok", "instructions": "Para solicitar la eliminación de tus datos personales, por favor envía un correo a soporte@ancla.com especificando tu número de teléfono y nombre."}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None, user_id: int = None):
    # Validar token JWT si se proporciona
    if token:
        try:
            from jose import jwt
            from app.config import settings
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            uid = payload.get("sub")
            if uid:
                user_id = int(uid)
        except Exception:
            pass

    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            await websocket.send_json({"status": "received", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception:
        manager.disconnect(websocket, user_id)

