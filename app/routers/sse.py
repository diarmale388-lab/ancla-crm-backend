import logging
import asyncio
import json
from typing import Dict, List, AsyncGenerator
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

logger = logging.getLogger("sse_router")
router = APIRouter(prefix="/sse", tags=["sse"])

class SSEManager:
    def __init__(self):
        # Mapea user_id a una lista de colas de eventos activas
        self.user_listeners: Dict[int, List[asyncio.Queue]] = {}
        # Oyentes globales de broadcast
        self.broadcast_listeners: List[asyncio.Queue] = []

    def subscribe(self, user_id: int = None) -> asyncio.Queue:
        q = asyncio.Queue()
        if user_id:
            if user_id not in self.user_listeners:
                self.user_listeners[user_id] = []
            self.user_listeners[user_id].append(q)
            logger.info(f"Usuario {user_id} suscrito a SSE.")
        else:
            self.broadcast_listeners.append(q)
            logger.info("Oyente anónimo suscrito a SSE.")
        return q

    def unsubscribe(self, q: asyncio.Queue, user_id: int = None):
        if user_id and user_id in self.user_listeners:
            if q in self.user_listeners[user_id]:
                self.user_listeners[user_id].remove(q)
            if not self.user_listeners[user_id]:
                del self.user_listeners[user_id]
            logger.info(f"Usuario {user_id} desuscrito de SSE.")
        else:
            if q in self.broadcast_listeners:
                self.broadcast_listeners.remove(q)
            logger.info("Oyente anónimo desuscrito de SSE.")

    async def send_personal_message(self, message: dict, user_id: int):
        """Envía un evento SSE solo a las conexiones de un asesor específico."""
        payload = json.dumps(message, default=str)
        if user_id in self.user_listeners:
            for q in self.user_listeners[user_id]:
                await q.put(payload)

    async def broadcast(self, message: dict):
        """Envía un evento SSE a todas las conexiones activas."""
        payload = json.dumps(message, default=str)
        # Enviar a todos los asesores autenticados
        for listener_list in self.user_listeners.values():
            for q in listener_list:
                await q.put(payload)
        # Enviar a oyentes anónimos/broadcast
        for q in self.broadcast_listeners:
            await q.put(payload)

sse_manager = SSEManager()

@router.get("/events")
async def sse_endpoint(request: Request, token: str = None):
    """
    Endpoint SSE central.
    Recibe el token como parámetro de consulta para autenticar al asesor conectado.
    """
    user_id = None
    if token:
        try:
            # Importar localmente para evitar dependencias circulares
            from app.core.security import decode_access_token
            payload = decode_access_token(token)
            user_id = int(payload.get("sub"))
        except Exception as err:
            logger.warning(f"Error al decodificar token SSE: {err}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido o expirado"
            )

    q = sse_manager.subscribe(user_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # Enviar mensaje inicial de conexión exitosa
            yield f"data: {json.dumps({'event': 'connected', 'user_id': user_id})}\n\n"
            
            while True:
                # Comprobar si el navegador cerró la conexión
                if await request.is_disconnected():
                    break
                try:
                    # Esperar evento con timeout de 1 segundo para verificar desconexión
                    message = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Ping para mantener viva la conexión HTTP (evita cortes de Render/proxies)
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            logger.info(f"Conexión SSE cancelada para usuario {user_id}")
        finally:
            sse_manager.unsubscribe(q, user_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Desactivar almacenamiento en caché en servidores como Nginx
        }
    )
