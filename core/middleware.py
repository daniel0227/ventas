"""
core/middleware.py
──────────────────
Middleware de auditoría de actividad de usuarios y Content Security Policy.

ActivityLogMiddleware:
    Registra cada request autenticado en el logger 'lottia.activity' usando el
    sistema de logging estándar de Python — sin overhead de BD por request.

ContentSecurityPolicyMiddleware:
    Añade la cabecera Content-Security-Policy a todas las respuestas HTML.
    Cubre las fuentes externas (CDNs) usadas en las plantillas.
"""
import logging
import time

activity_logger = logging.getLogger("lottia.activity")

# Rutas que no vale la pena auditar (assets, health checks, APIs de polling)
_SKIP_PATHS = frozenset([
    "/static/", "/media/", "/favicon.ico",
    "/api/notificaciones/count/",   # polling frecuente — omitir para no saturar logs
])

# Solo auditar métodos que mutan estado o son navegación significativa
_AUDIT_METHODS = frozenset(["GET", "POST", "PUT", "PATCH", "DELETE"])


def _should_skip(path: str) -> bool:
    return any(path.startswith(p) for p in _SKIP_PATHS)


class ActivityLogMiddleware:
    """
    Registra actividad de usuarios autenticados.
    Formato: [METHOD] /path/ → status_code | user=<username> | ip=<ip> | ms=<elapsed>
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        t0 = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if (
            request.user.is_authenticated
            and request.method in _AUDIT_METHODS
            and not _should_skip(request.path)
        ):
            ip = self._get_ip(request)
            activity_logger.info(
                "[%s] %s → %s | user=%s | ip=%s | ms=%d",
                request.method,
                request.path,
                response.status_code,
                request.user.username,
                ip,
                elapsed_ms,
            )

        return response

    @staticmethod
    def _get_ip(request) -> str:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "-")


# ---------------------------------------------------------------------------
# Content Security Policy
# ---------------------------------------------------------------------------
_CSP_DIRECTIVES = "; ".join([
    "default-src 'self'",
    # Estilos: propios + Bootstrap Icons (jsdelivr) + Google Fonts (importado desde volt.css)
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
    # Scripts: propios + Moment.js CDN + GitHub buttons
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://buttons.github.io",
    # Fuentes: propias + Bootstrap Icons (jsdelivr) + Inter via Google Fonts (gstatic)
    "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com",
    # Imágenes: propias + data URIs (avatares SVG inline)
    "img-src 'self' data:",
    # Conexiones fetch/XHR: origen propio + cdnjs (source maps de Moment.js en devtools)
    "connect-src 'self' https://cdnjs.cloudflare.com",
    # No se usan frames
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])


class ContentSecurityPolicyMiddleware:
    """
    Inyecta la cabecera Content-Security-Policy en todas las respuestas.
    Solo se aplica a respuestas HTML (text/html) para no interferir
    con descargas CSV/XLSX ni respuestas JSON.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = response.get("Content-Type", "")
        if "text/html" in content_type:
            response["Content-Security-Policy"] = _CSP_DIRECTIVES
        return response
