from django.shortcuts import render, HttpResponse, redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from django.utils.dateparse import parse_date
from django.http import Http404, JsonResponse
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from .models import Loteria, Dia, Venta, Resultado, Premio, VentaAuditLog, ConfiguracionVenta, _safe_create_venta_audit_log
from django.db import transaction, IntegrityError
from core.utils import importar_resultados  # ← añade esta línea
from django.contrib import messages
from django.db.models import Case, When, BooleanField, Sum, Count, F, Q, ExpressionWrapper, IntegerField
from collections import defaultdict
from django.utils.timezone import localtime, now, make_aware
from .forms import VentaForm
from django.core.paginator import Paginator
from pytz import timezone as pytz_timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import get_user_model
from datetime import date, timedelta, datetime
from django.db.models.functions import TruncDate
from django.db.models.functions import Coalesce, Trim
import os

VENTA_CIERRE_BUFFER_SEGUNDOS = int(getattr(settings, "VENTA_CIERRE_BUFFER_SEGUNDOS", 30))


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _audit_sale_event(request, event_type, status, message="", venta=None, payload=None, actor=None):
    _safe_create_venta_audit_log(
        event_type=event_type,
        status=status,
        venta=venta,
        actor=actor or getattr(request, "user", None),
        message=message,
        payload=payload or {},
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _loteria_esta_abierta_para_venta(loteria, ahora_local):
    return loteria.esta_disponible_en(ahora_local, cierre_buffer_segundos=VENTA_CIERRE_BUFFER_SEGUNDOS)


def _obtener_limite_apuesta_por_numero():
    limite = (
        ConfiguracionVenta.objects
        .filter(clave=ConfiguracionVenta.CLAVE_GLOBAL)
        .values_list("limite_apuesta_por_numero", flat=True)
        .first()
    )
    return int(limite or 0)

# Vista Home
@login_required
def home(request):
    # Obtener la fecha actual y la hora local ajustada    
    ahora = localtime()
    dia_actual = ahora.date()

    # Calcular el total de ventas y el promedio diario de ventas
    total_ventas = Venta.objects.filter(fecha_venta__date=dia_actual).aggregate(Sum('monto'))['monto__sum'] or 0
    ventas_del_dia = Venta.objects.filter(fecha_venta__date=dia_actual)

    # Calcular el promedio diario de ventas
    if ventas_del_dia.exists():
        promedio_diario = total_ventas / ventas_del_dia.count()
    else:
        promedio_diario = 0

    # Filtrar las ventas por vendedor
    ventas_por_vendedor = Venta.objects.values('vendedor').annotate(total_ventas=Sum('monto')).order_by('-total_ventas')

    # Filtrar las ventas por tendencia (última semana, por ejemplo)
    fecha_inicio = ahora - timedelta(days=7)
    ventas_tendencia = Venta.objects.filter(fecha_venta__gte=fecha_inicio).values('fecha_venta').annotate(total_ventas=Sum('monto')).order_by('fecha_venta')

    return render(request, 'core/home.html', {
        'total_ventas': total_ventas,
        'promedio_diario': promedio_diario,
        'ventas_por_vendedor': ventas_por_vendedor,
        'ventas_tendencia': ventas_tendencia,
    })

# Vista para mostrar loterías disponibles del día
@login_required
def loteria(request):
    # Obtener la fecha y hora actuales ajustadas a la zona horaria local
    ahora = timezone.localtime(timezone.now())  # Hora local en Bogotá
    dia_actual_nombre = ahora.strftime('%A')  # Nombre del día en inglés

    # Mapeo de los días en inglés a español
    dias_map = {
        'Monday': 'Lunes',
        'Tuesday': 'Martes',
        'Wednesday': 'Miércoles',
        'Thursday': 'Jueves',
        'Friday': 'Viernes',
        'Saturday': 'Sábado',
        'Sunday': 'Domingo',
    }

    dia_actual_nombre_es = dias_map.get(dia_actual_nombre)
    fecha_actual = ahora.date()  # Fecha actual ajustada a la zona horaria local

    try:
        dia_actual = Dia.objects.get(nombre=dia_actual_nombre_es)  # Busca el día en español
    except Dia.DoesNotExist:
        raise Http404(f"No se ha encontrado un día con el nombre {dia_actual_nombre_es}")

    # Filtrar las loterías que se juegan en el día actual y anotar si están disponibles
    loterias = Loteria.objects.filter(dias_juego=dia_actual).annotate(
        disponible=Case(
            When(hora_inicio__lte=ahora.time(), hora_fin__gte=ahora.time(), then=True),
            default=False,
            output_field=BooleanField(),
        )
    ).order_by('-disponible')  # Ordena las disponibles primero

    current_time = ahora.time()  # Hora actual en formato local

    return render(request, 'core/loterias.html', {
        'loterias': loterias,
        'dia_actual_nombre': dia_actual_nombre_es,
        'fecha_actual': fecha_actual,
        'current_time': current_time,
    })

# Vista simple para ventas (no se ha modificado)
@login_required
def ventas(request):
    return render(request, "core/ventas.html")

# Vista de Login personalizada
class CustomLoginView(LoginView):
    template_name = 'core/login.html'
    redirect_authenticated_user = True  # Redirige si el usuario ya está autenticado

# Vista para crear una venta
@login_required
@require_http_methods(["GET", "POST"])
def crear_venta(request):
    """
    Crea ventas en bloque.

    Reglas por fila:
      • monto (valor)  → obligatorio y > 0
      • Se debe ingresar al menos uno de los dos: numero o combi
    Además, la venta solo es válida si las loterías seleccionadas
    están abiertas en la hora actual.
    """
    ahora = timezone.localtime(timezone.now())

    # -------- Obtener día de la semana (ES) --------
    dias_map = {
        'Monday':    'Lunes', 'Tuesday':   'Martes', 'Wednesday': 'Miércoles',
        'Thursday':  'Jueves', 'Friday':  'Viernes', 'Saturday':  'Sábado',
        'Sunday':    'Domingo',
    }
    dia_actual_nombre_es = dias_map.get(ahora.strftime('%A'))
    if not dia_actual_nombre_es:
        return JsonResponse(
            {'success': False, 'error': 'Día actual no válido.'}, status=400
        )

    try:
        dia_actual = Dia.objects.get(nombre=dia_actual_nombre_es)
    except Dia.DoesNotExist:
        return JsonResponse(
            {'success': False,
             'error': f'Día no encontrado: {dia_actual_nombre_es}'},
            status=404
        )

    # -------- Loterías disponibles en la hora actual --------
    loterias = (
        Loteria.objects.filter(dias_juego=dia_actual)
        .annotate(
            disponible=Case(
                When(hora_inicio__lte=ahora.time(),
                     hora_fin__gte=ahora.time(),
                     then=True),
                default=False,
                output_field=BooleanField()
            )
        )
        .filter(disponible=True)
        .order_by('-disponible')
    )

    # ======================= POST ==========================
    if request.method == 'POST':
        loterias_ids = request.POST.getlist('loterias')
        numeros = request.POST.getlist('numero')
        montos = request.POST.getlist('monto')
        combis = request.POST.getlist('combi')
        loterias_ids = list(dict.fromkeys(loterias_ids))

        _audit_sale_event(
            request,
            VentaAuditLog.EVENT_CREATE_ATTEMPT,
            VentaAuditLog.STATUS_INFO,
            message="Intento de creacion de venta recibido.",
            payload={"loterias_ids": loterias_ids, "rows_count": len(numeros)}
        )

        # --- Validaciones de longitud ---
        if not (len(numeros) == len(montos) == len(combis)):
            _audit_sale_event(
                request,
                VentaAuditLog.EVENT_CREATE_REJECTED,
                VentaAuditLog.STATUS_REJECTED,
                message="Longitudes inconsistentes entre numero, monto y combi.",
                payload={"numero": len(numeros), "monto": len(montos), "combi": len(combis)}
            )
            return JsonResponse(
                {'success': False, 'error': 'Los numeros, montos y combis no coinciden.'},
                status=400
            )

        # --- Loterias seleccionadas ---
        loterias_seleccionadas = Loteria.objects.filter(id__in=loterias_ids)
        if not loterias_seleccionadas.exists():
            _audit_sale_event(
                request,
                VentaAuditLog.EVENT_CREATE_REJECTED,
                VentaAuditLog.STATUS_REJECTED,
                message="Loterias no validas.",
                payload={"loterias_ids": loterias_ids}
            )
            return JsonResponse(
                {'success': False, 'error': 'Loterias no validas.'},
                status=400
            )

        # --- Horario de cada loteria ---
        for lot in loterias_seleccionadas:
            if not _loteria_esta_abierta_para_venta(lot, ahora):
                _audit_sale_event(
                    request,
                    VentaAuditLog.EVENT_CREATE_CLOSED,
                    VentaAuditLog.STATUS_REJECTED,
                    message=f"Intento fuera de horario para {lot.nombre}.",
                    payload={
                        "loteria_id": lot.id,
                        "loteria": lot.nombre,
                        "server_time": ahora.isoformat(),
                        "hora_inicio": str(lot.hora_inicio),
                        "hora_fin": str(lot.hora_fin),
                        "buffer_segundos": VENTA_CIERRE_BUFFER_SEGUNDOS,
                    }
                )
                return JsonResponse(
                    {'success': False, 'error': f'La hora de juego para {lot.nombre} ha finalizado.'},
                    status=400
                )

        # --- Validacion fila a fila ---
        jugadas_validadas = []
        for idx, (numero, monto, combi) in enumerate(zip(numeros, montos, combis), start=1):
            numero = (numero or '').strip()
            combi = (combi or '').strip()
            monto = (monto or '').strip()

            try:
                monto_val = int(monto) if monto != '' else 0
            except (TypeError, ValueError):
                _audit_sale_event(
                    request,
                    VentaAuditLog.EVENT_CREATE_REJECTED,
                    VentaAuditLog.STATUS_REJECTED,
                    message=f"Fila {idx}: monto invalido.",
                    payload={"fila": idx, "monto": monto}
                )
                return JsonResponse(
                    {'success': False, 'error': f'Fila {idx}: el monto debe ser numerico.'},
                    status=400
                )

            if monto == '' or monto_val <= 0:
                _audit_sale_event(
                    request,
                    VentaAuditLog.EVENT_CREATE_REJECTED,
                    VentaAuditLog.STATUS_REJECTED,
                    message=f"Fila {idx}: monto faltante o no positivo.",
                    payload={"fila": idx, "monto": monto}
                )
                return JsonResponse(
                    {'success': False, 'error': f'Fila {idx}: el monto es obligatorio y debe ser mayor que 0.'},
                    status=400
                )

            if numero == '' and combi == '':
                _audit_sale_event(
                    request,
                    VentaAuditLog.EVENT_CREATE_REJECTED,
                    VentaAuditLog.STATUS_REJECTED,
                    message=f"Fila {idx}: numero y combi vacios.",
                    payload={"fila": idx}
                )
                return JsonResponse(
                    {'success': False, 'error': f'Fila {idx}: ingrese Numero o Combi.'},
                    status=400
                )

            jugadas_validadas.append({
                "fila": idx,
                "numero": numero,
                "combi": combi,
                "monto": monto_val,
            })

        # --- Crear ventas dentro de una transaccion ---
        try:
            with transaction.atomic():
                ahora_tx = timezone.localtime(timezone.now())
                loterias_seleccionadas = list(
                    Loteria.objects.select_for_update().filter(id__in=loterias_ids, dias_juego=dia_actual)
                )
                loterias_count = len(loterias_seleccionadas)

                if loterias_count != len(loterias_ids):
                    _audit_sale_event(
                        request,
                        VentaAuditLog.EVENT_CREATE_REJECTED,
                        VentaAuditLog.STATUS_REJECTED,
                        message="Loterias invalidas o fuera del dia actual en revalidacion.",
                        payload={"loterias_ids": loterias_ids, "dia": dia_actual_nombre_es}
                    )
                    return JsonResponse(
                        {'success': False, 'error': 'Loterias no validas para el dia actual.'},
                        status=400
                    )

                for lot in loterias_seleccionadas:
                    if not _loteria_esta_abierta_para_venta(lot, ahora_tx):
                        _audit_sale_event(
                            request,
                            VentaAuditLog.EVENT_CREATE_CLOSED,
                            VentaAuditLog.STATUS_REJECTED,
                            message=f"Rechazada en revalidacion final por cierre de {lot.nombre}.",
                            payload={
                                "loteria_id": lot.id,
                                "loteria": lot.nombre,
                                "server_time": ahora_tx.isoformat(),
                                "hora_inicio": str(lot.hora_inicio),
                                "hora_fin": str(lot.hora_fin),
                                "buffer_segundos": VENTA_CIERRE_BUFFER_SEGUNDOS,
                            }
                        )
                        return JsonResponse(
                            {'success': False, 'error': f'La hora de juego para {lot.nombre} ha finalizado.'},
                            status=400
                        )

                limite_apuesta_por_numero = _obtener_limite_apuesta_por_numero()
                if limite_apuesta_por_numero > 0:
                    numeros_con_tope = sorted({
                        jugada["numero"] for jugada in jugadas_validadas if jugada["numero"]
                    })
                    if numeros_con_tope:
                        acumulado_actual = {}
                        ventas_existentes = (
                            Venta.objects
                            .select_for_update()
                            .filter(
                                fecha_venta__date=ahora_tx.date(),
                                loterias__in=loterias_seleccionadas,
                                numero__in=numeros_con_tope,
                            )
                            .values("loterias__id", "numero", "monto")
                        )
                        for item in ventas_existentes:
                            numero_item = str(item.get("numero") or "").strip()
                            if not numero_item:
                                continue
                            key = (item["loterias__id"], numero_item)
                            acumulado_actual[key] = int(acumulado_actual.get(key, 0)) + int(item.get("monto") or 0)

                        acumulado_nuevo = defaultdict(int)
                        for jugada in jugadas_validadas:
                            numero_jugada = jugada["numero"]
                            if not numero_jugada:
                                continue
                            monto_jugada = int(jugada["monto"])
                            for lot in loterias_seleccionadas:
                                key = (lot.id, numero_jugada)
                                total_actual = int(acumulado_actual.get(key, 0)) + int(acumulado_nuevo[key])
                                total_proyectado = total_actual + monto_jugada
                                if total_proyectado > limite_apuesta_por_numero:
                                    disponible = max(limite_apuesta_por_numero - total_actual, 0)
                                    error_msg = (
                                        "Se excedio el valor de apuesta para ese numero. "
                                        f"Numero: {numero_jugada}. "
                                        f"Loteria: {lot.nombre}. "
                                        f"Disponible: ${disponible:,} COP."
                                    ).replace(",", ".")
                                    _audit_sale_event(
                                        request,
                                        VentaAuditLog.EVENT_CREATE_REJECTED,
                                        VentaAuditLog.STATUS_REJECTED,
                                        message="Venta rechazada por limite global por numero.",
                                        payload={
                                            "numero": numero_jugada,
                                            "loteria_id": lot.id,
                                            "loteria": lot.nombre,
                                            "limite": limite_apuesta_por_numero,
                                            "vendido_actual": total_actual,
                                            "monto_intento": monto_jugada,
                                        }
                                    )
                                    return JsonResponse({'success': False, 'error': error_msg}, status=400)
                                acumulado_nuevo[key] += monto_jugada

                ventas_creadas = []
                for jugada in jugadas_validadas:
                    venta = Venta.objects.create(
                        vendedor=request.user,
                        numero=jugada["numero"],
                        monto=int(jugada["monto"]),
                        fecha_venta=ahora_tx,
                        combi=int(jugada["combi"]) if jugada["combi"] else None
                    )
                    venta._allow_loterias_assignment = True
                    venta.loterias.set(loterias_seleccionadas)
                    ventas_creadas.append(venta)

                codigo_venta = ventas_creadas[0].id if ventas_creadas else None

        except IntegrityError as exc:
            _audit_sale_event(
                request,
                VentaAuditLog.EVENT_CREATE_REJECTED,
                VentaAuditLog.STATUS_ERROR,
                message="Error de integridad al crear venta.",
                payload={"error": str(exc)}
            )
            return JsonResponse({'success': False, 'error': f'Error BD: {exc}'}, status=400)

        except ValidationError as exc:
            _audit_sale_event(
                request,
                VentaAuditLog.EVENT_CREATE_REJECTED,
                VentaAuditLog.STATUS_BLOCKED,
                message="Validacion bloqueada al crear venta.",
                payload={"error": str(exc)}
            )
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)

        except Exception as exc:
            _audit_sale_event(
                request,
                VentaAuditLog.EVENT_CREATE_REJECTED,
                VentaAuditLog.STATUS_ERROR,
                message="Error no controlado al crear venta.",
                payload={"error": str(exc)}
            )
            return JsonResponse(
                {'success': False, 'error': 'Error interno al procesar la venta.'},
                status=500
            )

        jugadas_resumen = []
        for jugada in jugadas_validadas:
            jugadas_resumen.append({
                'numero': jugada["numero"],
                'combi': jugada["combi"],
                'monto': int(jugada["monto"]),
            })

        resumen_venta = {
            'vendedor': request.user.username,
            'loterias': [lot.nombre for lot in loterias_seleccionadas],
            'jugadas': jugadas_resumen,
            'total': sum(j["monto"] for j in jugadas_validadas) * loterias_count
        }

        _audit_sale_event(
            request,
            VentaAuditLog.EVENT_CREATE_SUCCESS,
            VentaAuditLog.STATUS_SUCCESS,
            message="Venta creada correctamente.",
            venta=ventas_creadas[0] if ventas_creadas else None,
            payload={
                "venta_referencia_id": codigo_venta,
                "ventas_ids": [v.id for v in ventas_creadas],
                "loterias_ids": [lot.id for lot in loterias_seleccionadas],
                "jugadas_count": len(ventas_creadas),
                "total": sum(v.monto for v in ventas_creadas) * loterias_count,
            }
        )

        return JsonResponse({
            'success': True,
            'resumen_venta': {
                'codigo': codigo_venta,
                'vendedor': request.user.username,
                'loterias': [lot.nombre for lot in loterias_seleccionadas],
                'jugadas': [{
                    'numero': v.numero,
                    'combi': v.combi,
                    'monto': v.monto
                } for v in ventas_creadas],
                'total': sum(v.monto for v in ventas_creadas) * loterias_count
            }
        }, status=201)
    # ======================= GET ==========================
    return render(
        request,
        'core/ventas.html',
        {
            'loterias':            loterias,
            'dia_actual_nombre':   dia_actual_nombre_es,
            'fecha_actual':        ahora.date(),
            'current_time':        ahora.time(),
        }
    )

# Vista para listar ventas con filtros y paginación
@login_required(login_url='/login-required/')
def ventas_list(request):
    """
    Listado paginado de ventas para un día dado.
    - Los usuarios no-admin sólo ven sus ventas.
    - Admins pueden filtrar por vendedor.
    - Search ahora aplica tanto a 'numero' como a 'combi'.
    - Se calcula el total multiplicando monto × cantidad de loterías.
    """
    search       = request.GET.get('search', '')
    default_date = str(timezone.localtime(timezone.now()).date())
    filter_date  = request.GET.get('start_date', default_date)
    vendedor_id  = request.GET.get('vendedor', '')

    # 1. Base queryset (sólo ventas del día filtrado)
    ventas_qs = Venta.objects.filter(fecha_venta__date=filter_date)

    # 2. Filtros de usuario
    if not request.user.is_staff:
        ventas_qs = ventas_qs.filter(vendedor=request.user)
    if request.user.is_staff and vendedor_id:
        ventas_qs = ventas_qs.filter(vendedor_id=vendedor_id)

    # 3. Búsqueda: número **o** combi
    if search:
        ventas_qs = ventas_qs.filter(
            Q(numero__icontains=search) | Q(combi__icontains=search)
        )

    # 4. Optimización N+1
    ventas_qs = (
        ventas_qs
          .select_related('vendedor')
          .prefetch_related('loterias')
          .annotate(count_loterias=Count('loterias'))
          .order_by('-fecha_venta')          # opcional, las más recientes primero
    )

    # 5. Total general (en BD)
    total_ventas = ventas_qs.aggregate(
        total=Sum(F('monto') * F('count_loterias'))
    )['total'] or 0

    # 6. Paginación
    paginator = Paginator(ventas_qs, 100)
    page_obj  = paginator.get_page(request.GET.get('page'))

    # 7. Vendedores (sólo para admins)
    vendedores = (
        Venta.objects
             .values('vendedor__id', 'vendedor__username')
             .distinct()
             .order_by('vendedor__username')   # 👈 ordenados alfabéticamente
        if request.user.is_staff else []
    )

    return render(
        request,
        'core/ventas_list.html',
        {
            'ventas':       page_obj,
            'total_ventas': total_ventas,
            'search':       search,
            'filter_date':  filter_date,
            'vendedores':   vendedores,
            'vendedor_id':  vendedor_id,
        }
    )

# Vista para mostrar el histórico de ventas
@login_required
def historico_ventas(request):
    if request.user.is_staff:
        ventas = Venta.objects.all()
    else:
        ventas = Venta.objects.filter(vendedor=request.user)

    resumen_ventas = ventas.values('fecha_venta__date', 'vendedor__username').annotate(
        total_venta=Sum('monto')
    ).order_by('-fecha_venta__date')

    return render(request, 'core/historico_ventas.html', {
        'resumen_ventas': resumen_ventas,
    })

@login_required
def premios(request):
    """
    Calcula y PERSISTE los premios para una fecha.
    Reglas:
      - 2 cifras (coincide 2 últimos): * 60
      - 3 cifras (coincide 3 últimos): * 550
      - 4 cifras (coincide exacto):    * 4500
    Si el usuario es admin (staff) ve todas las ventas/premios; de lo contrario, solo los suyos.
    """
    from datetime import datetime
    from django.http import Http404
    from django.utils import timezone
    from django.db import transaction
    from django.db.models import Sum

    from core.models import Dia, Loteria, Resultado, Venta, Premio  # ajusta imports a tu estructura

    # -------- Fecha filtro --------
    fecha_param = request.GET.get('fecha')
    ahora = timezone.localtime(timezone.now())
    if fecha_param:
        try:
            fecha = datetime.strptime(fecha_param, '%Y-%m-%d').date()
        except ValueError:
            fecha = ahora.date()
    else:
        fecha = ahora.date()

    # -------- Día ES --------
    dia_actual_nombre_en = fecha.strftime('%A')
    dias_map = {
        'Monday': 'Lunes',
        'Tuesday': 'Martes',
        'Wednesday': 'Miércoles',
        'Thursday': 'Jueves',
        'Friday': 'Viernes',
        'Saturday': 'Sábado',
        'Sunday': 'Domingo',
    }
    dia_nombre_es = dias_map.get(dia_actual_nombre_en)
    try:
        dia_obj = Dia.objects.get(nombre=dia_nombre_es)
    except Dia.DoesNotExist:
        raise Http404(f"No se ha encontrado el día {dia_nombre_es}")

    # -------- Loterías que juegan ese día --------
    loterias = Loteria.objects.filter(dias_juego=dia_obj)

    # -------- Cálculo y persistencia --------
    # Hacemos todo atómico para consistencia si hay múltiples upserts.
    with transaction.atomic():
        for lot in loterias:
            resultado_obj = Resultado.objects.filter(loteria=lot, fecha=fecha).first()
            if not resultado_obj:
                continue

            winning_number = str(resultado_obj.resultado).zfill(4).strip()

            if request.user.is_staff:
                ventas_qs = Venta.objects.filter(fecha_venta__date=fecha, loterias=lot)
            else:
                ventas_qs = Venta.objects.filter(
                    fecha_venta__date=fecha,
                    loterias=lot,
                    vendedor=request.user
                )

            for venta in ventas_qs.select_related('vendedor'):
                # robustez: si numero es int, casteamos
                sale_number = str(venta.numero or '').strip()
                if len(sale_number) not in (2, 3, 4):
                    continue

                # Coincidencia por últimos dígitos
                if sale_number == winning_number[-len(sale_number):]:
                    if len(sale_number) == 2:
                        multiplier = 60
                    elif len(sale_number) == 3:
                        multiplier = 550
                    else:  # 4
                        multiplier = 4500

                    premio_valor = int(venta.monto) * multiplier

                    # Persistir sin duplicar (idempotente por venta/lotería/fecha)
                    Premio.objects.update_or_create(
                        venta=venta,
                        loteria=lot,
                        fecha=fecha,
                        defaults={
                            'vendedor': venta.vendedor,
                            'numero': sale_number,
                            'valor': int(venta.monto),  # valor apostado
                            'cifras': len(sale_number),
                            'premio': premio_valor,     # payout
                        }
                    )

    # -------- Consulta para mostrar en el template (desde BD) --------
    if request.user.is_staff:
        premios_qs = Premio.objects.filter(fecha=fecha, loteria__in=loterias).select_related('loteria', 'vendedor')
    else:
        premios_qs = Premio.objects.filter(
            fecha=fecha,
            loteria__in=loterias,
            vendedor=request.user
        ).select_related('loteria', 'vendedor')

    # -------- Totales y conteo --------
    total_premios = premios_qs.aggregate(total=Sum('premio'))['total'] or 0
    premios_count = premios_qs.count()

    # -------- Shape para el template (alineado con tu HTML) --------
    premios_list = [
        {
            'loteria': p.loteria,
            'imagen': getattr(p.loteria, 'imagen', None),
            'imagen_2x': getattr(p.loteria, 'imagen_2x', None),
            'nombre': getattr(p.loteria, 'nombre', str(p.loteria)),
            'numero_ganador': p.numero,
            'valor': p.premio,            # lo que muestras en la UI (payout)
            'vendedor': p.vendedor,
            'cifras': p.cifras,
            'valor_apostado': p.valor,    # por si necesitas mostrarlo más adelante
        }
        for p in premios_qs
    ]
    # ... después de construir premios_qs
    total_premios = premios_qs.aggregate(total=Sum('premio'))['total'] or 0
    premios_count = premios_qs.count()


    context = {
    'premios_list': premios_list,
    'total_premios': total_premios,      # 👈 importante
    'premios_count': premios_count,      # 👈 opcional para mostrar cantidad
    'fecha': fecha,
    'fecha_actual': timezone.localdate(),# 👈 para el input date
    'es_admin': request.user.is_staff,
}
    return render(request, 'core/premios.html', context)


@user_passes_test(lambda u: u.is_superuser)
@login_required
def premios_reporte_rango(request):
    """
    Reporte de premios por rango de fechas, agrupado por vendedor.
    No altera el modulo existente de premios por fecha puntual.
    """
    hoy = timezone.localdate()

    fecha_inicio_raw = request.GET.get('fecha_inicio')
    fecha_fin_raw = request.GET.get('fecha_fin')

    fecha_fin = parse_date(fecha_fin_raw) if fecha_fin_raw else hoy
    fecha_inicio = parse_date(fecha_inicio_raw) if fecha_inicio_raw else (fecha_fin - timedelta(days=6))

    # Sanitizar rango para evitar errores de usuario o fechas futuras
    if not fecha_fin:
        fecha_fin = hoy
    if not fecha_inicio:
        fecha_inicio = fecha_fin - timedelta(days=6)

    if fecha_fin > hoy:
        fecha_fin = hoy
    if fecha_inicio > hoy:
        fecha_inicio = hoy

    if fecha_inicio > fecha_fin:
        fecha_inicio, fecha_fin = fecha_fin, fecha_inicio

    premios_qs = Premio.objects.filter(
        fecha__range=(fecha_inicio, fecha_fin)
    )

    if not request.user.is_staff:
        premios_qs = premios_qs.filter(vendedor=request.user)

    resumen_vendedores_qs = (
        premios_qs
        .values(
            'vendedor_id',
            'vendedor__username',
            'vendedor__first_name',
            'vendedor__last_name',
        )
        .annotate(
            total_premio=Coalesce(Sum('premio'), 0, output_field=IntegerField()),
            total_apostado=Coalesce(Sum('valor'), 0, output_field=IntegerField()),
            cantidad_premios=Count('id'),
            loterias_distintas=Count('loteria', distinct=True),
            dias_con_premios=Count('fecha', distinct=True),
        )
        .order_by('-total_premio', 'vendedor__username')
    )

    rows = []
    for item in resumen_vendedores_qs:
        full_name = f"{(item.get('vendedor__first_name') or '').strip()} {(item.get('vendedor__last_name') or '').strip()}".strip()
        vendedor_nombre = full_name or (item.get('vendedor__username') or f"Vendedor {item.get('vendedor_id')}")
        rows.append({
            'vendedor_id': item.get('vendedor_id'),
            'vendedor_nombre': vendedor_nombre,
            'username': item.get('vendedor__username') or '',
            'total_premio': int(item.get('total_premio') or 0),
            'total_apostado': int(item.get('total_apostado') or 0),
            'cantidad_premios': int(item.get('cantidad_premios') or 0),
            'loterias_distintas': int(item.get('loterias_distintas') or 0),
            'dias_con_premios': int(item.get('dias_con_premios') or 0),
        })

    totales = premios_qs.aggregate(
        total_premios=Coalesce(Sum('premio'), 0, output_field=IntegerField()),
        total_apostado=Coalesce(Sum('valor'), 0, output_field=IntegerField()),
        cantidad_premios=Count('id'),
        vendedores=Count('vendedor', distinct=True),
        loterias=Count('loteria', distinct=True),
    )
    totales = {k: int(v or 0) for k, v in totales.items()}

    chart_categories = [row['vendedor_nombre'] for row in rows]
    chart_total_premios = [row['total_premio'] for row in rows]
    context = {
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'rows': rows,
        'totales': totales,
        'chart_categories': chart_categories,
        'chart_total_premios': chart_total_premios,
        'es_admin': request.user.is_staff,
        'rango_dias': (fecha_fin - fecha_inicio).days + 1,
        'fecha_max': hoy,
    }
    return render(request, 'core/premios_reporte_rango.html', context)


@user_passes_test(lambda u: u.is_superuser)
@login_required
def registro_resultados(request):
    """
    Vista para:
      • Registrar/editar resultados manualmente (POST).
      • Importar resultados desde la API pública (?importar=1).
    """
    ahora = timezone.localtime(timezone.now())

    # ---------- 1. Fecha seleccionada ----------
    fecha_param = request.GET.get('fecha')
    if fecha_param:
        try:
            fecha_actual = datetime.strptime(fecha_param, '%Y-%m-%d').date()
        except ValueError:
            fecha_actual = ahora.date()
    else:
        fecha_actual = ahora.date()

    # ---------- 2. Importar desde API ----------
    if request.GET.get("importar"):                               # <<< NUEVO >>>
        resumen = importar_resultados(fecha_actual, user=request.user) 
        if "error" in resumen:
            messages.error(request, f"Error al importar: {resumen['error']}")
        else:
            messages.success(
                request,
                f"Importados: {resumen['importados']} "
                f"(omitidos: {resumen['omitidos']}, errores: {resumen['errores']})"
            )
        # Redirige para refrescar la página y evitar reenvío del parámetro
        return redirect(f"{request.path}?fecha={fecha_actual.isoformat()}")

    # ---------- 3. Día de la semana ----------
    dias_map = {
        'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
        'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado',
        'Sunday': 'Domingo',
    }
    dia_actual_nombre_es = dias_map.get(fecha_actual.strftime('%A'))

    try:
        dia_obj = Dia.objects.get(nombre=dia_actual_nombre_es)
    except Dia.DoesNotExist:
        raise Http404(f"No se ha encontrado un día con el nombre {dia_actual_nombre_es}")

    # ---------- 4. Loterías del día ----------
    loterias = Loteria.objects.filter(dias_juego=dia_obj).order_by('nombre')

    # ---------- 5. Diccionario de resultados actuales ----------
    resultados_dict = {}
    for lot in loterias:
        resultado_obj = Resultado.objects.filter(loteria=lot, fecha=fecha_actual).first()
        resultados_dict[lot.id] = resultado_obj.resultado if resultado_obj else None

    # ---------- 6. Registro manual (POST) ----------
    if request.method == 'POST':
        fecha_post = request.POST.get('fecha')
        if fecha_post:
            try:
                fecha_actual = datetime.strptime(fecha_post, '%Y-%m-%d').date()
            except ValueError:
                pass

        for lot in loterias:
            key   = f"resultado_{lot.id}"
            valor = request.POST.get(key)
            if valor:
                try:
                    valor_int = int(valor)
                except ValueError:
                    continue
                Resultado.objects.update_or_create(
                    loteria=lot,
                    fecha=fecha_actual,
                    defaults={
                        'resultado': valor_int,
                        'registrado_por': request.user
                    }
                )
            else:
                # Si el campo se deja vacío, elimina el registro existente (opcional)
                Resultado.objects.filter(loteria=lot, fecha=fecha_actual).delete()

        messages.success(request, "Resultados guardados correctamente.")   # <<< NUEVO >>>
        return redirect(f"{request.path}?fecha={fecha_actual.isoformat()}") # <<< cambia redirect

    # ---------- 7. Render ----------
    return render(
        request,
        'core/registro_resultados.html',
        {
            'loterias':           loterias,
            'resultados_dict':    resultados_dict,
            'fecha_actual':       fecha_actual,
            'dia_actual_nombre':  dia_actual_nombre_es,
        }
    )

# Vista para usuarios normales: Mostrar Resultados
@login_required
def resultados(request):
    from datetime import datetime
    # Obtener la fecha actual (por defecto)
    ahora = timezone.localtime(timezone.now())
    fecha_param = request.GET.get('fecha')
    if fecha_param:
        try:
            fecha_actual = datetime.strptime(fecha_param, '%Y-%m-%d').date()
        except ValueError:
            fecha_actual = ahora.date()
    else:
        fecha_actual = ahora.date()

    # Convertir la fecha a nombre del día en inglés y luego a español
    dia_actual_nombre_en = fecha_actual.strftime('%A')
    dias_map = {
        'Monday': 'Lunes',
        'Tuesday': 'Martes',
        'Wednesday': 'Miércoles',
        'Thursday': 'Jueves',
        'Friday': 'Viernes',
        'Saturday': 'Sábado',
        'Sunday': 'Domingo',
    }
    dia_actual_nombre_es = dias_map.get(dia_actual_nombre_en)

    # Obtener el objeto Dia correspondiente
    try:
        dia_obj = Dia.objects.get(nombre=dia_actual_nombre_es)
    except Dia.DoesNotExist:
        raise Http404(f"No se ha encontrado un día con el nombre {dia_actual_nombre_es}")

    # Filtrar las loterías que se juegan el día seleccionado
    loterias = Loteria.objects.filter(dias_juego=dia_obj).order_by('nombre')

    # Construir la lista de resultados: para cada lotería se consulta el resultado registrado para la fecha filtrada
    resultados_list = []
    for lot in loterias:
        resultado_obj = Resultado.objects.filter(loteria=lot, fecha=fecha_actual).first()
        resultados_list.append({
            'loteria': lot,
            'resultado': resultado_obj.resultado if resultado_obj else None,
        })

    context = {
         'loterias_resultados': resultados_list,
         'fecha_actual': fecha_actual,
         'dia_actual_nombre': dia_actual_nombre_es,
    }
    return render(request, 'core/resultados.html', context)

@user_passes_test(lambda u: u.is_staff)
@login_required
def reporte_descargas(request):
    # Fecha filtro
    fecha_param = request.GET.get('fecha')
    hoy = timezone.localtime(timezone.now()).date()
    try:
        fecha = datetime.strptime(fecha_param, '%Y-%m-%d').date() if fecha_param else hoy
    except ValueError:
        fecha = hoy

    base = (
        Venta.objects
        .filter(fecha_venta__date=fecha)
        .annotate(
            numero_clean=Trim('numero'),
        )
        .exclude(Q(numero_clean__isnull=True) | Q(numero_clean=''))
        .exclude(loterias__isnull=True)
    )

    report = (
        base.values('loterias__nombre', 'numero_clean')
            .annotate(
                veces_apostado=Count('id', distinct=True),
                total_ventas=Coalesce(Sum('monto'), 0, output_field=IntegerField()),
            )
            .order_by('-total_ventas')
    )

    return render(request, 'core/reporte_descargas.html', {
        'fecha': fecha,
        'report': report,
    })

def login_required_view(request):
    return render(request, 'core/login_required.html')

@csrf_exempt
def importar_resultados_api(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    token_recibido = request.headers.get("Authorization")
    token_esperado = os.getenv("IMPORT_TOKEN")  # o reemplaza por el string literal

    if not token_recibido or token_recibido != f"Token 1234superclaveAPI5678":
        return JsonResponse({"error": "No autorizado"}, status=401)

    fecha_objetivo = localtime(now()).date() - timedelta(days=1)

    User = get_user_model()
    try:
        user = User.objects.get(username="daniel")
    except User.DoesNotExist:
        return JsonResponse({"error": "Usuario 'daniel' no encontrado"}, status=500)

    resultado = importar_resultados(fecha_objetivo, user=user)
    return JsonResponse({"resultado": resultado}, status=200)

@csrf_exempt
def importar_resultados_via_get(request):
    token_recibido = request.GET.get("token")
    token_esperado = os.getenv("IMPORT_TOKEN")

    if token_recibido != token_esperado:
        return JsonResponse({"error": "No autorizado"}, status=401)

    fecha = localtime(now()).date() - timedelta(days=1)
    User = get_user_model()

    try:
        user = User.objects.get(username="daniel")
    except User.DoesNotExist:
        return JsonResponse({"error": "Usuario no encontrado"}, status=500)

    resultado = importar_resultados(fecha, user=user)
    return JsonResponse({"resultado": resultado})

RETENCION_PCT = Decimal('0.10')   # 10%
COMISION_PCT  = Decimal('0.35')   # 35%

def _round_cop(n) -> int:
    if not isinstance(n, Decimal):
        n = Decimal(n)
    return int(n.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

@user_passes_test(lambda u: u.is_superuser)
def reportes(request):
    # --- fechas robustas ---
    start_date = request.GET.get('start_date')
    end_date   = request.GET.get('end_date')
    try:
        if start_date and end_date:
            start = parse_date(start_date)
            end   = parse_date(end_date)
            if not start or not end:
                raise ValueError("fechas inválidas")
        else:
            raise ValueError("faltan fechas")
    except Exception:
        start = end = timezone.localdate()
        start_date = end_date = str(start)

    # --- por venta: monto × #loterías ---
    ventas_qs = (
        Venta.objects
        .annotate(fecha=TruncDate('fecha_venta'))
        .filter(fecha__range=(start, end))
        .select_related('vendedor')
        .prefetch_related('loterias')
        .annotate(count_loterias=Count('loterias', distinct=True))
        .annotate(total_bruta=ExpressionWrapper(F('monto') * F('count_loterias'),
                                                output_field=IntegerField()))
        .values('vendedor__username', 'total_bruta')
    )

    # --- sumar por vendedor en Python (evita aggregate-over-aggregate) ---
    sumas_brutas = defaultdict(int)
    for v in ventas_qs:
        sumas_brutas[v['vendedor__username']] += int(v['total_bruta'] or 0)

    # construir filas + totales y métricas derivadas
    rows = []
    labels, data = [], []

    total_general_bruta = total_general_neta = 0
    total_general_comision = total_general_liquidacion = 0

    for vendedor, bruta in sumas_brutas.items():
        neta = _round_cop(Decimal(bruta) * (Decimal('1') - RETENCION_PCT))
        comision = _round_cop(Decimal(neta) * COMISION_PCT)
        liquidacion = neta - comision

        rows.append({
            'vendedor': vendedor,
            'total': bruta,
            'venta_neta': neta,
            'comision': comision,
            'liquidacion': liquidacion,
        })

        labels.append(vendedor)
        data.append(bruta)
        total_general_bruta += bruta
        total_general_neta += neta
        total_general_comision += comision
        total_general_liquidacion += liquidacion

    rows.sort(key=lambda r: r['total'], reverse=True)

    return render(request, 'core/reportes.html', {
        'labels': labels,
        'data': data,
        'rows': rows,
        'total_general': total_general_bruta,
        'total_general_neta': total_general_neta,
        'total_general_comision': total_general_comision,
        'total_general_liquidacion': total_general_liquidacion,
        'start_date': start_date,
        'end_date': end_date,
    })


@user_passes_test(lambda u: u.is_superuser)
@login_required
def reporte_ventas_vs_premios(request):
    """
    Reporte comparativo por vendedor:
    - Venta bruta
    - Venta neta (bruta - 10%)
    - Liquidacion (venta neta - 35%)
    - Premios pagados en el mismo rango
    """
    hoy = timezone.localdate()
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    try:
        if start_date and end_date:
            start = parse_date(start_date)
            end = parse_date(end_date)
            if not start or not end:
                raise ValueError("fechas invalidas")
        else:
            raise ValueError("faltan fechas")
    except Exception:
        end = hoy
        start = hoy - timedelta(days=6)
        start_date = str(start)
        end_date = str(end)

    if start > end:
        start, end = end, start
        start_date, end_date = str(start), str(end)

    if end > hoy:
        end = hoy
        end_date = str(end)
        if start > end:
            start = end
            start_date = str(start)

    # --- Ventas por vendedor (monto x # loterias) ---
    ventas_qs = (
        Venta.objects
        .annotate(fecha=TruncDate('fecha_venta'))
        .filter(fecha__range=(start, end))
        .select_related('vendedor')
        .prefetch_related('loterias')
        .annotate(count_loterias=Count('loterias', distinct=True))
        .annotate(
            total_bruta=ExpressionWrapper(
                F('monto') * F('count_loterias'),
                output_field=IntegerField()
            )
        )
        .values(
            'vendedor_id',
            'vendedor__username',
            'vendedor__first_name',
            'vendedor__last_name',
            'total_bruta',
        )
    )

    ventas_por_vendedor = {}
    for v in ventas_qs:
        vendedor_id = v.get('vendedor_id')
        if not vendedor_id:
            continue

        item = ventas_por_vendedor.setdefault(vendedor_id, {
            'vendedor_id': vendedor_id,
            'username': v.get('vendedor__username') or '',
            'first_name': (v.get('vendedor__first_name') or '').strip(),
            'last_name': (v.get('vendedor__last_name') or '').strip(),
            'venta_bruta': 0,
        })
        item['venta_bruta'] += int(v.get('total_bruta') or 0)

    # --- Premios por vendedor (mismo rango) ---
    premios_qs = (
        Premio.objects
        .filter(fecha__range=(start, end))
        .values(
            'vendedor_id',
            'vendedor__username',
            'vendedor__first_name',
            'vendedor__last_name',
        )
        .annotate(
            total_premios=Coalesce(Sum('premio'), 0, output_field=IntegerField()),
            cantidad_premios=Count('id'),
        )
    )

    premios_por_vendedor = {}
    for p in premios_qs:
        vendedor_id = p.get('vendedor_id')
        if not vendedor_id:
            continue

        premios_por_vendedor[vendedor_id] = {
            'vendedor_id': vendedor_id,
            'username': p.get('vendedor__username') or '',
            'first_name': (p.get('vendedor__first_name') or '').strip(),
            'last_name': (p.get('vendedor__last_name') or '').strip(),
            'total_premios': int(p.get('total_premios') or 0),
            'cantidad_premios': int(p.get('cantidad_premios') or 0),
        }

    # --- Merge de vendedores (con ventas y/o con premios) ---
    all_vendor_ids = set(ventas_por_vendedor.keys()) | set(premios_por_vendedor.keys())

    rows = []
    total_bruta = total_neta = total_liquidacion = total_premios = total_diferencia = 0

    for vendor_id in all_vendor_ids:
        venta_data = ventas_por_vendedor.get(vendor_id, {})
        premio_data = premios_por_vendedor.get(vendor_id, {})

        username = venta_data.get('username') or premio_data.get('username') or ''
        first_name = venta_data.get('first_name') or premio_data.get('first_name') or ''
        last_name = venta_data.get('last_name') or premio_data.get('last_name') or ''
        full_name = f"{first_name} {last_name}".strip()
        vendedor_nombre = full_name or username or f"Vendedor {vendor_id}"

        bruta = int(venta_data.get('venta_bruta') or 0)
        neta = _round_cop(Decimal(bruta) * (Decimal('1') - RETENCION_PCT))
        comision = _round_cop(Decimal(neta) * COMISION_PCT)
        liquidacion = neta - comision
        premios_total = int(premio_data.get('total_premios') or 0)
        diferencia = liquidacion - premios_total
        cantidad_premios = int(premio_data.get('cantidad_premios') or 0)

        rows.append({
            'vendedor_id': vendor_id,
            'vendedor': vendedor_nombre,
            'username': username,
            'venta_bruta': bruta,
            'venta_neta': neta,
            'liquidacion': liquidacion,
            'premios': premios_total,
            'cantidad_premios': cantidad_premios,
            'diferencia': diferencia,
        })

        total_bruta += bruta
        total_neta += neta
        total_liquidacion += liquidacion
        total_premios += premios_total
        total_diferencia += diferencia

    rows.sort(key=lambda r: max(r['liquidacion'], r['premios']), reverse=True)

    chart_labels = [r['vendedor'] for r in rows]
    chart_liquidaciones = [r['liquidacion'] for r in rows]
    chart_premios = [r['premios'] for r in rows]

    return render(request, 'core/reporte_ventas_vs_premios.html', {
        'start_date': str(start),
        'end_date': str(end),
        'fecha_max': hoy,
        'rows': rows,
        'chart_labels': chart_labels,
        'chart_liquidaciones': chart_liquidaciones,
        'chart_premios': chart_premios,
        'total_bruta': total_bruta,
        'total_neta': total_neta,
        'total_liquidacion': total_liquidacion,
        'total_premios': total_premios,
        'total_diferencia': total_diferencia,
    })

