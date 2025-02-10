from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now

# Create your models here.
class Dia(models.Model):
    nombre = models.CharField(max_length=10, unique=True)  # 'unique=True' asegura que no haya duplicados

    def __str__(self):
        return self.nombre

class Loteria(models.Model):
    nombre = models.CharField(max_length=100)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    dias_juego = models.ManyToManyField(Dia)  # Relación ManyToMany con el modelo Dia
    imagen = models.ImageField(upload_to='loterias/', null=True, blank=True)  # Imagen opcional

    def __str__(self):
        return self.nombre
    

class Venta(models.Model):
    vendedor = models.ForeignKey(User, on_delete=models.CASCADE)
    loterias = models.ManyToManyField(Loteria)
    fecha_venta = models.DateTimeField(auto_now_add=True)
    numero = models.CharField(max_length=50)
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