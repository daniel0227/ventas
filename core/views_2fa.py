"""
core/views_2fa.py
─────────────────
Vistas de autenticacion de dos factores (2FA / TOTP) para cuentas staff.

Flujo:
  • dos_factor_setup  → enrolamiento: muestra el QR, confirma el primer codigo,
                        crea el dispositivo TOTP y genera codigos de respaldo.
  • dos_factor_verify → en cada sesion nueva pide el codigo de 6 digitos
                        (acepta tambien un codigo de respaldo).

Depende de django-otp. El enforcement (a quien se le exige) lo decide
core.middleware.TwoFactorEnforceMiddleware segun settings.OTP_ENFORCE.
"""
import base64
import io

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from django_otp import login as otp_login
from django_otp import match_token, user_has_device
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice


def _qr_data_uri(data: str) -> str:
    """Genera un PNG (data URI) del provisioning URI otpauth:// para el QR."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _secret_base32(device: TOTPDevice) -> str:
    """Clave en base32 para ingreso manual en la app de autenticacion."""
    return base64.b32encode(bytes.fromhex(device.key)).decode().replace("=", "")


def _generar_codigos_respaldo(user, cantidad: int = 10):
    """(Re)genera los codigos de respaldo de un solo uso para el usuario."""
    device, _ = StaticDevice.objects.get_or_create(user=user, name="backup")
    device.token_set.all().delete()
    codigos = []
    for _ in range(cantidad):
        codigo = StaticToken.random_token()
        device.token_set.create(token=codigo)
        codigos.append(codigo)
    return codigos


@login_required
@require_http_methods(["GET", "POST"])
def dos_factor_setup(request):
    """Enrola un dispositivo TOTP para el usuario actual."""
    user = request.user

    # Si ya tiene un dispositivo confirmado, no re-enrolar a la ligera.
    if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
        messages.info(request, "Ya tienes la verificacion en dos pasos activada.")
        return redirect("home")

    # Reutiliza un dispositivo sin confirmar o crea uno nuevo.
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=False)

    if request.method == "POST":
        token = (request.POST.get("token") or "").strip().replace(" ", "")
        if device.verify_token(token):
            device.confirmed = True
            device.save()
            codigos_respaldo = _generar_codigos_respaldo(user)
            otp_login(request, device)  # marca la sesion como verificada
            return render(
                request,
                "core/2fa/setup_done.html",
                {"backup_codes": codigos_respaldo},
            )
        messages.error(
            request,
            "Codigo incorrecto. Revisa que la hora de tu telefono este sincronizada "
            "e intenta de nuevo.",
        )

    return render(
        request,
        "core/2fa/setup.html",
        {
            "qr_data_uri": _qr_data_uri(device.config_url),
            "secret": _secret_base32(device),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def dos_factor_verify(request):
    """Pide el codigo TOTP (o un codigo de respaldo) para verificar la sesion."""
    user = request.user
    if not user_has_device(user):
        return redirect("dos_factor_setup")

    if request.method == "POST":
        token = (request.POST.get("token") or "").strip().replace(" ", "")
        device = match_token(user, token)
        if device is not None:
            otp_login(request, device)  # sesion verificada
            return redirect("home")
        messages.error(request, "Codigo incorrecto o expirado. Intenta de nuevo.")

    return render(request, "core/2fa/verify.html", {})
