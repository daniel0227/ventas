import logging
from datetime import date, time, timedelta

from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ConfiguracionVenta, Dia, Loteria, Notificacion,
    Premio, Resultado, Venta, VentaDescargue,
)
from core.utils import dia_es, total_monto, validar_rango_fechas
from core.views import _resolver_datos_premio, _resolver_datos_premio_combinado


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

        self.dia_actual = Dia.objects.create(nombre=dia_es(timezone.localtime(timezone.now())))

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

        self.dia_actual = Dia.objects.create(nombre=dia_es(timezone.localtime(timezone.now())))
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

        self.dia = Dia.objects.create(nombre=dia_es(timezone.localtime(timezone.now())))
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


# ─────────────────────────────────────────────────────────────────────────────
# 5.1 Tests de utilidades (core/utils.py)
# ─────────────────────────────────────────────────────────────────────────────

class DiaEsTests(TestCase):
    def test_dias_conocidos(self):
        casos = {
            date(2026, 4, 13): "Lunes",
            date(2026, 4, 14): "Martes",
            date(2026, 4, 15): "Miércoles",
            date(2026, 4, 16): "Jueves",
            date(2026, 4, 17): "Viernes",
            date(2026, 4, 18): "Sábado",
            date(2026, 4, 19): "Domingo",
        }
        for fecha, esperado in casos.items():
            with self.subTest(fecha=fecha):
                self.assertEqual(dia_es(fecha), esperado)

    def test_retorna_cadena_vacia_si_no_reconoce(self):
        class FechaFalsa:
            def strftime(self, fmt):
                return "Lunex"
        self.assertEqual(dia_es(FechaFalsa()), "")


class ValidarRangoFechasTests(TestCase):
    def test_rango_valido_retorna_ok(self):
        ok, msg = validar_rango_fechas(date(2026, 1, 1), date(2026, 1, 30))
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_rango_exactamente_93_dias_es_valido(self):
        inicio = date(2026, 1, 1)
        fin = inicio + timedelta(days=93)
        ok, _ = validar_rango_fechas(inicio, fin)
        self.assertTrue(ok)

    def test_rango_mayor_93_dias_es_invalido(self):
        inicio = date(2026, 1, 1)
        fin = inicio + timedelta(days=94)
        ok, msg = validar_rango_fechas(inicio, fin)
        self.assertFalse(ok)
        self.assertIn("93", msg)

    def test_max_dias_personalizado(self):
        inicio = date(2026, 1, 1)
        fin = inicio + timedelta(days=10)
        ok, _ = validar_rango_fechas(inicio, fin, max_dias=7)
        self.assertFalse(ok)

    def test_sin_fechas_retorna_ok(self):
        ok, _ = validar_rango_fechas(None, None)
        self.assertTrue(ok)


class TotalMontoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="util_user", password="x")
        self.loteria = Loteria.objects.create(
            nombre="Util Loteria", hora_inicio=time(0, 0), hora_fin=time(23, 59)
        )

    def test_suma_montos(self):
        for monto in [1000, 2000, 3000]:
            v = Venta.objects.create(vendedor=self.user, numero="1", monto=monto)
            v.loterias.set([self.loteria])
        resultado = total_monto(Venta.objects.all())
        self.assertEqual(resultado, 6000)

    def test_retorna_cero_si_vacio(self):
        self.assertEqual(total_monto(Venta.objects.none()), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 5.1 Tests de cálculo de premios
# ─────────────────────────────────────────────────────────────────────────────

class ResolverDatosPremioTests(TestCase):
    def test_dos_cifras_coinciden(self):
        datos = _resolver_datos_premio("34", "1234")  # últimas 2 cifras de "1234"
        self.assertIsNotNone(datos)
        self.assertEqual(datos["cifras"], 2)
        self.assertEqual(datos["multiplicador"], 60)

    def test_tres_cifras_coinciden(self):
        datos = _resolver_datos_premio("234", "1234")
        self.assertIsNotNone(datos)
        self.assertEqual(datos["cifras"], 3)
        self.assertEqual(datos["multiplicador"], 550)

    def test_cuatro_cifras_coinciden(self):
        datos = _resolver_datos_premio("1234", "1234")
        self.assertIsNotNone(datos)
        self.assertEqual(datos["cifras"], 4)
        self.assertEqual(datos["multiplicador"], 4500)

    def test_no_coincide_retorna_none(self):
        self.assertIsNone(_resolver_datos_premio("99", "1234"))

    def test_longitud_invalida_retorna_none(self):
        self.assertIsNone(_resolver_datos_premio("1", "1234"))
        self.assertIsNone(_resolver_datos_premio("12345", "12345"))

    def test_numero_vacio_retorna_none(self):
        self.assertIsNone(_resolver_datos_premio("", "1234"))


class ResolverDatosPremioCombinadoTests(TestCase):
    def test_tres_cifras_permutacion_gana(self):
        datos = _resolver_datos_premio_combinado("342", "1234")  # 342 es permutación de 234 (últimas 3 cifras)
        self.assertIsNotNone(datos)
        self.assertEqual(datos["multiplicador"], 90)

    def test_tres_cifras_mismos_digitos_gana(self):
        datos = _resolver_datos_premio_combinado("234", "1234")
        self.assertIsNotNone(datos)

    def test_cuatro_cifras_permutacion_gana(self):
        datos = _resolver_datos_premio_combinado("4321", "1234")
        self.assertIsNotNone(datos)
        self.assertEqual(datos["multiplicador"], 220)

    def test_no_es_permutacion_retorna_none(self):
        self.assertIsNone(_resolver_datos_premio_combinado("999", "1234"))

    def test_dos_cifras_no_aplica(self):
        self.assertIsNone(_resolver_datos_premio_combinado("23", "1234"))


class PremioVistaTests(TestCase):
    """Verifica que la vista premios calcula y persiste correctamente."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_premio", password="x", is_staff=True, is_superuser=True
        )
        self.vendedor = User.objects.create_user(username="vendedor_premio", password="x")
        self.dia = Dia.objects.create(nombre=dia_es(timezone.localtime(timezone.now())))
        self.loteria = Loteria.objects.create(
            nombre="Lotería Premio Test",
            hora_inicio=time(0, 0),
            hora_fin=time(23, 59),
        )
        self.loteria.dias_juego.add(self.dia)
        self.fecha = timezone.localdate()

    def _crear_venta(self, numero, monto, es_combinado=False):
        v = Venta.objects.create(
            vendedor=self.vendedor, numero=numero, monto=monto, es_combinado=es_combinado
        )
        v.loterias.set([self.loteria])
        return v

    def _crear_resultado(self, numero_ganador):
        return Resultado.objects.create(
            loteria=self.loteria,
            fecha=self.fecha,
            resultado=int(numero_ganador),
            registrado_por=self.admin,
        )

    def test_premio_dos_cifras_calculado_correctamente(self):
        self._crear_venta("34", 1000)
        self._crear_resultado("1234")
        self.client.force_login(self.admin)
        self.client.get(reverse("premios"), {"fecha": self.fecha.isoformat()})
        premio = Premio.objects.get()
        self.assertEqual(premio.premio, 1000 * 60)
        self.assertEqual(premio.cifras, 2)

    def test_premio_tres_cifras_calculado_correctamente(self):
        self._crear_venta("234", 500)
        self._crear_resultado("1234")
        self.client.force_login(self.admin)
        self.client.get(reverse("premios"), {"fecha": self.fecha.isoformat()})
        premio = Premio.objects.get()
        self.assertEqual(premio.premio, 500 * 550)

    def test_no_gana_retorna_lista_vacia(self):
        self._crear_venta("99", 1000)
        self._crear_resultado("1234")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("premios"), {"fecha": self.fecha.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["premios_list"]), 0)

    def test_premio_combinado_tres_cifras(self):
        self._crear_venta("432", 200, es_combinado=True)
        self._crear_resultado("1234")
        self.client.force_login(self.admin)
        self.client.get(reverse("premios"), {"fecha": self.fecha.isoformat()})
        premio = Premio.objects.filter(es_combinado=True).first()
        self.assertIsNotNone(premio)
        self.assertEqual(premio.premio, 200 * 90)

    def test_vendedor_solo_ve_sus_premios(self):
        otro = get_user_model().objects.create_user(username="otro_v", password="x")
        v_otro = Venta.objects.create(vendedor=otro, numero="34", monto=1000)
        v_otro.loterias.set([self.loteria])
        self._crear_resultado("1234")

        self.client.force_login(self.vendedor)
        response = self.client.get(reverse("premios"), {"fecha": self.fecha.isoformat()})
        self.assertEqual(len(response.context["premios_list"]), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 5.1 Tests de vistas de reportes
# ─────────────────────────────────────────────────────────────────────────────

class ReportesViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_user(
            username="super_rep", password="x",
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(self.superuser)
        self.dia = Dia.objects.create(nombre=dia_es(timezone.localtime(timezone.now())))
        self.loteria = Loteria.objects.create(
            nombre="Lot Rep", hora_inicio=time(0, 0), hora_fin=time(23, 59)
        )
        self.loteria.dias_juego.add(self.dia)
        self.hoy = timezone.localdate().isoformat()

    def _crear_venta(self, monto=5000, numero="111"):
        v = Venta.objects.create(vendedor=self.superuser, numero=numero, monto=monto)
        v.loterias.set([self.loteria])
        return v

    # ── Reporte liquidación ─────────────────────────────────
    def test_reportes_retorna_200_con_datos(self):
        self._crear_venta()
        resp = self.client.get(reverse("reportes"), {"start_date": self.hoy, "end_date": self.hoy})
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.context["rows"]), 0)

    def test_reportes_sin_rango_redirige(self):
        resp = self.client.get(reverse("reportes"))
        # Sin fechas usa la fecha de hoy y retorna 200 con 0 rows o redirige
        self.assertIn(resp.status_code, [200, 302])

    def test_reportes_exporta_csv(self):
        self._crear_venta()
        resp = self.client.get(
            reverse("reportes"),
            {"start_date": self.hoy, "end_date": self.hoy, "export": "csv"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn(b"Vendedor", resp.content)

    def test_reportes_exporta_excel(self):
        self._crear_venta()
        resp = self.client.get(
            reverse("reportes"),
            {"start_date": self.hoy, "end_date": self.hoy, "export": "excel"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_reportes_rango_mayor_93_dias_redirige(self):
        inicio = (timezone.localdate() - timedelta(days=100)).isoformat()
        resp = self.client.get(
            reverse("reportes"),
            {"start_date": inicio, "end_date": self.hoy},
        )
        self.assertEqual(resp.status_code, 302)

    # ── Reporte ventas vs premios ───────────────────────────
    def test_reporte_ventas_vs_premios_retorna_200(self):
        resp = self.client.get(
            reverse("reporte_ventas_vs_premios"),
            {"start_date": self.hoy, "end_date": self.hoy},
        )
        self.assertEqual(resp.status_code, 200)

    def test_reporte_ventas_vs_premios_exporta_csv(self):
        self._crear_venta()
        resp = self.client.get(
            reverse("reporte_ventas_vs_premios"),
            {"start_date": self.hoy, "end_date": self.hoy, "export": "csv"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])

    def test_reporte_ventas_vs_premios_exporta_excel(self):
        self._crear_venta()
        resp = self.client.get(
            reverse("reporte_ventas_vs_premios"),
            {"start_date": self.hoy, "end_date": self.hoy, "export": "excel"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    # ── Reporte premios por rango ───────────────────────────
    def test_premios_reporte_rango_retorna_200(self):
        resp = self.client.get(
            reverse("premios_reporte_rango"),
            {"fecha_inicio": self.hoy, "fecha_fin": self.hoy},
        )
        self.assertEqual(resp.status_code, 200)

    def test_premios_reporte_rango_exporta_csv(self):
        resp = self.client.get(
            reverse("premios_reporte_rango"),
            {"fecha_inicio": self.hoy, "fecha_fin": self.hoy, "export": "csv"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])

    def test_premios_reporte_rango_exporta_excel(self):
        resp = self.client.get(
            reverse("premios_reporte_rango"),
            {"fecha_inicio": self.hoy, "fecha_fin": self.hoy, "export": "excel"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    # ── Reporte conciliación ────────────────────────────────
    def test_reporte_conciliacion_retorna_200(self):
        resp = self.client.get(
            reverse("reporte_conciliacion"),
            {"fecha_inicio": self.hoy, "fecha_fin": self.hoy},
        )
        self.assertEqual(resp.status_code, 200)

    def test_reporte_conciliacion_calcula_diferencia(self):
        self._crear_venta(monto=10000, numero="22")
        Resultado.objects.create(
            loteria=self.loteria,
            fecha=timezone.localdate(),
            resultado=1122,
            registrado_por=self.superuser,
        )
        # Genera el premio primero
        self.client.get(reverse("premios"), {"fecha": self.hoy})

        resp = self.client.get(
            reverse("reporte_conciliacion"),
            {"fecha_inicio": self.hoy, "fecha_fin": self.hoy},
        )
        self.assertEqual(resp.status_code, 200)
        rows = resp.context["rows"]
        self.assertEqual(len(rows), 1)
        # Vendido = 10000, Premio = 10000 * 60 = 600000 → diferencia negativa
        self.assertEqual(rows[0]["total_ventas"], 10000)
        self.assertLess(rows[0]["diferencia"], 0)

    def test_reporte_conciliacion_exporta_csv(self):
        self._crear_venta()
        resp = self.client.get(
            reverse("reporte_conciliacion"),
            {"fecha_inicio": self.hoy, "fecha_fin": self.hoy, "export": "csv"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])

    def test_reporte_conciliacion_exporta_excel(self):
        self._crear_venta()
        resp = self.client.get(
            reverse("reporte_conciliacion"),
            {"fecha_inicio": self.hoy, "fecha_fin": self.hoy, "export": "excel"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_no_superuser_no_puede_ver_reportes(self):
        User = get_user_model()
        vendedor = User.objects.create_user(username="vend_noperm", password="x")
        self.client.force_login(vendedor)
        resp = self.client.get(reverse("reportes"))
        self.assertEqual(resp.status_code, 302)

    def test_reporte_descargas_exporta_excel(self):
        self._crear_venta()
        resp = self.client.get(
            reverse("reporte_descargas"),
            {"fecha": self.hoy, "export": "excel"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])


# ─────────────────────────────────────────────────────────────────────────────
# 5.1 Tests de Notificaciones
# ─────────────────────────────────────────────────────────────────────────────

class NotificacionModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="notif_user", password="x")

    def test_crear_notificacion(self):
        n = Notificacion.crear(self.user, "Título test", mensaje="Detalle", tipo=Notificacion.TIPO_EXITO)
        self.assertEqual(n.titulo, "Título test")
        self.assertEqual(n.tipo, Notificacion.TIPO_EXITO)
        self.assertFalse(n.leida)

    def test_notificacion_no_leida_por_defecto(self):
        n = Notificacion.objects.create(usuario=self.user, titulo="Test")
        self.assertFalse(n.leida)
        self.assertEqual(n.tipo, Notificacion.TIPO_INFO)

    def test_str_representacion(self):
        n = Notificacion.crear(self.user, "Alerta")
        self.assertIn("Alerta", str(n))


class NotificacionAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="notif_api_user", password="x")
        self.client.force_login(self.user)

    def test_count_retorna_cero_sin_notificaciones(self):
        resp = self.client.get(reverse("notificaciones_count"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_count_retorna_cantidad_no_leidas(self):
        Notificacion.crear(self.user, "Una")
        Notificacion.crear(self.user, "Dos")
        resp = self.client.get(reverse("notificaciones_count"))
        self.assertEqual(resp.json()["count"], 2)

    def test_count_no_cuenta_leidas(self):
        Notificacion.objects.create(usuario=self.user, titulo="Leída", leida=True)
        Notificacion.crear(self.user, "No leída")
        resp = self.client.get(reverse("notificaciones_count"))
        self.assertEqual(resp.json()["count"], 1)

    def test_list_retorna_notificaciones(self):
        Notificacion.crear(self.user, "Notif 1")
        resp = self.client.get(reverse("notificaciones_list"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["notificaciones"]), 1)
        self.assertEqual(data["notificaciones"][0]["titulo"], "Notif 1")

    def test_list_marca_como_leidas(self):
        Notificacion.crear(self.user, "Pendiente")
        self.client.get(reverse("notificaciones_list"))
        self.assertEqual(Notificacion.objects.filter(leida=False).count(), 0)

    def test_list_solo_ve_propias_notificaciones(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_notif", password="x")
        Notificacion.crear(otro, "No mía")
        Notificacion.crear(self.user, "Mía")
        resp = self.client.get(reverse("notificaciones_list"))
        notifs = resp.json()["notificaciones"]
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0]["titulo"], "Mía")

    def test_count_requiere_autenticacion(self):
        self.client.logout()
        resp = self.client.get(reverse("notificaciones_count"))
        self.assertEqual(resp.status_code, 302)

    def test_list_requiere_autenticacion(self):
        self.client.logout()
        resp = self.client.get(reverse("notificaciones_list"))
        self.assertEqual(resp.status_code, 302)


# ─────────────────────────────────────────────────────────────────────────────
# 5.1 Tests de Middleware de auditoría
# ─────────────────────────────────────────────────────────────────────────────

class ActivityLogMiddlewareTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="mw_user", password="x")
        self.dia = Dia.objects.create(nombre=dia_es(timezone.localtime(timezone.now())))

    def test_request_autenticado_genera_log(self):
        self.client.force_login(self.user)
        with self.assertLogs("lottia.activity", level="INFO") as cm:
            self.client.get(reverse("home"))
        self.assertTrue(any("mw_user" in line for line in cm.output))

    def test_request_no_autenticado_no_genera_log(self):
        # home redirige a login si no está autenticado — no debe loggear
        with self.assertRaises(AssertionError):
            with self.assertLogs("lottia.activity", level="INFO"):
                self.client.get(reverse("home"))

    def test_log_incluye_metodo_path_y_status(self):
        self.client.force_login(self.user)
        with self.assertLogs("lottia.activity", level="INFO") as cm:
            self.client.get(reverse("home"))
        log_line = cm.output[0]
        self.assertIn("GET", log_line)
        self.assertIn("/", log_line)

    def test_path_skip_no_genera_log(self):
        self.client.force_login(self.user)
        # El endpoint de conteo está en la skip list
        with self.assertRaises(AssertionError):
            with self.assertLogs("lottia.activity", level="INFO"):
                self.client.get(reverse("notificaciones_count"))


# ─────────────────────────────────────────────────────────────────────────────
# 5.1 Tests para reporte_riesgo_ventas
# ─────────────────────────────────────────────────────────────────────────────

class ReporteRiesgoVentasTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='staff_riesgo',
            password='segura123',
            is_staff=True,
        )
        self.user = User.objects.create_user(
            username='vendedor_riesgo',
            password='segura123',
            is_staff=False,
        )
        self.loteria = Loteria.objects.create(
            nombre='Riesgo Test',
            hora_inicio=time(8, 0),
            hora_fin=time(23, 0),
        )

    def _crear_resultado(self, numero, fecha=None):
        from datetime import date as ddate
        Resultado.objects.create(
            loteria=self.loteria,
            fecha=fecha or ddate.today(),
            resultado=numero,
            registrado_por=self.staff,
        )

    def test_redirige_si_no_autenticado(self):
        response = self.client.get(reverse('reporte_riesgo_ventas'))
        self.assertIn(response.status_code, [302, 301])

    def test_redirige_si_no_es_staff(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('reporte_riesgo_ventas'))
        self.assertEqual(response.status_code, 302)

    def test_muestra_formulario_vacio_sin_parametros(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('reporte_riesgo_ventas'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tabla'], [])

    def test_calcula_riesgo_pct_correctamente(self):
        from datetime import date as ddate
        hoy = ddate.today()
        # Crear resultados individuales para evitar unique_together
        Resultado.objects.filter(loteria=self.loteria).delete()
        for i in range(8):
            Resultado.objects.create(
                loteria=self.loteria,
                fecha=ddate(2024, 1, i + 1),
                resultado=9999,
                registrado_por=self.staff,
            )
        Resultado.objects.create(
            loteria=self.loteria,
            fecha=ddate(2024, 2, 1),
            resultado=1234,
            registrado_por=self.staff,
        )
        Resultado.objects.create(
            loteria=self.loteria,
            fecha=ddate(2024, 2, 2),
            resultado=1234,
            registrado_por=self.staff,
        )
        # total_sorteos = 10, 1234 ganó 2 → riesgo_pct = 20.0

        venta = Venta.objects.create(
            vendedor=self.staff,
            numero='1234',
            monto=5000,
            es_combinado=False,
        )
        venta.loterias.set([self.loteria])

        self.client.force_login(self.staff)
        response = self.client.get(reverse('reporte_riesgo_ventas'), {
            'loteria': self.loteria.pk,
            'fecha_desde': str(hoy),
            'fecha_hasta': str(hoy),
        })
        self.assertEqual(response.status_code, 200)
        tabla = response.context['tabla']
        self.assertEqual(len(tabla), 1)
        row = tabla[0]
        self.assertEqual(row['numero'], '1234')
        self.assertEqual(row['veces_ganado'], 2)
        self.assertAlmostEqual(row['riesgo_pct'], 20.0, places=1)
        self.assertEqual(row['nivel'], 'ALTO')

    def test_nivel_bajo_si_nunca_gano(self):
        from datetime import date as ddate
        hoy = ddate.today()
        Resultado.objects.create(
            loteria=self.loteria,
            fecha=ddate(2024, 3, 1),
            resultado=9999,
            registrado_por=self.staff,
        )
        venta = Venta.objects.create(
            vendedor=self.staff,
            numero='1234',
            monto=1000,
            es_combinado=False,
        )
        venta.loterias.set([self.loteria])

        self.client.force_login(self.staff)
        response = self.client.get(reverse('reporte_riesgo_ventas'), {
            'loteria': self.loteria.pk,
            'fecha_desde': str(hoy),
            'fecha_hasta': str(hoy),
        })
        self.assertEqual(response.status_code, 200)
        tabla = response.context['tabla']
        self.assertEqual(len(tabla), 1)
        self.assertEqual(tabla[0]['nivel'], 'BAJO')
        self.assertEqual(tabla[0]['veces_ganado'], 0)

    def test_export_csv_retorna_contenido_correcto(self):
        from datetime import date as ddate
        hoy = ddate.today()
        venta = Venta.objects.create(
            vendedor=self.staff,
            numero='5678',
            monto=3000,
            es_combinado=False,
        )
        venta.loterias.set([self.loteria])

        self.client.force_login(self.staff)
        response = self.client.get(reverse('reporte_riesgo_ventas'), {
            'loteria': self.loteria.pk,
            'fecha_desde': str(hoy),
            'fecha_hasta': str(hoy),
            'export': 'csv',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        content = response.content.decode('utf-8-sig')
        self.assertIn('Número', content)
        self.assertIn('5678', content)
