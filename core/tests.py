from datetime import time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ConfiguracionVenta, Dia, Loteria, Venta


class ReporteDescargasTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='staff_reportes',
            password='segura123',
            is_staff=True,
        )
        self.valle = Loteria.objects.create(
            nombre='Valle',
            hora_inicio=time(8, 0),
            hora_fin=time(23, 0),
        )
        self.manizales = Loteria.objects.create(
            nombre='Manizales',
            hora_inicio=time(8, 0),
            hora_fin=time(23, 0),
        )

    def test_reporte_descargas_no_prorratea_monto_multi_loteria(self):
        venta = Venta.objects.create(
            vendedor=self.staff,
            numero='428',
            monto=1100,
            combi=None,
        )
        venta.loterias.set([self.valle, self.manizales])

        self.client.force_login(self.staff)
        response = self.client.get(
            reverse('reporte_descargas'),
            {'fecha': timezone.localdate().isoformat()},
        )

        self.assertEqual(response.status_code, 200)

        report_rows = list(response.context['report'])
        row_valle_428 = next(
            row for row in report_rows
            if row['loterias__nombre'] == 'Valle' and row['numero_clean'] == '428'
        )

        self.assertEqual(row_valle_428['veces_apostado'], 1)
        self.assertEqual(row_valle_428['total_ventas'], 1100)


class LimiteVentaPorNumeroTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='vendedor_limite',
            password='segura123',
        )
        self.client.force_login(self.user)

        dia_actual_en = timezone.localtime(timezone.now()).strftime('%A')
        dias_map = {
            'Monday': 'Lunes',
            'Tuesday': 'Martes',
            'Wednesday': 'Mi\u00e9rcoles',
            'Thursday': 'Jueves',
            'Friday': 'Viernes',
            'Saturday': 'S\u00e1bado',
            'Sunday': 'Domingo',
        }
        self.dia_actual = Dia.objects.create(nombre=dias_map[dia_actual_en])

        self.valle = Loteria.objects.create(
            nombre='Valle Limite',
            hora_inicio=time(0, 0),
            hora_fin=time(23, 59),
        )
        self.valle.dias_juego.add(self.dia_actual)
        self.manizales = Loteria.objects.create(
            nombre='Manizales Limite',
            hora_inicio=time(0, 0),
            hora_fin=time(23, 59),
        )
        self.manizales.dias_juego.add(self.dia_actual)

        ConfiguracionVenta.objects.create(
            limite_apuesta_por_numero=30000,
        )

    def _crear_venta_existente(self, numero, monto):
        venta = Venta.objects.create(
            vendedor=self.user,
            numero=numero,
            monto=monto,
            combi=None,
        )
        venta.loterias.set([self.valle])
        return venta

    def test_rechaza_si_supera_limite_global_por_numero(self):
        self._crear_venta_existente(numero='248', monto=20000)

        response = self.client.post(
            reverse('ventas'),
            data={
                'loterias': [str(self.valle.id)],
                'numero': ['248'],
                'monto': ['12000'],
                'combi': [''],
            },
        )

        self.assertEqual(response.status_code, 400, response.content.decode('utf-8', errors='ignore'))
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertIn('Se excedio el valor de apuesta para ese numero', payload['error'])

    def test_permite_venta_hasta_el_limite(self):
        self._crear_venta_existente(numero='248', monto=20000)

        response = self.client.post(
            reverse('ventas'),
            data={
                'loterias': [str(self.valle.id)],
                'numero': ['248'],
                'monto': ['10000'],
                'combi': [''],
            },
        )

        self.assertEqual(response.status_code, 201, response.content.decode('utf-8', errors='ignore'))
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(
            Venta.objects.filter(numero='248', loterias=self.valle).count(),
            2,
        )

    def test_permite_mismo_numero_en_otra_loteria(self):
        self._crear_venta_existente(numero='248', monto=30000)

        response = self.client.post(
            reverse('ventas'),
            data={
                'loterias': [str(self.manizales.id)],
                'numero': ['248'],
                'monto': ['5000'],
                'combi': [''],
            },
        )

        self.assertEqual(response.status_code, 201, response.content.decode('utf-8', errors='ignore'))
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(
            Venta.objects.filter(numero='248', loterias=self.manizales).count(),
            1,
        )
