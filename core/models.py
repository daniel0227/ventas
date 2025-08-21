from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.utils.timezone import now

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
    

class Venta(models.Model):
    vendedor = models.ForeignKey(User, on_delete=models.CASCADE)
    loterias = models.ManyToManyField(Loteria)
    fecha_venta = models.DateTimeField(auto_now_add=True, db_index=True)  # Agregado db_index=True para optimizar consultas
    numero = models.CharField(max_length=50, db_index=True)
    monto = models.IntegerField()  # Cambiado a IntegerField
    combi = models.IntegerField(null=True, blank=True)  # Cambiado a IntegerField

    def __str__(self):
        return f"{self.vendedor} - {self.numero} - {self.fecha_venta}"
    
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

    def __str__(self):
        return f"{self.loteria} - {self.fecha}: {self.resultado}"
    
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
    numero = models.CharField(max_length=10, db_index=True)      # número apostado
    valor = models.PositiveIntegerField()                         # valor apostado (monto)
    cifras = models.PositiveSmallIntegerField()                   # 2, 3 o 4
    premio = models.PositiveBigIntegerField()                     # valor del premio (payout)
    fecha = models.DateField(db_index=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        # Evita duplicados por el mismo día/venta/lotería
        constraints = [
            models.UniqueConstraint(
                fields=['venta', 'loteria', 'fecha'],
                name='uniq_premio_por_venta_loteria_fecha'
            )
        ]

    def __str__(self):
        return f'{self.fecha} • {self.loteria} • {self.vendedor} • {self.numero} = {self.premio}'