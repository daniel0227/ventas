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
            es_combinado=False,
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

    def _crear_venta_existente(self, numero, monto, es_combinado=False):
        venta = Venta.objects.create(
            vendedor=self.user,
            numero=numero,
            monto=monto,
            es_combinado=es_combinado,
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
                'es_combinado': ['0'],
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
                'es_combinado': ['0'],
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
                'es_combinado': ['0'],
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


# ─────────────────────────────────────────────────────────────────────────────
# Tests para el campo es_combinado (BooleanField)
# ─────────────────────────────────────────────────────────────────────────────

class EsCombinadoModelTests(TestCase):
    """Verifica que el campo es_combinado se guarda y lee correctamente."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='vendedor_combi', password='pass')
        self.loteria = Loteria.objects.create(
            nombre='Lotería Combi',
            hora_inicio=time(0, 0),
            hora_fin=time(23, 59),
        )

    def _crear(self, es_combinado):
        v = Venta.objects.create(
            vendedor=self.user,
            numero='123',
            monto=1000,
            es_combinado=es_combinado,
        )
        v.loterias.set([self.loteria])
        return v

    def test_default_es_false(self):
        """Una venta creada sin especificar es_combinado debe tener False."""
        v = Venta.objects.create(vendedor=self.user, numero='100', monto=500)
        v.loterias.set([self.loteria])
        self.assertFalse(Venta.objects.get(pk=v.pk).es_combinado)

    def test_guarda_true(self):
        v = self._crear(es_combinado=True)
        self.assertTrue(Venta.objects.get(pk=v.pk).es_combinado)

    def test_guarda_false(self):
        v = self._crear(es_combinado=False)
        self.assertFalse(Venta.objects.get(pk=v.pk).es_combinado)

    def test_filtro_combinadas(self):
        self._crear(es_combinado=True)
        self._crear(es_combinado=False)
        self.assertEqual(Venta.objects.filter(es_combinado=True).count(), 1)
        self.assertEqual(Venta.objects.filter(es_combinado=False).count(), 1)

    def test_no_existe_campo_combi(self):
        """El campo combi ya no debe existir en el modelo."""
        v = self._crear(es_combinado=False)
        self.assertFalse(hasattr(v, 'combi'))


class EsCombinadoViewTests(TestCase):
    """Prueba el flujo completo POST → BD con es_combinado."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='vendedor_view', password='pass')
        self.client.force_login(self.user)

        dia_actual_en = timezone.localtime(timezone.now()).strftime('%A')
        dias_map = {
            'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
            'Thursday': 'Jueves', 'Friday': 'Viernes',
            'Saturday': 'Sábado', 'Sunday': 'Domingo',
        }
        self.dia = Dia.objects.create(nombre=dias_map[dia_actual_en])
        self.loteria = Loteria.objects.create(
            nombre='Lotería Vista',
            hora_inicio=time(0, 0),
            hora_fin=time(23, 59),
        )
        self.loteria.dias_juego.add(self.dia)

    def _post(self, numeros, montos, es_combinados, loterias=None):
        return self.client.post(
            reverse('ventas'),
            data={
                'loterias': [str(self.loteria.id)] if loterias is None else loterias,
                'numero': numeros,
                'monto': montos,
                'es_combinado': es_combinados,
            },
        )

    # ── Happy path ────────────────────────────────────────

    def test_venta_directa_guarda_false(self):
        """Apuesta sin combinado → es_combinado=False en BD."""
        response = self._post(['777'], ['2000'], ['0'])
        self.assertEqual(response.status_code, 201)
        v = Venta.objects.get(numero='777')
        self.assertFalse(v.es_combinado)

    def test_venta_combinada_guarda_true(self):
        """Apuesta combinada (checkbox activado = '1') → es_combinado=True."""
        response = self._post(['777'], ['2000'], ['1'])
        self.assertEqual(response.status_code, 201)
        v = Venta.objects.get(numero='777')
        self.assertTrue(v.es_combinado)

    def test_multiples_filas_combinado_mixto(self):
        """Varias filas: sólo las marcadas como '1' se guardan como combinado."""
        response = self._post(
            ['111', '222', '333'],
            ['1000', '1500', '2000'],
            ['0', '1', '0'],
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Venta.objects.get(numero='111').es_combinado)
        self.assertTrue(Venta.objects.get(numero='222').es_combinado)
        self.assertFalse(Venta.objects.get(numero='333').es_combinado)

    def test_respuesta_json_incluye_es_combinado(self):
        """El JSON de respuesta debe incluir el campo es_combinado."""
        response = self._post(['456'], ['3000'], ['1'])
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['success'])
        jugada = data['resumen_venta']['jugadas'][0]
        self.assertIn('es_combinado', jugada)
        self.assertTrue(jugada['es_combinado'])

    def test_multiples_loterias_con_combinado(self):
        """Con 2 loterías, se crea 1 venta con las 2 loterías asignadas vía M2M."""
        loteria2 = Loteria.objects.create(
            nombre='Segunda Lotería',
            hora_inicio=time(0, 0),
            hora_fin=time(23, 59),
        )
        loteria2.dias_juego.add(self.dia)

        response = self.client.post(
            reverse('ventas'),
            data={
                'loterias': [str(self.loteria.id), str(loteria2.id)],
                'numero': ['999'],
                'monto': ['5000'],
                'es_combinado': ['1'],
            },
        )
        self.assertEqual(response.status_code, 201)
        ventas = Venta.objects.filter(numero='999')
        # Una sola venta con ambas loterías asignadas via M2M
        self.assertEqual(ventas.count(), 1)
        v = ventas.first()
        self.assertTrue(v.es_combinado)
        self.assertEqual(v.loterias.count(), 2)

    # ── Validaciones ──────────────────────────────────────

    def test_rechaza_sin_numero(self):
        """Número vacío debe rechazarse (es_combinado ya no puede sustituirlo)."""
        response = self._post([''], ['2000'], ['1'])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIn('número', response.json()['error'])

    def test_rechaza_monto_cero(self):
        """Monto 0 debe rechazarse independientemente de es_combinado."""
        response = self._post(['123'], ['0'], ['1'])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    def test_rechaza_longitudes_inconsistentes(self):
        """Si los arrays no tienen la misma longitud el servidor rechaza."""
        response = self._post(
            ['111', '222'],   # 2 números
            ['1000', '2000'], # 2 montos
            ['0'],            # sólo 1 es_combinado → inconsistente
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    def test_es_combinado_valor_invalido_se_trata_como_false(self):
        """Cualquier valor distinto de '1' se interpreta como False."""
        casos = {'': '300', 'on': '301', 'true': '302', 'yes': '303', '2': '304'}
        for val, numero in casos.items():
            response = self._post([numero], ['1000'], [val])
            self.assertEqual(response.status_code, 201, f"Falló para valor '{val}'")
            self.assertFalse(
                Venta.objects.get(numero=numero).es_combinado,
                f"Se esperaba False para valor '{val}'",
            )

    # ── Migración de datos ────────────────────────────────

    def test_campo_combi_no_existe_en_bd(self):
        """Confirma que el campo combi fue eliminado de la tabla."""
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'core_venta'"
            )
            columnas = [row[0] for row in cursor.fetchall()]
        self.assertNotIn('combi', columnas)
        self.assertIn('es_combinado', columnas)
