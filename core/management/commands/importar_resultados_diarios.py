import os
from django.core.management.base import BaseCommand
from django.utils.timezone import localtime, now
from datetime import timedelta
from django.contrib.auth import get_user_model
from core.utils import importar_resultados, enviar_whatsapp_callmebot
from core.models import Resultado, Venta, Dia, Loteria

User = get_user_model()

class Command(BaseCommand):
    help = "Importa resultados y notifica por WhatsApp si hay o no premios."

    def handle(self, *args, **kwargs):
        fecha_objetivo = localtime(now()).date() - timedelta(days=1)

        from django.conf import settings as django_settings
        import_user = getattr(django_settings, "IMPORT_RESULT_USER", "daniel")
        try:
            usuario = User.objects.get(username=import_user)
        except User.DoesNotExist:
            self.stderr.write(f"❌ El usuario '{import_user}' no existe.")
            return

        self.stdout.write(f"📦 Ejecutando importación del {fecha_objetivo}...")

        try:
            resumen = importar_resultados(fecha_objetivo, user=usuario)
        except Exception as e:
            self.stderr.write(f"❌ Error durante la importación: {str(e)}")
            return

        self.stdout.write(
            f"✅ Importados: {resumen['importados']} "
            f"(omitidos: {resumen['omitidos']}, errores: {resumen['errores']})"
        )

        # Detectar premios
        dia_nombre = fecha_objetivo.strftime('%A')
        map_dia = {
            'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
            'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
        }
        try:
            dia_obj = Dia.objects.get(nombre=map_dia[dia_nombre])
        except Dia.DoesNotExist:
            self.stdout.write("⚠️ Día no registrado.")
            return

        loterias = Loteria.objects.filter(dias_juego=dia_obj)
        premios_detectados = []

        for lot in loterias:
            resultado = Resultado.objects.filter(loteria=lot, fecha=fecha_objetivo).first()
            if not resultado:
                continue
            numero_ganador = str(resultado.resultado).zfill(4)
            ventas = Venta.objects.filter(fecha_venta__date=fecha_objetivo, loterias=lot)

            for venta in ventas:
                jugado = venta.numero.strip()
                if len(jugado) in (2, 3, 4) and jugado == numero_ganador[-len(jugado):]:
                    mult = {2: 60, 3: 550, 4: 4500}.get(len(jugado), 0)
                    valor = venta.monto * mult
                    premios_detectados.append(
                        f"💥 {venta.vendedor} acertó con *{jugado}* en *{lot.nombre}*.\nGanancia: *${valor:,}* 🧨"
                    )

        # Crear el mensaje con tono divertido y emojis
        if premios_detectados:
            mensaje = (
                f"😬 *¡Tenemos premios!* 😬\n\n"
                f"📆 Fecha: {fecha_objetivo}\n"
                f"🚨 Se detectaron jugadas ganadoras:\n\n" +
                "\n\n".join(premios_detectados) +
                "\n\n💸 Ve preparando la billetera... que hoy toca pagar."
            )
        else:
            mensaje = (
                f"✅ *Sin novedades ni premios* ✅\n\n"
                f"📆 Fecha: {fecha_objetivo}\n"
                f"🔍 Se revisaron todas las ventas y *nadie acertó*.\n\n"
                f"🎉 Hoy no toca pagar. ¡Todo bajo control!"
            )

        # 📲 Lista de destinatarios — configurar en variable de entorno:
        # CALLMEBOT_RECIPIENTS=573002393652:2485881,573001212758:7858937
        raw = os.environ.get("CALLMEBOT_RECIPIENTS", "")
        destinatarios = []
        for entry in raw.split(","):
            parts = entry.strip().split(":")
            if len(parts) == 2 and parts[0] and parts[1]:
                destinatarios.append({"telefono": parts[0], "apikey": parts[1]})

        for d in destinatarios:
            respuesta = enviar_whatsapp_callmebot(
                mensaje=mensaje,
                telefono=d["telefono"],
                apikey=d["apikey"]
            )
            self.stdout.write(f"📤 Mensaje enviado a {d['telefono']} ➜ {respuesta}")
