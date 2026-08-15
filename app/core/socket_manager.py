import asyncio
import json
import logging
import redis.asyncio as redis
from typing import Dict, Set, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Gestiona conexiones WebSocket locales de esta instancia de Uvicorn."""
    def __init__(self):
        # Mapea user_id a su conjunto de WebSockets activos
        self.active_connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info(f"Asesor {user_id} conectado por WebSocket. Conexiones activas: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"Asesor {user_id} desconectado de WebSocket.")

    async def send_to_user(self, user_id: int, message: dict):
        """Envía un mensaje directo a las conexiones de un asesor específico."""
        connections = self.active_connections.get(user_id, set())
        for connection in list(connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error enviando mensaje a asesor {user_id}: {e}")
                self.disconnect(connection, user_id)

    async def broadcast_to_all(self, message: dict):
        """Envía un mensaje a absolutamente todos los asesores conectados en esta instancia."""
        for user_id in list(self.active_connections.keys()):
            await self.send_to_user(user_id, message)

    async def broadcast(self, message: dict):
        """Difunde un mensaje a todos (alias de broadcast_to_all)."""
        await self.broadcast_to_all(message)

    async def send_personal_message(self, message: dict, user_id: int):
        """Envía un mensaje directo a un asesor específico (alias de send_to_user)."""
        await self.send_to_user(user_id, message)

manager = ConnectionManager()

class RedisPubSubBridge:
    """Escucha eventos globales en Redis (redis:// y rediss://) y los redirige a los WebSockets locales con tolerancia a fallos."""
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis_client = None
        self.pubsub = None
        self.listener_task = None
        self.is_connected = False

    async def start(self):
        if not self.redis_url or "dummy" in self.redis_url.lower():
            logger.info("REDIS_URL no configurada o dummy. Operando en modo local WebSocket puro.")
            return

        try:
            # Soporta esquemas redis:// y rediss:// (TLS) con timeout estricto para evitar bloqueo
            is_ssl = self.redis_url.startswith("rediss://")
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=3.0,
                socket_timeout=3.0,
                retry_on_timeout=True
            )
            # Ping de verificación rápida con timeout de 2.0s
            await asyncio.wait_for(self.redis_client.ping(), timeout=2.0)
            self.pubsub = self.redis_client.pubsub()
            await self.pubsub.subscribe("crm_live_updates")
            self.is_connected = True
            self.listener_task = asyncio.create_task(self._listen())
            logger.info("✅ Suscripción a Redis Pub/Sub (Railway / Upstash) activada exitosamente.")
        except Exception as e:
            self.is_connected = False
            logger.warning(f"⚠️ Redis Pub/Sub no disponible ({e}). Operando en modo memoria local WebSocket.")
            # Reintentar en segundo plano tras 15 segundos sin bloquear el arranque del backend
            asyncio.create_task(self._schedule_reconnect())

    async def _schedule_reconnect(self):
        await asyncio.sleep(15)
        if not self.is_connected:
            await self.start()

    async def _listen(self):
        try:
            async for message in self.pubsub.listen():
                if message and message.get("type") == "message":
                    try:
                        payload = json.loads(message["data"])
                        await self._route_payload(payload)
                    except Exception as parse_err:
                        logger.error(f"Error procesando carga útil de Redis: {parse_err}")
        except asyncio.CancelledError:
            logger.info("Hilo de escucha Redis Pub/Sub cancelado.")
        except Exception as e:
            self.is_connected = False
            logger.warning(f"⚠️ Caída en hilo de escucha Redis Pub/Sub: {e}. Programando reconexión...")
            await asyncio.sleep(10)
            asyncio.create_task(self.start())

    async def _route_payload(self, payload: dict):
        """
        Difunde el evento a TODOS los clientes conectados en la instancia local
        para que tanto administradores como asesores reciban la actualización en vivo.
        """
        try:
            await manager.broadcast_to_all(payload)
        except Exception as route_err:
            logger.error(f"Error enrutando payload de Redis a WebSockets locales: {route_err}")

    async def stop(self):
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
        if self.pubsub:
            try:
                await self.pubsub.unsubscribe("crm_live_updates")
                await self.pubsub.close()
            except Exception:
                pass
        if self.redis_client:
            try:
                await self.redis_client.close()
            except Exception:
                pass
        self.is_connected = False
