import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.core.socket_manager import manager
from app.database import engine
from app.models.base import Base
from app.routers import auth, chats, webhooks, ai, meta_ads, pipeline, appointments, settings as settings_router, google_auth, analytics, broadcasts, proposals, sse, showroom
 
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

    await redis_bridge.start()
    yield
    await redis_bridge.stop()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="CRM Omnicanal con IA integrado con Meta Ads, WhatsApp y Pipeline Kanban.",
    version="1.0.0",
    lifespan=lifespan
)
 
# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, restringir al dominio del frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
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
app.include_router(showroom.router)

# Router dedicado para reconfirmacion de asistentes al Showroom
from app.routers import showroom_confirm
app.include_router(showroom_confirm.router, prefix=settings.API_V1_STR)

# Módulo de IA Autónomo Sofi AI (/ai_agent)
from ai_agent.router import router as ai_agent_router
app.include_router(ai_agent_router)


@app.get("/api/v1/public/audit-logs")
def get_public_audit_logs_root(db: Session = Depends(get_db)):
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
async def websocket_endpoint(websocket: WebSocket, user_id: int = None):
    await manager.connect(websocket, user_id)
    try:
        while True:
            # Mantener conexión abierta y escuchar posibles mensajes entrantes desde el cliente
            data = await websocket.receive_json()
            # Opcional: procesar comandos en tiempo real enviados por el frontend
            # Por ejemplo: marcando chat como leído en tiempo real
            await websocket.send_json({"status": "received", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        manager.disconnect(websocket, user_id)
