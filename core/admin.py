from django.contrib import admin
from .models import Loteria, Venta, Dia, Resultado

# Register your models here.
admin.site.register(Loteria)
admin.site.register(Venta)
admin.site.register(Dia)
admin.site.register(Resultado)