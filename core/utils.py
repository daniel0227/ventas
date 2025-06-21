import requests
from datetime import date
from django.utils import timezone
from .models import Loteria, Resultado

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
        numero = item.get("result")

        if not slug or not numero:
            resumen["errores"] += 1
            continue

        lot = Loteria.objects.filter(slug=slug).first()
        if not lot:
            resumen["omitidos"] += 1
            continue

        Resultado.objects.update_or_create(
            loteria=lot,
            fecha=fecha,
            defaults={
                "resultado": int(numero),
                "registrado_por": user,
                "registrado_en": timezone.now(),
            },
        )
        resumen["importados"] += 1
    return resumen
