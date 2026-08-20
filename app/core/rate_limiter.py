import time
import asyncio
from collections import defaultdict
from typing import Dict, List, Optional, Callable
from functools import wraps
from fastapi import Request, HTTPException, status

class InMemoryRateLimiter:
    """
    Limitador de tasa de alto rendimiento basado en ventana deslizante (Sliding Window Log).
    Mantiene los timestamps de peticiones por clave (IP o user_id) y limpia entradas expiradas automáticamente.
    """
    def __init__(self):
        self._records: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()

    async def _cleanup(self, now: float, max_age: float = 3600):
        # Limpieza periódica cada 10 minutos para evitar crecimiento de memoria
        if now - self._last_cleanup > 600:
            self._last_cleanup = now
            keys_to_remove = []
            for k, timestamps in self._records.items():
                self._records[k] = [t for t in timestamps if now - t < max_age]
                if not self._records[k]:
                    keys_to_remove.append(k)
            for k in keys_to_remove:
                self._records.pop(k, None)

    async def is_rate_limited(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """
        Evalúa si la clave ha excedido el límite.
        Retorna (is_limited: bool, retry_after: int)
        """
        now = time.time()
        async with self._lock:
            await self._cleanup(now, window_seconds * 2)
            timestamps = self._records[key]
            # Filtrar marcas de tiempo dentro de la ventana
            cutoff = now - window_seconds
            valid_timestamps = [t for t in timestamps if t > cutoff]
            self._records[key] = valid_timestamps

            if len(valid_timestamps) >= max_requests:
                oldest_in_window = valid_timestamps[0]
                retry_after = max(1, int(oldest_in_window + window_seconds - now))
                return True, retry_after

            # Registrar la petición actual
            self._records[key].append(now)
            return False, 0

# Instancia global singleton
limiter = InMemoryRateLimiter()

def get_client_ip(request: Request) -> str:
    """
    Extrae la IP real del cliente considerando proxies inversos (Cloudflare, Nginx, Railway).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Tomar la primera IP de la cadena (IP del cliente original)
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"

def rate_limit(max_requests: int = 10, window_seconds: int = 60, key_prefix: str = "rl"):
    """
    Decorador asíncrono para endpoints de FastAPI que aplica Rate Limiting por IP.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                for k, v in kwargs.items():
                    if isinstance(v, Request):
                        request = v
                        break

            if request:
                ip = get_client_ip(request)
                limiter_key = f"{key_prefix}:{ip}:{request.url.path}"
                is_limited, retry_after = await limiter.is_rate_limited(limiter_key, max_requests, window_seconds)
                if is_limited:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Límite de peticiones excedido. Por favor espera {retry_after} segundos.",
                        headers={"Retry-After": str(retry_after)}
                    )

            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)
        return wrapper
    return decorator
