from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import Loteria, Venta, Dia, Resultado, Premio

User = get_user_model()

# --- Loteria ---
@admin.register(Loteria)
class LoteriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", )
    search_fields = ("nombre", )

# --- Venta ---
@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ("id", "fecha_venta", "vendedor", "numero", "monto")
    list_filter = ("fecha_venta", )
    # Muy importante para habilitar el autocomplete desde PremioAdmin
    search_fields = (
        "numero",
        "vendedor__username",
        "vendedor__first_name",
        "vendedor__last_name",
        "id",
    )
    list_select_related = ("vendedor", )

# --- Dia / Resultado (sin cambios relevantes) ---
@admin.register(Dia)
class DiaAdmin(admin.ModelAdmin):
    list_display = ("nombre", )
    search_fields = ("nombre", )

@admin.register(Resultado)
class ResultadoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "loteria", "resultado")
    list_filter = ("fecha", "loteria")
    search_fields = ("loteria__nombre", "resultado")
    list_select_related = ("loteria", )

# --- Premio ---
@admin.register(Premio)
class PremioAdmin(admin.ModelAdmin):
    date_hierarchy = "fecha"
    list_display = ("fecha", "loteria", "vendedor", "numero", "valor", "cifras", "premio")
    list_filter = ("fecha", "loteria", "cifras")
    search_fields = ("numero", "vendedor__username", "vendedor__first_name", "vendedor__last_name")

    # Clave: evita renderizar selects gigantes
    autocomplete_fields = ("vendedor", "loteria", "venta")
    # Si tuvieras problemas con el autocomplete de venta, cámbialo por raw_id:
    # raw_id_fields = ("venta",)

    list_select_related = ("loteria", "vendedor", "venta")

    # Opcional: limitar el queryset del autocomplete de Venta (ej. últimas 2 semanas)
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "venta":
            # ejemplo de filtro suave para no cargar millones de registros
            # from django.utils import timezone
            # from datetime import timedelta
            # hace_15 = timezone.now() - timedelta(days=15)
            # kwargs["queryset"] = Venta.objects.filter(fecha_venta__gte=hace_15).select_related("vendedor")
            kwargs["queryset"] = Venta.objects.all().select_related("vendedor")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
