import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from app.core.rate_limiter import get_client_ip

logger = logging.getLogger("security_audit")

class SecurityAuditMiddleware(BaseHTTPMiddleware):
    """
    Middleware de Trazabilidad Inmutable (Zero-Trust) que audita cada petición entrante,
    capturando IP real, User-Agent, ruta, método, tiempo de respuesta y código de estado.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.time()
        client_ip = get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "Unknown")
        method = request.method
        path = request.url.path

        try:
            response = await call_next(request)
            elapsed_ms = (time.time() - start_time) * 1000
            status_code = response.status_code

            # Registrar endpoints de autenticación, administración, webhooks y fallos de seguridad
            is_security_path = any(p in path for p in ["/auth", "/settings", "/webhooks", "/ai", "/showroom", "/users"])
            if is_security_path or status_code >= 400:
                log_level = logging.WARNING if status_code in [401, 403, 429] else logging.ERROR if status_code >= 500 else logging.INFO
                logger.log(
                    log_level,
                    f"🛡️ [AUDIT] {method} {path} | IP: {client_ip} | Status: {status_code} | Latency: {elapsed_ms:.1f}ms | UA: {user_agent[:60]}"
                )

            return response
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f"🚨 [AUDIT_EXCEPTION] {method} {path} | IP: {client_ip} | Latency: {elapsed_ms:.1f}ms | Error: {str(e)} | UA: {user_agent[:60]}"
            )
            raise e
