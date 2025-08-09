from django.shortcuts import render, HttpResponse, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.http import Http404, JsonResponse
from django.contrib.auth.views import LoginView
from .models import Loteria, Dia, Venta, Resultado
from django.db import transaction, IntegrityError
from core.utils import importar_resultados  # ← añade esta línea
from django.contrib import messages
from django.db.models import Case, When, BooleanField, Sum, Count, F, Q, ExpressionWrapper,IntegerField, FloatField,Subquery, OuterRef
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
from django.db.models.functions import Cast, Coalesce,Trim  
import os

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
        numeros      = request.POST.getlist('numero')
        montos       = request.POST.getlist('monto')
        combis       = request.POST.getlist('combi')

        # --- Validaciones de longitud ---
        if not (len(numeros) == len(montos) == len(combis)):
            return JsonResponse(
                {'success': False,
                 'error': 'Los números, montos y combis no coinciden.'},
                status=400
            )

        # --- Loterías seleccionadas ---
        loterias_seleccionadas = Loteria.objects.filter(id__in=loterias_ids)
        if not loterias_seleccionadas.exists():
            return JsonResponse(
                {'success': False, 'error': 'Loterías no válidas.'},
                status=400
            )

        # --- Horario de cada lotería ---
        for lot in loterias_seleccionadas:
            if not (lot.hora_inicio <= ahora.time() <= lot.hora_fin):
                return JsonResponse(
                    {'success': False,
                     'error': f'La hora de juego para {lot.nombre} ha finalizado.'},
                    status=400
                )

        # --- Validación fila a fila ---
        for idx, (numero, monto, combi) in enumerate(
                zip(numeros, montos, combis), start=1):
            numero = numero.strip()
            combi  = combi.strip()
            monto  = monto.strip()

            # Monto obligatorio y > 0
            if monto == '' or float(monto) <= 0:
                return JsonResponse(
                    {'success': False,
                     'error': f'Fila {idx}: el monto es obligatorio y debe ser mayor que 0.'},
                    status=400
                )

            # Debe existir numero o combi
            if numero == '' and combi == '':
                return JsonResponse(
                    {'success': False,
                     'error': f'Fila {idx}: ingrese Número o Combi.'},
                    status=400
                )

        # --- Crear ventas dentro de una transacción ---
        try:
            with transaction.atomic():
                ventas_creadas = []

                for numero, monto, combi in zip(numeros, montos, combis):
                    venta = Venta.objects.create(
                        vendedor=request.user,
                        numero=numero.strip(),
                        monto=int(monto),
                        fecha_venta=ahora,
                        combi=int(combi) if combi.strip() else None
                    )
                    venta.loterias.set(loterias_seleccionadas)
                    ventas_creadas.append(venta)

                # ID de referencia de la venta (la primera creada)
                codigo_venta = ventas_creadas[0].id if ventas_creadas else None

        except IntegrityError as exc:   # Ej. unique constraint si la añades
            return JsonResponse(
                {'success': False, 'error': f'Error BD: {exc}'}, status=400
            )

        # Todo OK
        # === Construcción del resumen para WhatsApp ===
        jugadas_resumen = []

        for numero, monto, combi in zip(numeros, montos, combis):
            jugadas_resumen.append({
                'numero': numero.strip(),
                'combi': combi.strip(),
                'monto': int(monto)
            })

        resumen_venta = {
            'vendedor': request.user.username,
            'loterias': [lot.nombre for lot in loterias_seleccionadas],
            'jugadas': jugadas_resumen,
            'total': sum(int(m) for m in montos) * loterias_seleccionadas.count()
        }

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
        'total': sum(v.monto for v in ventas_creadas) * loterias_seleccionadas.count()
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
    Vista que calcula y muestra los premios para una fecha dada.
    Se consideran las ventas del día para cada lotería y se verifica si el
    número apostado coincide (por sus últimos dígitos) con el resultado registrado.
    Multiplicador:
      - Si la venta tiene 2 cifras y coincide con los dos últimos dígitos: * 60
      - Si la venta tiene 3 cifras y coincide con los tres últimos dígitos: * 550
      - Si la venta tiene 4 cifras y coincide exactamente: * 4500
    """
    from datetime import datetime
    from django.http import Http404
    from django.utils import timezone

    # Obtener la fecha del filtro (GET), si no se indica se usa la fecha actual
    fecha_param = request.GET.get('fecha')
    ahora = timezone.localtime(timezone.now())
    if fecha_param:
        try:
            fecha = datetime.strptime(fecha_param, '%Y-%m-%d').date()
        except ValueError:
            fecha = ahora.date()
    else:
        fecha = ahora.date()

    # Convertir la fecha a nombre del día en inglés y luego a español
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

    # Filtrar las loterías que se juegan ese día
    loterias = Loteria.objects.filter(dias_juego=dia_obj)

    premios_list = []
    for lot in loterias:
        # Se obtiene el resultado registrado para la lotería en la fecha indicada
        resultado_obj = Resultado.objects.filter(loteria=lot, fecha=fecha).first()
        if resultado_obj:
            # El número ganador siempre es de 4 cifras
            winning_number = str(resultado_obj.resultado).zfill(4).strip()

            # Filtrar las ventas: si es administrador (staff) se ven todas; sino, solo las del usuario logueado
            if request.user.is_staff:
                ventas = Venta.objects.filter(fecha_venta__date=fecha, loterias=lot)
            else:
                ventas = Venta.objects.filter(fecha_venta__date=fecha, loterias=lot, vendedor=request.user)
            
            for venta in ventas:
                sale_number = venta.numero.strip()
                # Solo se consideran ventas con 2, 3 o 4 dígitos
                if len(sale_number) not in (2, 3, 4):
                    continue
                # Se extrae la porción final del número ganador según la cantidad de dígitos de la venta
                if sale_number == winning_number[-len(sale_number):]:
                    if len(sale_number) == 2:
                        multiplier = 60
                    elif len(sale_number) == 3:
                        multiplier = 550
                    elif len(sale_number) == 4:
                        multiplier = 4500
                    else:
                        multiplier = 0
                    premio_valor = venta.monto * multiplier
                    premios_list.append({
                        'loteria': lot,
                        'imagen': lot.imagen,
                        'nombre': lot.nombre,
                        'numero_ganador': sale_number,
                        'valor': premio_valor,
                        'vendedor': venta.vendedor, # Vendedor de la venta
                    })
    context = {
        'premios_list': premios_list,
        'fecha': fecha,  # En formato YYYY-MM-DD
        'es_admin': request.user.is_staff,
    }
    return render(request, 'core/premios.html', context)

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

    # Subquery: cantidad de loterías por venta (en la tabla through)
    through = Venta.loterias.through  # core_venta_loterias
    loterias_count_sq = (
        through.objects
        .filter(venta_id=OuterRef('pk'))
        .values('venta_id')
        .annotate(c=Count('loteria_id', distinct=True))
        .values('c')[:1]
    )

    base = (
        Venta.objects
        .filter(fecha_venta__date=fecha)
        .annotate(
            numero_clean=Trim('numero'),
            cantidad_loterias=Coalesce(Subquery(loterias_count_sq, output_field=IntegerField()), 1),
        )
        .exclude(Q(numero_clean__isnull=True) | Q(numero_clean=''))
        .annotate(
            valor_ajustado=ExpressionWrapper(
                Cast(F('monto'), FloatField()) / Cast(F('cantidad_loterias'), FloatField()),
                output_field=FloatField()
            )
        )
    )

    report = (
        base.values('loterias__nombre', 'numero_clean')
            .annotate(
                veces_apostado=Count('id'),
                total_ventas=Sum('valor_ajustado'),
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

@user_passes_test(lambda u: u.is_staff)
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
    except:
        start = end = timezone.localdate()
        start_date = end_date = str(start)

    # --- queryset base con total por venta ---
    ventas_qs = (
        Venta.objects
        .annotate(fecha=TruncDate('fecha_venta'))
        .filter(fecha__range=(start, end))
        .select_related('vendedor')
        .prefetch_related('loterias')
        .annotate(count_loterias=Count('loterias'))
        .annotate(total_venta=ExpressionWrapper(F('monto') * F('count_loterias'),
                                                output_field=IntegerField()))
        .values('vendedor__username', 'total_venta')
    )

    # --- agregamos por vendedor en Python ---
    resumen_por_vendedor = defaultdict(int)
    for v in ventas_qs:
        resumen_por_vendedor[v['vendedor__username']] += v['total_venta']

    # datos para la gráfica
    labels = list(resumen_por_vendedor.keys())
    data   = list(resumen_por_vendedor.values())

    # --- NUEVO: filas de tabla y total general ---
    rows = [{'vendedor': k, 'total': v} for k, v in resumen_por_vendedor.items()]
    rows.sort(key=lambda r: r['total'], reverse=True)
    total_general = sum(data) if data else 0

    return render(request, 'core/reportes.html', {
        'labels': labels,
        'data': data,
        'rows': rows,                     # 👈 tabla
        'total_general': total_general,   # 👈 total
        'start_date': start_date,
        'end_date': end_date,
    })