from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import (
    Loteria,
    Venta,
    VentaDescargue,
    Dia,
    DiaFestivo,
    Resultado,
    ResultadoAuditLog,
    Premio,
    VentaAuditLog,
    ConfiguracionVenta,
    LimiteVendedor,
    Abonado,
    JugadaAbonado,
    AbonadoApuesta,
    PersonaDescargue,
    ReglaDescargue,
)

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
    actions = ["delete_selected"]
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
            return ("vendedor", "fecha_venta", "numero", "es_combinado", "monto", "loterias")
        return ("vendedor", "fecha_venta", "numero", "es_combinado", "monto", "loterias_list")

    def get_readonly_fields(self, request, obj=None):
        # Se permite correccion por superadmin, pero se preserva la fecha de venta.
        if request.user.is_superuser:
            return ("fecha_venta",)
        return ("vendedor", "fecha_venta", "numero", "monto", "es_combinado", "loterias_list")

    def _attach_audit_context(self, request, obj):
        obj._audit_actor = request.user
        obj._audit_ip_address = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() if request.META.get("HTTP_X_FORWARDED_FOR") else request.META.get("REMOTE_ADDR")
        obj._audit_user_agent = request.META.get("HTTP_USER_AGENT", "")
        obj._audit_source = "admin"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_staff)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not (request.user and request.user.is_superuser):
            return {}
        return actions

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

    def delete_model(self, request, obj):
        if request.user and request.user.is_superuser:
            obj._allow_delete = True
            self._attach_audit_context(request, obj)
        return super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        if not (request.user and request.user.is_superuser):
            return

        for obj in queryset:
            obj._allow_delete = True
            self._attach_audit_context(request, obj)
            obj.delete()


@admin.register(VentaDescargue)
class VentaDescargueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "fecha_venta",
        "descargue",
        "loteria",
        "numero",
        "monto",
        "registrado_por",
    )
    list_filter = ("fecha_venta", "loteria", "descargue")
    search_fields = (
        "numero",
        "descargue__username",
        "descargue__first_name",
        "descargue__last_name",
        "registrado_por__username",
    )
    autocomplete_fields = ("descargue", "loteria", "registrado_por")
    list_select_related = ("descargue", "loteria", "registrado_por")

# --- Dia ---
@admin.register(Dia)
class DiaAdmin(admin.ModelAdmin):
    list_display = ("nombre", )
    search_fields = ("nombre", )


# --- Día Festivo ---
@admin.register(DiaFestivo)
class DiaFestivoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "descripcion")
    search_fields = ("descripcion",)
    ordering = ("fecha",)
    date_hierarchy = "fecha"

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff


# --- Resultado ---
@admin.register(Resultado)
class ResultadoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "loteria", "resultado", "registrado_por", "registrado_en")
    list_filter = ("fecha", "loteria")
    search_fields = ("loteria__nombre", "resultado")
    list_select_related = ("loteria", "registrado_por")

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return ("registrado_en",)
        return ("loteria", "fecha", "resultado", "registrado_por", "registrado_en")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def _ip(self, request):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "")

    def save_model(self, request, obj, form, change):
        obj._audit_actor = request.user
        obj._audit_ip_address = self._ip(request)
        obj._audit_source = "admin"
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        obj._audit_actor = request.user
        obj._audit_ip_address = self._ip(request)
        obj._audit_source = "admin"
        super().delete_model(request, obj)


@admin.register(ResultadoAuditLog)
class ResultadoAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "loteria", "fecha", "valor_anterior", "valor_nuevo", "actor", "source", "ip_address")
    list_filter = ("action", "fecha", "loteria")
    search_fields = ("loteria__nombre", "actor__username", "ip_address")
    list_select_related = ("loteria", "actor", "resultado")
    readonly_fields = (
        "created_at", "action", "loteria", "fecha",
        "valor_anterior", "valor_nuevo", "actor",
        "ip_address", "source", "resultado",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

# --- Premio ---
@admin.register(Premio)
class PremioAdmin(admin.ModelAdmin):
    date_hierarchy = "fecha"
    list_display = ("fecha", "loteria", "vendedor", "numero", "valor", "cifras", "premio", "es_combinado")
    list_filter = ("fecha", "loteria", "cifras")
    search_fields = ("numero", "vendedor__username", "vendedor__first_name", "vendedor__last_name")
    list_select_related = ("loteria", "vendedor", "venta")
    actions = ["delete_selected"]
    readonly_fields = (
        "fecha", "loteria", "vendedor", "venta", "venta_descargue",
        "numero", "valor", "cifras", "premio", "es_combinado",
        "creado_en", "actualizado_en",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("delete_selected", None)
        return actions


@admin.register(VentaAuditLog)
class VentaAuditLogAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("created_at", "event_type", "status", "venta_id", "actor", "ip_address")
    list_filter = ("status", "event_type")
    search_fields = ("venta_id", "actor__username", "ip_address")
    list_select_related = ("actor",)
    list_per_page = 50
    show_full_result_count = False
    readonly_fields = (
        "created_at", "event_type", "status", "venta", "actor",
        "message", "payload", "ip_address", "user_agent"
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
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


# --- Límite de vendedor ---
@admin.register(LimiteVendedor)
class LimiteVendedorAdmin(admin.ModelAdmin):
    list_display = ("usuario", "limite_diario_fmt", "activo", "actualizado_en")
    list_filter = ("activo",)
    search_fields = ("usuario__username", "usuario__first_name", "usuario__last_name")
    autocomplete_fields = ("usuario",)
    list_select_related = ("usuario",)
    readonly_fields = ("creado_en", "actualizado_en")
    fields = ("usuario", "limite_diario", "activo", "creado_en", "actualizado_en")

    @admin.display(description="Límite diario")
    def limite_diario_fmt(self, obj):
        if not obj.limite_diario:
            return "Sin límite"
        return f"${obj.limite_diario:,}".replace(",", ".")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser


# --- Abonados ---
class JugadaAbonadoInline(admin.TabularInline):
    model = JugadaAbonado
    extra = 0
    fields = ("numero", "monto", "es_combinado", "orden")


@admin.register(Abonado)
class AbonadoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "vendedor", "telefono", "activo", "actualizado_en")
    list_filter = ("activo",)
    search_fields = ("nombre", "vendedor__username", "telefono")
    autocomplete_fields = ("vendedor",)
    list_select_related = ("vendedor",)
    inlines = [JugadaAbonadoInline]


@admin.register(JugadaAbonado)
class JugadaAbonadoAdmin(admin.ModelAdmin):
    list_display = ("abonado", "numero", "monto", "es_combinado")
    search_fields = ("abonado__nombre", "numero")
    list_select_related = ("abonado",)


@admin.register(AbonadoApuesta)
class AbonadoApuestaAdmin(admin.ModelAdmin):
    date_hierarchy = "fecha"
    list_display = ("fecha", "abonado", "registrado_por", "total")
    list_filter = ("fecha",)
    search_fields = ("abonado__nombre", "registrado_por__username")
    list_select_related = ("abonado", "registrado_por")
    readonly_fields = ("creada_en",)


# --- Configuracion de descargues ---
class ReglaDescargueInline(admin.TabularInline):
    model = ReglaDescargue
    extra = 1
    fields = ("cifras", "monto_maximo")


@admin.register(PersonaDescargue)
class PersonaDescargueAdmin(admin.ModelAdmin):
    list_display = ("orden", "nombre", "telefono", "recibe_restante", "activo", "reglas_resumen")
    list_filter = ("activo", "recibe_restante")
    search_fields = ("nombre",)
    ordering = ("orden",)
    inlines = [ReglaDescargueInline]
    fields = ("orden", "nombre", "telefono", "recibe_restante", "activo")

    @admin.display(description="Reglas")
    def reglas_resumen(self, obj):
        partes = [
            f"{r.cifras}c → ${r.monto_maximo:,}".replace(",", ".")
            for r in obj.reglas.all()
        ]
        return " | ".join(partes) if partes else "—"

    def has_add_permission(self, request):
        return request.user.is_staff

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
