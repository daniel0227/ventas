# Reporte de Riesgo de Ventas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un reporte administrativo que cruza los números apostados en un rango de fechas con el histórico de resultados de cada lotería, calculando frecuencia histórica y nivel de riesgo (ALTO/MEDIO/BAJO) por número.

**Architecture:** Vista Django pura con dos queries ORM (ventas agrupadas por número + resultados históricos agrupados por número), merge en Python, y exportación CSV opcional vía `?export=csv`. Sin modelos nuevos ni migraciones.

**Tech Stack:** Django ORM, Python stdlib (`csv`), Bootstrap Icons, Django TestCase.

---

## Mapa de archivos

| Archivo | Acción | Responsabilidad |
|---------|--------|-----------------|
| `core/views.py` | Modificar — agregar al final | View `reporte_riesgo_ventas` |
| `chance/urls.py` | Modificar — agregar path | Ruta `reportes/riesgo-ventas/` |
| `core/templates/core/reporte_riesgo_ventas.html` | Crear | Template del reporte |
| `core/templates/core/home.html` | Modificar línea 182 | Link en menú lateral |
| `core/tests.py` | Modificar — agregar clase al final | Tests de la view |

---

## Task 1: Tests (TDD — escribir primero, fallarán hasta Task 2)

**Files:**
- Modify: `core/tests.py` — agregar al final del archivo

- [ ] **Step 1: Agregar la clase de tests al final de `core/tests.py`**

```python
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
        # 10 sorteos históricos, el número 1234 ganó 2 veces → 20%
        for i in range(10):
            fecha = ddate(2024, 1, i + 1)
            numero_ganador = 1234 if i < 2 else 9999
            try:
                self._crear_resultado(numero_ganador, fecha=fecha)
            except Exception:
                pass  # unique_together puede fallar si número se repite misma fecha

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
```

- [ ] **Step 2: Verificar que los tests fallan (view no existe aún)**

```bash
python manage.py test core.tests.ReporteRiesgoVentasTests -v 2
```

Resultado esperado: `ERROR` — `NoReverseMatch` o `AttributeError: module has no attribute 'reporte_riesgo_ventas'`

---

## Task 2: View `reporte_riesgo_ventas`

**Files:**
- Modify: `core/views.py` — agregar al final del archivo (antes del EOF)

- [ ] **Step 1: Agregar la view al final de `core/views.py`**

```python
@login_required
@user_passes_test(lambda u: u.is_staff)
def reporte_riesgo_ventas(request):
    hoy = timezone.localdate()
    loterias_all = Loteria.objects.all().order_by('nombre')

    loteria_id = request.GET.get('loteria', '').strip()
    start_date = request.GET.get('fecha_desde', '').strip()
    end_date = request.GET.get('fecha_hasta', '').strip()

    tabla = []
    loteria_sel = None
    total_sorteos = 0

    if loteria_id and start_date and end_date:
        try:
            loteria_sel = Loteria.objects.get(pk=loteria_id)
            start = parse_date(start_date)
            end = parse_date(end_date)
            if not start or not end:
                raise ValueError("fechas inválidas")
            if start > end:
                start, end = end, start
                start_date, end_date = str(start), str(end)
            ok, msg = validar_rango_fechas(start, end)
            if not ok:
                messages.error(request, msg)
                return redirect(request.path)

            # Query A: ventas en el rango agrupadas por número
            ventas_qs = (
                Venta.objects
                .annotate(fecha=TruncDate('fecha_venta'))
                .filter(loterias=loteria_sel, fecha__range=(start, end))
                .values('numero')
                .annotate(
                    veces_apostado=Count('id'),
                    valor_apostado=Sum('monto'),
                )
            )

            # Query B: frecuencia histórica completa
            total_sorteos = Resultado.objects.filter(loteria=loteria_sel).count()
            freq_map = {
                str(r['resultado']): r['apariciones']
                for r in Resultado.objects
                    .filter(loteria=loteria_sel)
                    .values('resultado')
                    .annotate(apariciones=Count('id'))
            }

            UMBRAL_ALTO = 3.0
            UMBRAL_MEDIO = 1.0

            for row in ventas_qs:
                numero = str(row['numero']).strip()
                apariciones = freq_map.get(numero, 0)
                riesgo_pct = round(apariciones / total_sorteos * 100, 2) if total_sorteos > 0 else 0.0
                if riesgo_pct > UMBRAL_ALTO:
                    nivel = 'ALTO'
                elif riesgo_pct >= UMBRAL_MEDIO:
                    nivel = 'MEDIO'
                else:
                    nivel = 'BAJO'
                tabla.append({
                    'numero': numero,
                    'veces_apostado': row['veces_apostado'],
                    'valor_apostado': row['valor_apostado'],
                    'veces_ganado': apariciones,
                    'riesgo_pct': riesgo_pct,
                    'nivel': nivel,
                })

            tabla.sort(key=lambda x: x['riesgo_pct'], reverse=True)

            if request.GET.get('export') == 'csv':
                resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
                resp['Content-Disposition'] = (
                    f'attachment; filename="riesgo_ventas_{loteria_sel.nombre}_{start}_{end}.csv"'
                )
                writer = csv.writer(resp)
                writer.writerow(['Número', 'Veces apostado', 'Valor apostado', 'Veces ganado', 'Riesgo %', 'Nivel'])
                for item in tabla:
                    writer.writerow([
                        item['numero'],
                        item['veces_apostado'],
                        item['valor_apostado'],
                        item['veces_ganado'],
                        item['riesgo_pct'],
                        item['nivel'],
                    ])
                return resp

        except Loteria.DoesNotExist:
            messages.error(request, 'Lotería no encontrada.')
            return redirect(request.path)

    return render(request, 'core/reporte_riesgo_ventas.html', {
        'loterias': loterias_all,
        'loteria_sel': loteria_sel,
        'loteria_id': loteria_id,
        'fecha_desde': start_date,
        'fecha_hasta': end_date or str(hoy),
        'tabla': tabla,
        'total_sorteos': total_sorteos,
    })
```

---

## Task 3: URL

**Files:**
- Modify: `chance/urls.py`

- [ ] **Step 1: Agregar el path en `chance/urls.py`**

Después de la línea `path('reportes/conciliacion/', ...)`, agregar:

```python
path('reportes/riesgo-ventas/', views.reporte_riesgo_ventas, name='reporte_riesgo_ventas'),
```

El bloque de urlpatterns queda así en esa sección:

```python
    path('reportes/', views.reportes, name='reportes'),
    path('reportes/ventas-vs-premios/', views.reporte_ventas_vs_premios, name='reporte_ventas_vs_premios'),
    path('reportes/conciliacion/', views.reporte_conciliacion, name='reporte_conciliacion'),
    path('reportes/riesgo-ventas/', views.reporte_riesgo_ventas, name='reporte_riesgo_ventas'),
```

- [ ] **Step 2: Ejecutar los tests de nuevo — ahora deben pasar**

```bash
python manage.py test core.tests.ReporteRiesgoVentasTests -v 2
```

Resultado esperado: todos los tests en `OK` (template aún no existe — el test de formulario vacío puede fallar con `TemplateDoesNotExist`; es normal hasta Task 4).

---

## Task 4: Template `reporte_riesgo_ventas.html`

**Files:**
- Create: `core/templates/core/reporte_riesgo_ventas.html`

- [ ] **Step 1: Crear el archivo con el siguiente contenido**

```html
{# core/templates/core/reporte_riesgo_ventas.html #}
{% extends "core/base.html" %}
{% load format_filters %}

{% block breadcrumbs %}
<nav class="breadcrumb-lottia" aria-label="Ruta de navegación">
  <a href="{% url 'home' %}"><i class="bi bi-house-fill me-1"></i>Inicio</a>
  <span class="sep"><i class="bi bi-chevron-right"></i></span>
  <span class="current">Análisis de Riesgo</span>
</nav>
{% endblock %}

{% block content %}
<style>
  :root {
    --primary:       #4f46e5;
    --primary-dark:  #3730a3;
    --primary-light: #eef2ff;
    --danger:        #ef4444;
    --danger-light:  #fef2f2;
    --warning:       #f59e0b;
    --warning-light: #fffbeb;
    --success:       #10b981;
    --success-light: #ecfdf5;
    --border:        #e5e7eb;
    --muted:         #6b7280;
    --card-radius:   16px;
    --shadow:        0 2px 12px rgba(0,0,0,.07);
  }

  @keyframes fadeUp {
    from { opacity:0; transform:translateY(12px); }
    to   { opacity:1; transform:translateY(0); }
  }
  .fade-up { animation: fadeUp .35s ease both; }

  .page-header { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:.6rem; margin-bottom:1.25rem; }
  .page-header h1 { font-size:1.35rem; font-weight:700; color:#1f2937; margin:0; }
  .page-header .subtitle { font-size:.82rem; color:var(--muted); margin-top:.15rem; }

  .filter-card { background:#fff; border-radius:var(--card-radius); box-shadow:var(--shadow); padding:1rem 1.25rem; margin-bottom:1.25rem; border:1px solid var(--border); }
  .filter-label { font-size:.75rem; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; margin-bottom:.4rem; display:block; }
  .filter-select, .filter-input {
    appearance:none; -webkit-appearance:none;
    border:1.5px solid var(--border); border-radius:10px;
    font-size:.92rem; padding:.52rem .85rem;
    background:#fafafa; width:100%; min-height:44px;
    color:#1f2937;
  }
  .filter-select { background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 16 16'%3E%3Cpath fill='%236b7280' d='M7.247 11.14L2.451 5.658C1.885 5.013 2.345 4 3.204 4h9.592a1 1 0 0 1 .753 1.659l-4.796 5.48a1 1 0 0 1-1.506 0z'/%3E%3C/svg%3E"); background-repeat:no-repeat; background-position:right .85rem center; padding-right:2.5rem; }

  .btn-primary-action {
    display:inline-flex; align-items:center; gap:.4rem;
    background:var(--primary); color:#fff; border:none; border-radius:10px;
    font-size:.9rem; font-weight:600; padding:.52rem 1.25rem;
    cursor:pointer; min-height:44px; text-decoration:none;
  }
  .btn-primary-action:hover { background:var(--primary-dark); color:#fff; }

  .btn-export {
    display:inline-flex; align-items:center; gap:.4rem;
    border-radius:10px; font-size:.85rem; font-weight:600;
    padding:.45rem 1rem; text-decoration:none; min-height:38px;
    background:#10b981; color:#fff;
  }
  .btn-export:hover { opacity:.88; color:#fff; }

  .table-card { background:#fff; border-radius:var(--card-radius); box-shadow:var(--shadow); border:1px solid var(--border); margin-bottom:1.5rem; overflow:hidden; }
  .table-card-header {
    background:linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
    color:#fff; padding:.85rem 1.25rem;
    display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:.5rem;
  }
  .table-card-header .title { font-size:.95rem; font-weight:700; }

  .desktop-table { display:none; }
  @media (min-width:576px) { .desktop-table { display:block; } }
  .desktop-table table { width:100%; border-collapse:collapse; }
  .desktop-table thead tr { background:#f8fafc; }
  .desktop-table thead th { font-size:.75rem; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; padding:.7rem 1rem; border-bottom:1px solid var(--border); white-space:nowrap; }
  .desktop-table tbody tr { border-bottom:1px solid #f3f4f6; transition:background .12s; }
  .desktop-table tbody tr:last-child { border-bottom:none; }
  .desktop-table tbody tr:hover { background:#fafbff; }
  .desktop-table tbody td { padding:.75rem 1rem; font-size:.9rem; color:#374151; vertical-align:middle; }

  .mobile-cards { display:block; }
  @media (min-width:576px) { .mobile-cards { display:none; } }
  .mob-row { border-bottom:1px solid var(--border); padding:.85rem 1rem; }
  .mob-row:last-child { border-bottom:none; }
  .mob-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:.4rem; }
  .mob-numero { font-size:1rem; font-weight:800; color:#1f2937; }
  .mob-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:.3rem .5rem; }
  .mob-item { display:flex; flex-direction:column; }
  .mob-label { font-size:.68rem; font-weight:600; color:var(--muted); text-transform:uppercase; }
  .mob-value { font-size:.83rem; font-weight:600; color:#374151; }

  .badge-riesgo { display:inline-flex; align-items:center; gap:.3rem; border-radius:8px; font-size:.78rem; font-weight:700; padding:.2rem .6rem; }
  .badge-alto   { background:var(--danger-light);  color:var(--danger); }
  .badge-medio  { background:var(--warning-light); color:var(--warning); }
  .badge-bajo   { background:var(--success-light); color:var(--success); }

  .empty-state { text-align:center; padding:3rem 1.5rem; color:var(--muted); }
  .empty-state i { font-size:3rem; opacity:.35; margin-bottom:.75rem; display:block; }
  .empty-state p { font-size:.9rem; margin:0; }
</style>

<!-- Header -->
<div class="page-header fade-up">
  <div>
    <h1><i class="bi bi-shield-exclamation me-2" style="color:var(--danger);"></i>Análisis de Riesgo de Ventas</h1>
    {% if loteria_sel %}
    <div class="subtitle">{{ loteria_sel.nombre }} · {{ fecha_desde }} — {{ fecha_hasta }}</div>
    {% else %}
    <div class="subtitle">Selecciona una lotería y rango de fechas</div>
    {% endif %}
  </div>
  {% if tabla %}
  <a href="?loteria={{ loteria_id }}&fecha_desde={{ fecha_desde }}&fecha_hasta={{ fecha_hasta }}&export=csv" class="btn-export">
    <i class="bi bi-filetype-csv"></i> Exportar CSV
  </a>
  {% endif %}
</div>

<!-- Filtro -->
<div class="filter-card fade-up">
  <form method="get" action="">
    <div class="row g-2 align-items-end">
      <div class="col-12 col-sm-4">
        <label class="filter-label">Lotería</label>
        <select name="loteria" class="filter-select" required>
          <option value="">— Selecciona —</option>
          {% for lot in loterias %}
          <option value="{{ lot.pk }}" {% if lot.pk|stringformat:"s" == loteria_id %}selected{% endif %}>{{ lot.nombre }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-6 col-sm-3">
        <label class="filter-label">Desde</label>
        <input type="date" name="fecha_desde" class="filter-input" value="{{ fecha_desde }}" required>
      </div>
      <div class="col-6 col-sm-3">
        <label class="filter-label">Hasta</label>
        <input type="date" name="fecha_hasta" class="filter-input" value="{{ fecha_hasta }}" required>
      </div>
      <div class="col-12 col-sm-2">
        <button type="submit" class="btn-primary-action w-100">
          <i class="bi bi-search"></i> Consultar
        </button>
      </div>
    </div>
  </form>
</div>

{% if messages %}
{% for msg in messages %}
<div class="alert alert-{{ msg.tags }} mb-3">{{ msg }}</div>
{% endfor %}
{% endif %}

{% if loteria_sel %}
<!-- Tabla de riesgo -->
<div class="table-card fade-up">
  <div class="table-card-header">
    <span class="title"><i class="bi bi-table me-2"></i>Números en riesgo — {{ tabla|length }} número{{ tabla|length|pluralize:"s" }}</span>
    {% if total_sorteos > 0 %}
    <span style="font-size:.8rem;opacity:.85;">{{ total_sorteos }} sorteo{{ total_sorteos|pluralize:"s" }} histórico{{ total_sorteos|pluralize:"s" }}</span>
    {% endif %}
  </div>

  {% if tabla %}
  <!-- Desktop -->
  <div class="desktop-table">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Número</th>
          <th>Veces apostado</th>
          <th>Valor apostado</th>
          <th>Veces ganado</th>
          <th>Riesgo %</th>
          <th>Nivel</th>
        </tr>
      </thead>
      <tbody>
        {% for row in tabla %}
        <tr>
          <td style="color:var(--muted);font-size:.8rem;">{{ forloop.counter }}</td>
          <td style="font-weight:700;font-size:1rem;letter-spacing:.05em;">{{ row.numero }}</td>
          <td>{{ row.veces_apostado }}</td>
          <td>${{ row.valor_apostado|floatformat:0 }}</td>
          <td>{{ row.veces_ganado }}</td>
          <td style="font-weight:700;">{{ row.riesgo_pct }}%</td>
          <td>
            {% if row.nivel == 'ALTO' %}
            <span class="badge-riesgo badge-alto"><i class="bi bi-exclamation-triangle-fill"></i> ALTO</span>
            {% elif row.nivel == 'MEDIO' %}
            <span class="badge-riesgo badge-medio"><i class="bi bi-dash-circle-fill"></i> MEDIO</span>
            {% else %}
            <span class="badge-riesgo badge-bajo"><i class="bi bi-check-circle-fill"></i> BAJO</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Mobile -->
  <div class="mobile-cards">
    {% for row in tabla %}
    <div class="mob-row">
      <div class="mob-header">
        <span class="mob-numero">{{ row.numero }}</span>
        {% if row.nivel == 'ALTO' %}
        <span class="badge-riesgo badge-alto"><i class="bi bi-exclamation-triangle-fill"></i> ALTO</span>
        {% elif row.nivel == 'MEDIO' %}
        <span class="badge-riesgo badge-medio"><i class="bi bi-dash-circle-fill"></i> MEDIO</span>
        {% else %}
        <span class="badge-riesgo badge-bajo"><i class="bi bi-check-circle-fill"></i> BAJO</span>
        {% endif %}
      </div>
      <div class="mob-grid">
        <div class="mob-item"><span class="mob-label">Veces apostado</span><span class="mob-value">{{ row.veces_apostado }}</span></div>
        <div class="mob-item"><span class="mob-label">Valor apostado</span><span class="mob-value">${{ row.valor_apostado|floatformat:0 }}</span></div>
        <div class="mob-item"><span class="mob-label">Veces ganado</span><span class="mob-value">{{ row.veces_ganado }}</span></div>
        <div class="mob-item"><span class="mob-label">Riesgo %</span><span class="mob-value">{{ row.riesgo_pct }}%</span></div>
      </div>
    </div>
    {% endfor %}
  </div>

  {% else %}
  <div class="empty-state">
    <i class="bi bi-inbox"></i>
    <p>No hay ventas registradas para {{ loteria_sel.nombre }} en el rango seleccionado.</p>
  </div>
  {% endif %}
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 2: Ejecutar todos los tests**

```bash
python manage.py test core.tests.ReporteRiesgoVentasTests -v 2
```

Resultado esperado: todos en `OK`.

---

## Task 5: Link en menú lateral

**Files:**
- Modify: `core/templates/core/home.html` — línea 182

- [ ] **Step 1: Agregar el link después de `Rentabilidad Mensual`**

Encontrar el bloque (alrededor de la línea 179-183):

```html
                <a href="{% url 'reporte_conciliacion' %}" class="menu-collapse-link">
                  <span class="menu-collapse-dot"></span>
                  <span>Rentabilidad Mensual</span>
                </a>
              </div>
```

Reemplazarlo por:

```html
                <a href="{% url 'reporte_conciliacion' %}" class="menu-collapse-link">
                  <span class="menu-collapse-dot"></span>
                  <span>Rentabilidad Mensual</span>
                </a>
                <a href="{% url 'reporte_riesgo_ventas' %}" class="menu-collapse-link">
                  <span class="menu-collapse-dot"></span>
                  <span>Riesgo de Ventas</span>
                </a>
              </div>
```

---

## Task 6: Commit y verificación final

- [ ] **Step 1: Ejecutar suite completa de tests**

```bash
python manage.py test core -v 2
```

Resultado esperado: todos los tests existentes más los nuevos en `OK`. Sin errores de regresión.

- [ ] **Step 2: Verificar que el servidor levanta sin errores**

```bash
python manage.py check
```

Resultado esperado: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Commit final**

```bash
git add core/views.py chance/urls.py core/templates/core/reporte_riesgo_ventas.html core/templates/core/home.html core/tests.py
git commit -m "feat: agregar reporte de análisis de riesgo de ventas"
```

---

## Notas de implementación

- El filtro `loterias=loteria_sel` en la Query A funciona porque `Venta.loterias` es ManyToMany — Django genera un JOIN correcto.
- `TruncDate('fecha_venta')` se importa desde `django.db.models.functions` (ya importado en `views.py` línea 38).
- `freq_map` indexa por `str(resultado)` para hacer el lookup con `str(row['numero'])` y manejar zeros iniciales correctamente.
- Si `total_sorteos == 0` (sin historial), `riesgo_pct = 0.0` y todos los números aparecen como BAJO.
