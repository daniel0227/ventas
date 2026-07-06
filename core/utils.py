import requests
from datetime import date
from django.utils import timezone
from .models import Loteria, Resultado
from django.db.models import Sum, IntegerField
from django.db.models.functions import Coalesce

# ---------------------------------------------------------------------------
# Utilidades compartidas
# ---------------------------------------------------------------------------

_DIAS_EN_ES = {
    "Monday": "Lunes",
    "Tuesday": "Martes",
    "Wednesday": "Miércoles",
    "Thursday": "Jueves",
    "Friday": "Viernes",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}


def dia_es(fecha) -> str:
    """Retorna el nombre del dia de la semana en español para una fecha o datetime."""
    return _DIAS_EN_ES.get(fecha.strftime("%A"), "")


def total_monto(queryset) -> int:
    """Suma el campo 'monto' de un queryset de Venta/VentaDescargue. Retorna 0 si no hay registros."""
    return queryset.aggregate(
        t=Coalesce(Sum("monto"), 0, output_field=IntegerField())
    )["t"]


def validar_rango_fechas(start, end, max_dias: int = 93):
    """
    Valida que el rango (start, end) no supere max_dias.
    Retorna (ok: bool, mensaje: str).
    """
    if start and end and (end - start).days > max_dias:
        return False, f"El rango máximo permitido es {max_dias} días. Por favor ajusta las fechas."
    return True, ""

URL = "https://api-resultadosloterias.com/api/results/{fecha}"

def importar_resultados(fecha: date, user=None) -> dict:
    """Descarga y guarda los resultados para esa fecha."""
    try:
        r = requests.get(URL.format(fecha=fecha.isoformat()), timeout=10)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as exc:
        return {"error": str(exc)}

    resumen = {"importados": 0, "omitidos": 0, "errores": 0} 
    for item in data:
        slug   = item.get("slug")
        numero = str(item.get("result") or "").strip()

        if not slug or not numero:
            resumen["errores"] += 1
            continue

        # Solo dígitos y máximo 4 cifras: un resultado corrupto (letras,
        # series, 5+ cifras) dañaría el cálculo de premios.
        if not numero.isdigit() or len(numero) > 4:
            resumen["errores"] += 1
            continue

        lot = Loteria.objects.filter(slug=slug).first()
        if not lot:
            resumen["omitidos"] += 1
            continue

        try:
            obj = Resultado.objects.filter(loteria=lot, fecha=fecha).first()
            if obj:
                obj.resultado = int(numero)
                obj.registrado_por = user
            else:
                obj = Resultado(loteria=lot, fecha=fecha, resultado=int(numero), registrado_por=user)
            obj._audit_actor = user
            obj._audit_source = "import_api"
            obj.save()
            resumen["importados"] += 1
        except Exception as exc:
            resumen["errores"] += 1
    return resumen

def enviar_whatsapp_callmebot(mensaje, telefono, apikey):
    """
    Envía un mensaje de WhatsApp usando CallMeBot.
    """
    base_url = "https://api.callmebot.com/whatsapp.php"
    params = {
        "phone": telefono,
        "text": mensaje,
        "apikey": apikey
    }

    try:
        response = requests.get(base_url, params=params, timeout=10)
        if "Message Sent" in response.text:
            return {"status": "success", "response": response.text}
        else:
            return {"status": "fail", "response": response.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}