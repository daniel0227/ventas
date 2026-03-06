from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import Loteria, Venta, Dia, Resultado, Premio, VentaAuditLog, ConfiguracionVenta

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
    actions = None
    # Muy importante para habilitar el autocomplete desde PremioAdmin
    search_fields = (
        "numero",
        "vendedor__username",
        "vendedor__first_name",
        "vendedor__last_name",
        "id",
    )
    list_select_related = ("vendedor", )

    def loterias_list(self, obj):
        if not obj.pk:
            return "-"
        return ", ".join(obj.loterias.values_list("nombre", flat=True))
    loterias_list.short_description = "Loterias"

    def get_fields(self, request, obj=None):
        if request.user.is_superuser:
            return ("vendedor", "fecha_venta", "numero", "combi", "monto", "loterias")
        return ("vendedor", "fecha_venta", "numero", "combi", "monto", "loterias_list")

    def get_readonly_fields(self, request, obj=None):
        # Se permite correccion por superadmin, pero se preserva la fecha de venta.
        if request.user.is_superuser:
            return ("fecha_venta",)
        return ("vendedor", "fecha_venta", "numero", "monto", "combi", "loterias_list")

    def _attach_audit_context(self, request, obj):
        obj._audit_actor = request.user
        obj._audit_ip_address = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() if request.META.get("HTTP_X_FORWARDED_FOR") else request.META.get("REMOTE_ADDR")
        obj._audit_user_agent = request.META.get("HTTP_USER_AGENT", "")
        obj._audit_source = "admin"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_staff)

    def save_model(self, request, obj, form, change):
        if change and request.user.is_superuser:
            obj._allow_mutation = True
            self._attach_audit_context(request, obj)
        return super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        if change and request.user.is_superuser:
            form.instance._allow_loterias_assignment = True
            self._attach_audit_context(request, form.instance)
        return super().save_related(request, form, formsets, change)

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


@admin.register(VentaAuditLog)
class VentaAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "status", "venta", "actor", "ip_address")
    list_filter = ("status", "event_type", "created_at")
    search_fields = ("message", "venta__id", "actor__username", "ip_address")
    readonly_fields = (
        "created_at", "event_type", "status", "venta", "actor",
        "message", "payload", "ip_address", "user_agent"
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Permite abrir el detalle en modo solo lectura.
        return True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfiguracionVenta)
class ConfiguracionVentaAdmin(admin.ModelAdmin):
    list_display = ("limite_apuesta_por_numero", "actualizado_en")
    fields = ("limite_apuesta_por_numero", "actualizado_en")
    readonly_fields = ("actualizado_en",)

    def has_add_permission(self, request):
        return not ConfiguracionVenta.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
