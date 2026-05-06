from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import m2m_changed, pre_delete
from django.dispatch import receiver
from django.utils import timezone

# Create your models here.
class Dia(models.Model):
    nombre = models.CharField(max_length=10, unique=True)  # 'unique=True' asegura que no haya duplicados

    def __str__(self):
        return self.nombre

class Loteria(models.Model):
    nombre = models.CharField(max_length=100)
    slug     = models.SlugField(unique=True, null=True, blank=True, help_text="Coincide con el slug de la API")
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    dias_juego = models.ManyToManyField(Dia)  # Relación ManyToMany con el modelo Dia
    imagen = models.ImageField(upload_to='loterias/', null=True, blank=True)  # Imagen opcional

    def __str__(self):
        return self.nombre

    def esta_disponible_en(self, fecha_hora, cierre_buffer_segundos=0):
        """
        Valida disponibilidad usando hora del servidor y buffer de cierre opcional.
        """
        if fecha_hora is None:
            return False

        if timezone.is_naive(fecha_hora):
            fecha_hora = timezone.make_aware(fecha_hora, timezone.get_current_timezone())

        fecha_hora_local = timezone.localtime(fecha_hora)
        tz_actual = timezone.get_current_timezone()
        inicio_dt = timezone.make_aware(datetime.combine(fecha_hora_local.date(), self.hora_inicio), tz_actual)
        fin_dt = timezone.make_aware(datetime.combine(fecha_hora_local.date(), self.hora_fin), tz_actual)

        # Soporte defensivo si alguna loteria cruza medianoche.
        if fin_dt < inicio_dt:
            if fecha_hora_local >= inicio_dt:
                fin_dt = fin_dt + timedelta(days=1)
            else:
                inicio_dt = inicio_dt - timedelta(days=1)

        buffer_segundos = max(int(cierre_buffer_segundos or 0), 0)
        fin_efectivo = fin_dt - timedelta(seconds=buffer_segundos)
        return inicio_dt <= fecha_hora_local <= fin_efectivo
     

class DiaFestivo(models.Model):
    fecha = models.DateField(unique=True, verbose_name="Fecha")
    descripcion = models.CharField(max_length=200, blank=True, verbose_name="Descripción")

    class Meta:
        verbose_name = "Día Festivo"
        verbose_name_plural = "Días Festivos"
        ordering = ["fecha"]

    def __str__(self):
        base = self.fecha.strftime("%d/%m/%Y")
        return f"{base} — {self.descripcion}" if self.descripcion else base


class ConfiguracionVenta(models.Model):
    CLAVE_GLOBAL = "global"

    clave = models.CharField(max_length=20, unique=True, default=CLAVE_GLOBAL, editable=False)
    limite_apuesta_por_numero = models.PositiveIntegerField(
        default=0,
        help_text="Tope por numero y loteria para un dia. 0 desactiva el limite.",
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracion de venta"
        verbose_name_plural = "Configuracion de ventas"

    def save(self, *args, **kwargs):
        self.clave = self.CLAVE_GLOBAL
        result = super().save(*args, **kwargs)
        # Invalida el cache del limite para que la proxima consulta lea el valor actualizado
        from django.core.cache import cache
        cache.delete("config_venta_limite_por_numero")
        return result

    def __str__(self):
        if not self.limite_apuesta_por_numero:
            return "Configuracion de ventas (sin limite)"
        return f"Configuracion de ventas (limite {self.limite_apuesta_por_numero})"


class VentaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if not kwargs:
            return 0

        ids = list(self.values_list("id", flat=True)[:100])
        _safe_create_venta_audit_log(
            event_type=VentaAuditLog.EVENT_SALE_UPDATE_BLOCKED,
            status=VentaAuditLog.STATUS_BLOCKED,
            venta=None,
            actor=None,
            message="Intento de modificacion masiva bloqueado sobre ventas.",
            payload={"ids_preview": ids, "fields": sorted(list(kwargs.keys()))},
        )
        raise ValidationError("Las ventas son inmutables y no pueden modificarse.")

    def delete(self):
        ids = list(self.values_list("id", flat=True)[:100])
        _safe_create_venta_audit_log(
            event_type=VentaAuditLog.EVENT_SALE_DELETE_BLOCKED,
            status=VentaAuditLog.STATUS_BLOCKED,
            venta=None,
            actor=None,
            message="Intento de eliminacion masiva bloqueado sobre ventas.",
            payload={"ids_preview": ids},
        )
        raise ValidationError("Las ventas no se pueden eliminar.")


class VentaManager(models.Manager):
    def get_queryset(self):
        return VentaQuerySet(self.model, using=self._db)


class Venta(models.Model):
    objects = VentaManager()

    vendedor = models.ForeignKey(User, on_delete=models.CASCADE)
    loterias = models.ManyToManyField(Loteria)
    fecha_venta = models.DateTimeField(auto_now_add=True, db_index=True)  # Agregado db_index=True para optimizar consultas
    numero = models.CharField(max_length=50, db_index=True)
    monto = models.IntegerField()  # Cambiado a IntegerField
    es_combinado = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["vendedor"], name="venta_vendedor_idx"),
            models.Index(fields=["vendedor", "fecha_venta"], name="venta_vendedor_fecha_idx"),
        ]

    def __str__(self):
        return f"{self.vendedor} - {self.numero} - {self.fecha_venta}"

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values(
                "vendedor_id", "numero", "monto", "es_combinado", "fecha_venta"
            ).first()
            if original:
                cambios = {}
                if original["vendedor_id"] != self.vendedor_id:
                    cambios["vendedor_id"] = [original["vendedor_id"], self.vendedor_id]
                if original["numero"] != self.numero:
                    cambios["numero"] = [original["numero"], self.numero]
                if original["monto"] != self.monto:
                    cambios["monto"] = [original["monto"], self.monto]
                if original["es_combinado"] != self.es_combinado:
                    cambios["es_combinado"] = [original["es_combinado"], self.es_combinado]
                if str(original["fecha_venta"]) != str(self.fecha_venta):
                    cambios["fecha_venta"] = [str(original["fecha_venta"]), str(self.fecha_venta)]

                if cambios:
                    if getattr(self, "_allow_mutation", False):
                        _safe_create_venta_audit_log(
                            event_type=VentaAuditLog.EVENT_SALE_UPDATE_ALLOWED,
                            status=VentaAuditLog.STATUS_SUCCESS,
                            venta=self,
                            actor=getattr(self, "_audit_actor", None),
                            message="Modificacion de venta permitida por superadmin.",
                            payload={
                                "changes": cambios,
                                "source": getattr(self, "_audit_source", "unknown"),
                            },
                            ip_address=getattr(self, "_audit_ip_address", None),
                            user_agent=getattr(self, "_audit_user_agent", ""),
                        )
                    else:
                        _safe_create_venta_audit_log(
                            event_type=VentaAuditLog.EVENT_SALE_UPDATE_BLOCKED,
                            status=VentaAuditLog.STATUS_BLOCKED,
                            venta=self,
                            actor=getattr(self, "_audit_actor", None),
                            message="Intento de modificacion bloqueado: las ventas son inmutables.",
                            payload={"changes": cambios},
                            ip_address=getattr(self, "_audit_ip_address", None),
                            user_agent=getattr(self, "_audit_user_agent", ""),
                        )
                        raise ValidationError("Las ventas son inmutables y no pueden modificarse.")

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if not getattr(self, "_allow_delete", False):
            _safe_create_venta_audit_log(
                event_type=VentaAuditLog.EVENT_SALE_DELETE_BLOCKED,
                status=VentaAuditLog.STATUS_BLOCKED,
                venta=self,
                actor=None,
                message="Intento de eliminacion bloqueado: las ventas no se eliminan.",
                payload={},
            )
            raise ValidationError("Las ventas no se pueden eliminar.")
        return super().delete(*args, **kwargs)


class VentaDescargue(models.Model):
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ventas_descargue_registradas",
    )
    descargue = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ventas_descargue",
    )
    loteria = models.ForeignKey(
        "Loteria",
        on_delete=models.PROTECT,
        related_name="ventas_descargue",
    )
    fecha_venta = models.DateTimeField(auto_now_add=True, db_index=True)
    numero = models.CharField(max_length=50, db_index=True)
    monto = models.PositiveIntegerField()

    class Meta:
        ordering = ("-fecha_venta", "-id")
        verbose_name = "Venta de descargue"
        verbose_name_plural = "Ventas de descargues"

    def clean(self):
        if self.descargue_id and self.descargue and self.descargue.is_staff:
            raise ValidationError("El usuario descargue no puede ser administrador.")

    def __str__(self):
        return f"{self.descargue} - {self.numero} - {self.loteria} - {self.fecha_venta}"


class VentaAuditLog(models.Model):
    STATUS_INFO = "info"
    STATUS_SUCCESS = "success"
    STATUS_REJECTED = "rejected"
    STATUS_BLOCKED = "blocked"
    STATUS_ERROR = "error"

    STATUS_CHOICES = [
        (STATUS_INFO, "Info"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_BLOCKED, "Blocked"),
        (STATUS_ERROR, "Error"),
    ]

    EVENT_CREATE_ATTEMPT = "sale.create_attempt"
    EVENT_CREATE_SUCCESS = "sale.create_success"
    EVENT_CREATE_REJECTED = "sale.create_rejected"
    EVENT_CREATE_CLOSED = "sale.create_rejected_closed_lottery"
    EVENT_SALE_UPDATE_ALLOWED = "sale.update_allowed"
    EVENT_SALE_UPDATE_BLOCKED = "sale.update_blocked"
    EVENT_SALE_DELETE_BLOCKED = "sale.delete_blocked"
    EVENT_SALE_LOTTERIES_CHANGE_ALLOWED = "sale.lotteries_change_allowed"
    EVENT_SALE_LOTTERIES_CHANGE_BLOCKED = "sale.lotteries_change_blocked"

    EVENT_CHOICES = [
        (EVENT_CREATE_ATTEMPT, "Sale Create Attempt"),
        (EVENT_CREATE_SUCCESS, "Sale Create Success"),
        (EVENT_CREATE_REJECTED, "Sale Create Rejected"),
        (EVENT_CREATE_CLOSED, "Sale Create Rejected Closed Lottery"),
        (EVENT_SALE_UPDATE_ALLOWED, "Sale Update Allowed"),
        (EVENT_SALE_UPDATE_BLOCKED, "Sale Update Blocked"),
        (EVENT_SALE_DELETE_BLOCKED, "Sale Delete Blocked"),
        (EVENT_SALE_LOTTERIES_CHANGE_ALLOWED, "Sale Lotteries Change Allowed"),
        (EVENT_SALE_LOTTERIES_CHANGE_BLOCKED, "Sale Lotteries Change Blocked"),
    ]

    venta = models.ForeignKey("Venta", on_delete=models.SET_NULL, related_name="audit_logs", null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="venta_audit_logs", null=True, blank=True)
    event_type = models.CharField(max_length=64, choices=EVENT_CHOICES, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)
    message = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")
        verbose_name = "Log de auditoria de venta"
        verbose_name_plural = "Logs de auditoria de ventas"

    def __str__(self):
        venta_id = self.venta_id if self.venta_id else "-"
        return f"[{self.created_at}] {self.event_type} ({self.status}) venta={venta_id}"
     
class Resultado(models.Model):
    loteria = models.ForeignKey(Loteria, on_delete=models.CASCADE, related_name='resultados')
    fecha = models.DateField()
    resultado = models.PositiveIntegerField()
    registrado_por = models.ForeignKey(User, on_delete=models.CASCADE)
    registrado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('loteria', 'fecha')
        verbose_name = "Resultado de Lotería"
        verbose_name_plural = "Resultados de Loterías"

    def save(self, *args, **kwargs):
        is_creation = self.pk is None
        valor_anterior = None
        if not is_creation:
            prev = type(self).objects.filter(pk=self.pk).values("resultado").first()
            if prev:
                valor_anterior = prev["resultado"]

        super().save(*args, **kwargs)

        try:
            action = ResultadoAuditLog.ACTION_CREATE if is_creation else ResultadoAuditLog.ACTION_UPDATE
            if is_creation or (valor_anterior is not None and valor_anterior != self.resultado):
                ResultadoAuditLog.objects.create(
                    resultado=self,
                    loteria=self.loteria,
                    fecha=self.fecha,
                    action=action,
                    valor_anterior=valor_anterior,
                    valor_nuevo=self.resultado,
                    actor=getattr(self, "_audit_actor", None),
                    ip_address=getattr(self, "_audit_ip_address", None),
                    source=getattr(self, "_audit_source", ""),
                )
        except Exception:
            pass

    def __str__(self):
        return f"{self.loteria} - {self.fecha}: {self.resultado}"


class ResultadoAuditLog(models.Model):
    ACTION_CREATE = "resultado.create"
    ACTION_UPDATE = "resultado.update"
    ACTION_DELETE = "resultado.delete"

    ACTION_CHOICES = [
        (ACTION_CREATE, "Creado"),
        (ACTION_UPDATE, "Modificado"),
        (ACTION_DELETE, "Eliminado"),
    ]

    resultado = models.ForeignKey(
        "Resultado",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="audit_logs",
    )
    loteria = models.ForeignKey(
        "Loteria",
        on_delete=models.PROTECT,
        related_name="resultado_audit_logs",
    )
    fecha = models.DateField(db_index=True)
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    valor_anterior = models.PositiveIntegerField(null=True, blank=True)
    valor_nuevo = models.PositiveIntegerField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="resultado_audit_logs",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    source = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Log de auditoría de resultado"
        verbose_name_plural = "Logs de auditoría de resultados"

    def __str__(self):
        return f"[{self.created_at}] {self.action} | {self.loteria} {self.fecha} | {self.valor_anterior} → {self.valor_nuevo}"


class Premio(models.Model):
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='premios'
    )
    loteria = models.ForeignKey(
        'Loteria',
        on_delete=models.PROTECT,
        related_name='premios'
    )
    # Guardar la venta que originó el premio (útil para trazabilidad)
    venta = models.ForeignKey(
        'Venta',
        on_delete=models.CASCADE,
        related_name='premios',
        null=True, blank=True
    )
    venta_descargue = models.ForeignKey(
        'VentaDescargue',
        on_delete=models.CASCADE,
        related_name='premios',
        null=True, blank=True
    )
    numero = models.CharField(max_length=10, db_index=True)      # número apostado
    valor = models.PositiveIntegerField()                         # valor apostado (monto)
    cifras = models.PositiveSmallIntegerField()                   # 2, 3 o 4
    premio = models.PositiveBigIntegerField()                     # valor del premio (payout)
    es_combinado = models.BooleanField(default=False)             # True si el premio fue por modalidad combinado
    fecha = models.DateField(db_index=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["vendedor"], name="premio_vendedor_idx"),
            models.Index(fields=["vendedor", "fecha"], name="premio_vendedor_fecha_idx"),
        ]
        # Evita duplicados por el mismo día/venta/lotería
        constraints = [
            models.UniqueConstraint(
                fields=['venta', 'loteria', 'fecha'],
                name='uniq_premio_por_venta_loteria_fecha'
            ),
            models.UniqueConstraint(
                fields=['venta_descargue', 'loteria', 'fecha'],
                name='uniq_premio_por_descargue_loteria_fecha'
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(venta__isnull=False)
                        & models.Q(venta_descargue__isnull=True)
                    )
                    | (
                        models.Q(venta__isnull=True)
                        & models.Q(venta_descargue__isnull=False)
                    )
                ),
                name='premio_con_una_sola_fuente'
            ),
        ]

    def __str__(self):
        return f'{self.fecha} • {self.loteria} • {self.vendedor} • {self.numero} = {self.premio}'
class Notificacion(models.Model):
    TIPO_INFO = "info"
    TIPO_EXITO = "exito"
    TIPO_ALERTA = "alerta"
    TIPO_ERROR = "error"

    TIPO_CHOICES = [
        (TIPO_INFO, "Información"),
        (TIPO_EXITO, "Éxito"),
        (TIPO_ALERTA, "Alerta"),
        (TIPO_ERROR, "Error"),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notificaciones",
    )
    titulo = models.CharField(max_length=200)
    mensaje = models.TextField(blank=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default=TIPO_INFO)
    leida = models.BooleanField(default=False, db_index=True)
    url = models.CharField(max_length=300, blank=True, help_text="URL opcional para redirigir al hacer click")
    creada_en = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-creada_en",)
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"

    def __str__(self):
        return f"[{self.tipo}] {self.titulo} → {self.usuario}"

    @classmethod
    def crear(cls, usuario, titulo, mensaje="", tipo=None, url=""):
        """Crea una notificación y la guarda. Útil para llamadas desde views/signals."""
        return cls.objects.create(
            usuario=usuario,
            titulo=titulo,
            mensaje=mensaje,
            tipo=tipo or cls.TIPO_INFO,
            url=url,
        )


class Abonado(models.Model):
    """Cliente frecuente perteneciente a un vendedor."""
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="abonados",
    )
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30, blank=True)
    activo = models.BooleanField(default=True, db_index=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("nombre",)
        verbose_name = "Abonado"
        verbose_name_plural = "Abonados"
        constraints = [
            models.UniqueConstraint(
                fields=["vendedor", "nombre"],
                name="uniq_abonado_por_vendedor_nombre",
            ),
        ]
        indexes = [
            models.Index(fields=["vendedor", "activo"], name="abonado_vendedor_activo_idx"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.vendedor})"


class JugadaAbonado(models.Model):
    """Plantilla de jugada guardada para un abonado."""
    abonado = models.ForeignKey(
        Abonado,
        on_delete=models.CASCADE,
        related_name="jugadas",
    )
    numero = models.CharField(max_length=4)
    monto = models.PositiveIntegerField()
    es_combinado = models.BooleanField(default=False)
    orden = models.PositiveSmallIntegerField(default=0)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("orden", "id")
        verbose_name = "Jugada de abonado"
        verbose_name_plural = "Jugadas de abonado"

    def __str__(self):
        return f"{self.abonado.nombre} - {self.numero} (${self.monto})"


class AbonadoApuesta(models.Model):
    """Registro historico de apuestas realizadas para un abonado."""
    abonado = models.ForeignKey(
        Abonado,
        on_delete=models.CASCADE,
        related_name="apuestas",
    )
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="apuestas_abonados",
    )
    ventas = models.ManyToManyField(
        "Venta",
        related_name="apuestas_abonado",
        blank=True,
    )
    fecha = models.DateField(db_index=True)
    total = models.PositiveBigIntegerField(default=0)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-fecha", "-id")
        verbose_name = "Apuesta de abonado"
        verbose_name_plural = "Apuestas de abonados"
        indexes = [
            models.Index(fields=["abonado", "fecha"], name="abonado_apuesta_fecha_idx"),
        ]

    def __str__(self):
        return f"{self.abonado.nombre} - {self.fecha} - ${self.total:,}"


def _safe_create_venta_audit_log(
    event_type,
    status,
    venta=None,
    actor=None,
    message="",
    payload=None,
    ip_address=None,
    user_agent="",
):
    """
    Registra auditoria sin interrumpir la operacion principal en caso de error.
    """
    try:
        VentaAuditLog.objects.create(
            venta=venta if getattr(venta, "pk", None) else None,
            actor=actor if getattr(actor, "pk", None) else None,
            event_type=event_type,
            status=status,
            message=(message or "")[:255],
            payload=payload or {},
            ip_address=ip_address,
            user_agent=user_agent or "",
        )
    except Exception:
        pass


@receiver(m2m_changed, sender=Venta.loterias.through)
def bloquear_cambios_loterias_en_venta(sender, instance, action, **kwargs):
    if action not in ("pre_add", "pre_remove", "pre_clear"):
        return

    if not getattr(instance, "pk", None):
        return

    relaciones_existentes = sender.objects.filter(venta_id=instance.pk).exists()

    if action == "pre_add" and not relaciones_existentes:
        # Alta inicial de loterias durante la creacion de la venta.
        return

    if getattr(instance, "_allow_loterias_assignment", False):
        _safe_create_venta_audit_log(
            event_type=VentaAuditLog.EVENT_SALE_LOTTERIES_CHANGE_ALLOWED,
            status=VentaAuditLog.STATUS_SUCCESS,
            venta=instance,
            actor=getattr(instance, "_audit_actor", None),
            message="Cambio de loterias permitido por superadmin.",
            payload={
                "action": action,
                "pk_set": sorted(list(kwargs.get("pk_set") or [])),
                "source": getattr(instance, "_audit_source", "unknown"),
            },
            ip_address=getattr(instance, "_audit_ip_address", None),
            user_agent=getattr(instance, "_audit_user_agent", ""),
        )
        return

    _safe_create_venta_audit_log(
        event_type=VentaAuditLog.EVENT_SALE_LOTTERIES_CHANGE_BLOCKED,
        status=VentaAuditLog.STATUS_BLOCKED,
        venta=instance,
        actor=getattr(instance, "_audit_actor", None),
        message="Intento de modificar loterias de una venta bloqueado.",
        payload={"action": action, "pk_set": sorted(list(kwargs.get("pk_set") or []))},
        ip_address=getattr(instance, "_audit_ip_address", None),
        user_agent=getattr(instance, "_audit_user_agent", ""),
    )
    raise ValidationError("No se pueden modificar las loterias de una venta.")


@receiver(pre_delete, sender=Venta)
def bloquear_eliminacion_venta(sender, instance, using, **kwargs):
    if getattr(instance, "_allow_delete", False):
        return

    _safe_create_venta_audit_log(
        event_type=VentaAuditLog.EVENT_SALE_DELETE_BLOCKED,
        status=VentaAuditLog.STATUS_BLOCKED,
        venta=instance,
        actor=None,
        message="Intento de eliminacion bloqueado por señal pre_delete.",
        payload={"using": using},
    )
    raise ValidationError("Las ventas no se pueden eliminar.")


@receiver(pre_delete, sender=Resultado)
def log_resultado_eliminacion(sender, instance, **_):
    try:
        ResultadoAuditLog.objects.create(
            resultado=None,
            loteria=instance.loteria,
            fecha=instance.fecha,
            action=ResultadoAuditLog.ACTION_DELETE,
            valor_anterior=instance.resultado,
            valor_nuevo=None,
            actor=getattr(instance, "_audit_actor", None),
            ip_address=getattr(instance, "_audit_ip_address", None),
            source=getattr(instance, "_audit_source", ""),
        )
    except Exception:
        pass
