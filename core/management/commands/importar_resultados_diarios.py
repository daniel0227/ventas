from django.core.management.base import BaseCommand
from django.utils.timezone import localtime, now
from datetime import timedelta
from django.contrib.auth import get_user_model
from core.utils import importar_resultados

User = get_user_model()

class Command(BaseCommand):
    help = "Importa automáticamente los resultados del día anterior desde la API."

    def handle(self, *args, **kwargs):
        fecha_objetivo = localtime(now()).date() - timedelta(days=1)

        try:
            usuario = User.objects.get(username="daniel")
        except User.DoesNotExist:
            self.stderr.write("❌ El usuario 'daniel' no existe. Debes crearlo con createsuperuser.")
            return

        self.stdout.write(f"📦 Ejecutando importación del {fecha_objetivo}...")

        try:
            resumen = importar_resultados(fecha_objetivo, user=usuario)
        except Exception as e:
            self.stderr.write(f"❌ Error general durante la importación: {str(e)}")
            return

        self.stdout.write(
            f"✅ Importados: {resumen['importados']} "
            f"(omitidos: {resumen['omitidos']}, errores: {resumen['errores']})"
        )
