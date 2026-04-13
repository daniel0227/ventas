from datetime import time

from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ConfiguracionVenta, Dia, Loteria, Venta, VentaDescargue


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


class FlujoDescarguesTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username='admin_descargues',
            password='segura123',
            is_staff=True,
        )
        self.descargue = User.objects.create_user(
            username='usuario_descargue',
            password='segura123',
        )
        self.vendedor = User.objects.create_user(
            username='vendedor_normal',
            password='segura123',
        )

        grupo_descargue, _ = Group.objects.get_or_create(name='descargue')
        grupo_descargue.user_set.add(self.descargue)

        dia_actual_en = timezone.localtime(timezone.now()).strftime('%A')
        dias_map = {
            'Monday': 'Lunes',
            'Tuesday': 'Martes',
            'Wednesday': 'Miércoles',
            'Thursday': 'Jueves',
            'Friday': 'Viernes',
            'Saturday': 'Sábado',
            'Sunday': 'Domingo',
        }
        self.dia_actual = Dia.objects.create(nombre=dias_map[dia_actual_en])
        self.loteria = Loteria.objects.create(
            nombre='Lotería Descargues',
            hora_inicio=time(0, 0),
            hora_fin=time(23, 59),
        )
        self.loteria.dias_juego.add(self.dia_actual)

    def test_admin_registra_venta_para_descargue(self):
        self.client.force_login(self.admin)
        hoy = timezone.localdate().isoformat()
        response = self.client.post(
            reverse('descargues'),
            data={
                'descargue': str(self.descargue.id),
                'loteria': str(self.loteria.id),
                'numero': '1234',
                'monto': '5000',
                'fecha_filtro': hoy,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(VentaDescargue.objects.count(), 1)
        venta = VentaDescargue.objects.first()
        self.assertEqual(venta.descargue, self.descargue)
        self.assertEqual(venta.registrado_por, self.admin)
        self.assertEqual(venta.loteria, self.loteria)
        self.assertEqual(venta.numero, '1234')
        self.assertEqual(venta.monto, 5000)

    def test_descargue_puede_ver_sus_ventas(self):
        VentaDescargue.objects.create(
            registrado_por=self.admin,
            descargue=self.descargue,
            loteria=self.loteria,
            numero='9876',
            monto=2400,
        )
        self.client.force_login(self.descargue)
        response = self.client.get(
            reverse('mis_descargues'),
            data={'start_date': timezone.localdate().isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        ventas = list(response.context['ventas'].object_list)
        self.assertEqual(len(ventas), 1)
        self.assertEqual(ventas[0].numero, '9876')

    def test_descargue_no_puede_registrar_venta_directa(self):
        self.client.force_login(self.descargue)
        response = self.client.post(reverse('ventas'), data={})

        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertIn('descargue', payload['error'])

    def test_vendedor_normal_no_tiene_acceso_a_mis_descargues(self):
        self.client.force_login(self.vendedor)
        response = self.client.get(reverse('mis_descargues'))

        self.assertEqual(response.status_code, 302)

    def test_admin_carga_ventas_masivas_para_descargue(self):
        self.client.force_login(self.admin)
        hoy = timezone.localdate().isoformat()

        response = self.client.post(
            reverse('descargues'),
            data={
                'accion': 'masiva',
                'descargue': str(self.descargue.id),
                'loteria': str(self.loteria.id),
                'jugadas_masivas': '1016 - 1500\n016 - 3500\n0914 - 1500',
                'fecha_filtro': hoy,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(VentaDescargue.objects.count(), 3)
        ventas = list(
            VentaDescargue.objects
            .filter(descargue=self.descargue, loteria=self.loteria)
            .order_by('id')
            .values_list('numero', 'monto')
        )
        self.assertEqual(
            ventas,
            [('1016', 1500), ('016', 3500), ('0914', 1500)],
        )

    def test_carga_masiva_invalida_no_crea_registros(self):
        self.client.force_login(self.admin)
        hoy = timezone.localdate().isoformat()

        response = self.client.post(
            reverse('descargues'),
            data={
                'accion': 'masiva',
                'descargue': str(self.descargue.id),
                'loteria': str(self.loteria.id),
                'jugadas_masivas': '1016 - 1500\nlinea invalida\n0914 - 1500',
                'fecha_filtro': hoy,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(VentaDescargue.objects.count(), 0)
        self.assertTrue(
            any('Línea 2' in error for error in response.context['bulk_errors'])
        )

    def test_premios_incluye_ventas_de_descargue_para_admin_y_descargue(self):
        fecha = timezone.localdate()
        VentaDescargue.objects.create(
            registrado_por=self.admin,
            descargue=self.descargue,
            loteria=self.loteria,
            numero='111',
            monto=500,
        )
        from core.models import Resultado, Premio

        Resultado.objects.create(
            loteria=self.loteria,
            fecha=fecha,
            resultado=111,
            registrado_por=self.admin,
        )

        self.client.force_login(self.admin)
        response_admin = self.client.get(
            reverse('premios'),
            data={'fecha': fecha.isoformat()},
        )
        self.assertEqual(response_admin.status_code, 200)
        self.assertEqual(Premio.objects.count(), 1)
        premio = Premio.objects.get()
        self.assertEqual(premio.vendedor, self.descargue)
        self.assertEqual(premio.venta_descargue.descargue, self.descargue)
        self.assertEqual(len(response_admin.context['premios_list']), 1)

        self.client.force_login(self.descargue)
        response_descargue = self.client.get(
            reverse('premios'),
            data={'fecha': fecha.isoformat()},
        )
        self.assertEqual(response_descargue.status_code, 200)
        self.assertEqual(len(response_descargue.context['premios_list']), 1)
        self.assertEqual(
            response_descargue.context['premios_list'][0]['vendedor'],
            self.descargue,
        )

    def test_admin_puede_filtrar_premios_por_usuario_descargue(self):
        fecha = timezone.localdate()
        otra_descargue = get_user_model().objects.create_user(
            username='otro_descargue',
            password='segura123',
        )
        Group.objects.get(name='descargue').user_set.add(otra_descargue)

        VentaDescargue.objects.create(
            registrado_por=self.admin,
            descargue=self.descargue,
            loteria=self.loteria,
            numero='111',
            monto=500,
        )
        VentaDescargue.objects.create(
            registrado_por=self.admin,
            descargue=otra_descargue,
            loteria=self.loteria,
            numero='222',
            monto=500,
        )

        from core.models import Resultado

        Resultado.objects.create(
            loteria=self.loteria,
            fecha=fecha,
            resultado=111,
            registrado_por=self.admin,
        )

        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('premios'),
            data={
                'fecha': fecha.isoformat(),
                'vendedor': str(self.descargue.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['premios_list']), 1)
        self.assertEqual(
            response.context['premios_list'][0]['vendedor'],
            self.descargue,
        )
