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
    """Escucha eventos globales en Redis y los redirige a los WebSockets locales."""
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis_client = None
        self.pubsub = None
        self.listener_task = None

    async def start(self):
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            self.pubsub = self.redis_client.pubsub()
            await self.pubsub.subscribe("crm_live_updates")
            self.listener_task = asyncio.create_task(self._listen())
            logger.info("Suscripción a Redis Pub/Sub activada exitosamente.")
        except Exception as e:
            logger.error(f"Error iniciando puente de Redis Pub/Sub: {e}")

    async def _listen(self):
        try:
            async for message in self.pubsub.listen():
                if message and message.get("type") == "message":
                    payload = json.loads(message["data"])
                    await self._route_payload(payload)
        except asyncio.CancelledError:
            logger.info("Hilo de escucha Redis Pub/Sub cancelado.")
        except Exception as e:
            logger.error(f"Fallo en el hilo de escucha Pub/Sub de Redis: {e}")
            await asyncio.sleep(5)
            asyncio.create_task(self.start())

    async def _route_payload(self, payload: dict):
        assigned_user_id = payload.get("assigned_user_id")
        if assigned_user_id is not None:
            await manager.send_to_user(int(assigned_user_id), payload)
        else:
            await manager.broadcast_to_all(payload)

    async def stop(self):
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
        if self.pubsub:
            await self.pubsub.unsubscribe("crm_live_updates")
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.close()
