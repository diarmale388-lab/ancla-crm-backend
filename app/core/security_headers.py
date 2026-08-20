from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware defensivo que inyecta cabeceras HTTP de blindaje de grado bancario (Zero-Trust).
    Mitiga ataques de Clickjacking, MIME-Sniffing, XSS reflejado y restringe políticas de recursos.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        
        # 1. Anti-Clickjacking: Prohíbe embebido en iframes externos
        response.headers["X-Frame-Options"] = "DENY"
        
        # 2. Anti-MIME Sniffing: Fuerza al navegador a respetar los Content-Types declarados
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # 3. HSTS: Fuerza comunicación HTTPS estricta por 1 año con preload
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        
        # 4. Referrer Policy: Protege datos sensibles en URLs al navegar a orígenes externos
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # 5. Permissions Policy: Restringe acceso a APIs del navegador no necesarias
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        
        # 6. Legacy XSS Filter protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # 7. Content-Security-Policy (CSP)
        # Permite fuentes de Google Fonts, WebSockets internos y orígenes autorizados
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' ws: wss: https: http:; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp
        
        return response
