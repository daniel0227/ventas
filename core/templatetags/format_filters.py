# core/templatetags/format_filters.py
from django import template

register = template.Library()

@register.filter
def format_colombian(value):
    """
    Formatea un número entero con separador de miles usando puntos,
    sin decimales. Por ejemplo, 1000000 se mostrará como '1.000.000'.
    """
    try:
        # Convertir el valor a entero (redondeando si es necesario)
        value = int(round(float(value)))
    except (ValueError, TypeError):
        return value
    # Formatea usando la función format() y reemplaza las comas por puntos
    return format(value, ",d").replace(",", ".")
