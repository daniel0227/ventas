from django.shortcuts import render, HttpResponse, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone
from django.http import Http404, JsonResponse
from django.contrib.auth.views import LoginView
from .models import Loteria, Dia, Venta, Resultado
from django.db.models import Case, When, BooleanField, Sum, Count, F
from django.utils.timezone import localtime, now, make_aware
from .forms import VentaForm
from django.core.paginator import Paginator
from pytz import timezone as pytz_timezone
from datetime import date, timedelta

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
def crear_venta(request):
    ahora = timezone.localtime(timezone.now())

    try:
        # Mapeo de días
        dias_map = {
            'Monday': 'Lunes',
            'Tuesday': 'Martes',
            'Wednesday': 'Miércoles',
            'Thursday': 'Jueves',
            'Friday': 'Viernes',
            'Saturday': 'Sábado',
            'Sunday': 'Domingo',
        }

        # Obtener el nombre del día actual
        dia_actual_nombre_en = ahora.strftime('%A')
        dia_actual_nombre_es = dias_map.get(dia_actual_nombre_en)
        print("Día actual (es):", dia_actual_nombre_es)

        if not dia_actual_nombre_es:
            return JsonResponse({'success': False, 'error': 'Día actual no válido.'}, status=400)

        # Buscar el día en la base de datos
        dia_actual = Dia.objects.get(nombre=dia_actual_nombre_es)

        # Filtrar loterías solo disponibles
        loterias = Loteria.objects.filter(dias_juego=dia_actual).annotate(
            disponible=Case(
                When(hora_inicio__lte=ahora.time(), hora_fin__gte=ahora.time(), then=True),
                default=False,
                output_field=BooleanField(),
            )
        ).filter(disponible=True).order_by('-disponible')

        if request.method == 'POST':
            print("Método POST detectado...")

            # Capturar los datos del POST
            loterias_ids = request.POST.getlist('loterias')
            numeros = request.POST.getlist('numero')
            montos = request.POST.getlist('monto')
            combi = request.POST.get('combi')  # Captura el campo combi

            # Validar números y montos
            if len(numeros) != len(montos):
                print("Error: Longitud de números y montos no coincide.")
                return JsonResponse({'success': False, 'error': 'Los números y montos no coinciden.'}, status=400)

            # Validar loterías
            loterias_seleccionadas = Loteria.objects.filter(id__in=loterias_ids)
            print("Loterías seleccionadas:", loterias_seleccionadas)
            if not loterias_seleccionadas.exists():
                return JsonResponse({'success': False, 'error': 'Loterías no válidas.'}, status=400)

            # Crear ventas
            for numero, monto in zip(numeros, montos):
                venta = Venta.objects.create(
                    vendedor=request.user,
                    numero=numero,
                    monto=monto,
                    fecha_venta=ahora,
                    combi=int(combi) if combi else None  # Asignar null si no hay valor
                )
                venta.loterias.set(loterias_seleccionadas)
                print("Venta creada con éxito:", venta)

            print("Todas las ventas se crearon correctamente.")
            return JsonResponse({'success': True})

    except Dia.DoesNotExist:
        print(f"Error: Día no encontrado ({dia_actual_nombre_es}).")
        return JsonResponse({'success': False, 'error': f'Día no encontrado: {dia_actual_nombre_es}'}, status=404)

    except Exception as e:
        print(f"Error general en la vista crear_venta: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    # Renderizar la página
    return render(request, 'core/ventas.html', {
        'loterias': loterias,
        'dia_actual_nombre': dia_actual_nombre_es,
        'fecha_actual': ahora.date(),
        'current_time': ahora.time(),
    })

# Vista para listar ventas con filtros y paginación
@login_required(login_url='/login-required/')
def ventas_list(request):
    search = request.GET.get('search', '')
    start_date = request.GET.get('start_date', str(date.today()))
    end_date = request.GET.get('end_date', str(date.today()))
    vendedor_id = request.GET.get('vendedor', '')

    ventas = Venta.objects.filter(fecha_venta__date__gte=start_date, fecha_venta__date__lte=end_date)

    if not request.user.is_staff:
        ventas = ventas.filter(vendedor=request.user)

    if request.user.is_staff and vendedor_id:
        ventas = ventas.filter(vendedor_id=vendedor_id)

    if search:
        ventas = ventas.filter(numero__icontains=search)

    paginator = Paginator(ventas, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    total_ventas = ventas.annotate(
        total_por_loteria=F('monto') * Count('loterias')
    ).aggregate(
        total=Sum('total_por_loteria')
    )['total'] or 0

    vendedores = Venta.objects.values('vendedor__id', 'vendedor__username').distinct() if request.user.is_staff else []

    return render(request, 'core/ventas_list.html', {
        'ventas': page_obj,
        'total_ventas': total_ventas,
        'search': search,
        'start_date': start_date,
        'end_date': end_date,
        'vendedores': vendedores,
        'vendedor_id': vendedor_id,
    })

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

# Vista para premios
@login_required
def premios(request):
    return render(request, 'core/premios.html', {
    })

# Nueva vista para el superadmin: Registro de Resultados
@user_passes_test(lambda u: u.is_superuser)
@login_required
def registro_resultados(request):
    ahora = timezone.localtime(timezone.now())
    dia_actual_nombre = ahora.strftime('%A')
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
    fecha_actual = ahora.date()

    try:
        dia_actual = Dia.objects.get(nombre=dia_actual_nombre_es)
    except Dia.DoesNotExist:
        raise Http404(f"No se ha encontrado un día con el nombre {dia_actual_nombre_es}")

    # Filtrar las loterías que se juegan el día actual
    loterias = Loteria.objects.filter(dias_juego=dia_actual).order_by('nombre')

    # Preparar un diccionario con el resultado actual (si existe) para cada lotería
    resultados_dict = {}
    for lot in loterias:
        resultado_obj = Resultado.objects.filter(loteria=lot, fecha=fecha_actual).first()
        resultados_dict[lot.id] = resultado_obj.resultado if resultado_obj else None

    if request.method == 'POST':
        # Procesar el formulario: se espera un input "resultado_<loteria.id>" para cada lotería
        for lot in loterias:
            key = f"resultado_{lot.id}"
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
                Resultado.objects.filter(loteria=lot, fecha=fecha_actual).delete()
        return redirect('resultados')

    return render(request, 'core/registro_resultados.html', {
        'loterias': loterias,
        'resultados_dict': resultados_dict,
        'fecha_actual': fecha_actual,
        'dia_actual_nombre': dia_actual_nombre_es,
    })

# Vista para usuarios normales: Mostrar Resultados
@login_required
def resultados(request):
    ahora = timezone.localtime(timezone.now())
    dia_actual_nombre = ahora.strftime('%A')
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
    fecha_actual = ahora.date()

    try:
        dia_actual = Dia.objects.get(nombre=dia_actual_nombre_es)
    except Dia.DoesNotExist:
        raise Http404(f"No se ha encontrado un día con el nombre {dia_actual_nombre_es}")

    # Filtrar las loterías que se juegan el día actual
    loterias = Loteria.objects.filter(dias_juego=dia_actual).order_by('nombre')

    # Crear una lista de diccionarios con cada lotería y su resultado (si existe) para el día actual
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

def login_required_view(request):
    return render(request, 'core/login_required.html')
