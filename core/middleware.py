"""
core/middleware.py
──────────────────
Middleware de auditoría de actividad de usuarios.
Registra cada request autenticado en el logger 'lottia.activity' usando el
sistema de logging estándar de Python — sin overhead de BD por request.

Los logs pueden redirigirse a un archivo, sentry, o cualquier handler
configurado en LOGGING de settings.py.
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
    # Estilos: propios + Bootstrap Icons (jsdelivr) + Google Fonts
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
    # Scripts: propios + Moment.js CDN + GitHub buttons
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://buttons.github.io https://cdn.jsdelivr.net",
    # Fuentes: propias + Bootstrap Icons (jsdelivr) + Google Fonts (gstatic)
    "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com",
    # Imágenes: propias + data URIs
    "img-src 'self' data:",
    # Conexiones fetch/XHR: origen propio + cdnjs
    "connect-src 'self' https://cdnjs.cloudflare.com",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])


class ContentSecurityPolicyMiddleware:
    """
    Inyecta la cabecera Content-Security-Policy en todas las respuestas HTML.
    No interfiere con descargas CSV/XLSX ni respuestas JSON.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = response.get("Content-Type", "")
        if "text/html" in content_type:
            response["Content-Security-Policy"] = _CSP_DIRECTIVES
        return response


# ---------------------------------------------------------------------------
# Enforcement de 2FA para cuentas staff/superuser
# ---------------------------------------------------------------------------
from django.conf import settings as _settings
from django.shortcuts import redirect


class TwoFactorEnforceMiddleware:
    """
    Exige segundo factor (TOTP) verificado a usuarios staff/superuser cuando
    settings.OTP_ENFORCE es True.

    - Los vendedores normales (no staff) NUNCA se ven afectados.
    - Si el staff aun no tiene dispositivo -> lo manda a enrolarse (/2fa/setup/).
    - Si lo tiene pero la sesion no esta verificada -> a /2fa/verify/.
    Depende de django_otp.middleware.OTPMiddleware (debe ir antes en MIDDLEWARE),
    que provee request.user.is_verified().
    """

    # Prefijos accesibles sin estar verificado (enrolar/verificar/salir/estaticos)
    _EXEMPT_PREFIXES = (
        "/2fa/",
        "/login/",
        "/logout/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._needs_2fa(request):
            from django_otp import user_has_device
            if user_has_device(request.user):
                return redirect("dos_factor_verify")
            return redirect("dos_factor_setup")
        return self.get_response(request)

    @staticmethod
    def _needs_2fa(request) -> bool:
        if not getattr(_settings, "OTP_ENFORCE", False):
            return False
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if not user.is_staff:           # vendedores normales: jamas
            return False
        # is_verified() lo agrega OTPMiddleware; si falta, asumimos no verificado
        if hasattr(user, "is_verified") and user.is_verified():
            return False
        return not any(request.path.startswith(p) for p in self._EXEMPT_PREFIXES)
