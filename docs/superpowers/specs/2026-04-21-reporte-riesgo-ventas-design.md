# Diseño: Reporte de Análisis de Riesgo de Ventas

**Fecha:** 2026-04-21  
**Proyecto:** Chance — Sistema de Loterías  
**Estado:** Aprobado

---

## Resumen

Nuevo reporte administrativo que cruza los números jugados en un rango de fechas contra el histórico completo de resultados de cada lotería, para identificar cuáles números representan mayor riesgo financiero por su frecuencia histórica de caída.

---

## Alcance

- Solo ventas normales (`Venta`). No incluye `VentaDescargue`.
- Solo accesible para staff/administradores.
- El histórico de resultados usa **todos** los `Resultado` registrados (sin límite de fecha).
- El rango de fechas del filtro aplica únicamente a las ventas.

---

## Acceso y URL

- **URL:** `reportes/riesgo-ventas/`
- **Nombre de URL:** `reporte_riesgo_ventas`
- **Acceso:** `@login_required` + `@user_passes_test(lambda u: u.is_staff)`
- **Enlace:** agregado en la página `reportes/` existente

---

## Filtros

Formulario GET con dos campos:

| Campo | Tipo | Requerido |
|-------|------|-----------|
| `loteria` | Select con todas las `Loteria` | Sí |
| `fecha_desde` | Date input | Sí |
| `fecha_hasta` | Date input | Sí |

Sin filtros seleccionados, la tabla no se muestra (solo el formulario).

---

## Flujo de cálculo

### Query A — Ventas en rango

```python
Venta.objects
    .filter(loterias=loteria, fecha_venta__date__range=[fecha_desde, fecha_hasta])
    .values("numero")
    .annotate(
        veces_apostado=Count("id"),
        valor_apostado=Sum("monto"),
    )
```

### Query B — Histórico de resultados

```python
resultados_hist = (
    Resultado.objects
        .filter(loteria=loteria)
        .values("resultado")
        .annotate(apariciones=Count("id"))
)
total_sorteos = Resultado.objects.filter(loteria=loteria).count()
```

### Merge en Python

Para cada número de Query A:

```python
apariciones = freq_map.get(str(numero), 0)   # freq_map: {str(resultado): apariciones}
riesgo_pct  = (apariciones / total_sorteos * 100) if total_sorteos > 0 else 0.0
nivel       = "ALTO" if riesgo_pct > 3 else ("MEDIO" if riesgo_pct >= 1 else "BAJO")
```

### Ordenamiento

Resultado final ordenado por `riesgo_pct` descendente.

---

## Tabla de resultados

| Columna | Fuente | Descripción |
|---------|--------|-------------|
| Número | `Venta.numero` | Número apostado |
| Veces apostado | Count de `Venta` en rango | Cuántas apuestas se hicieron sobre ese número |
| Valor apostado | Sum de `Venta.monto` en rango | Total dinero apostado en el rango |
| Veces ganado | Count de `Resultado` histórico donde `resultado == numero` | Cuántas veces ese número fue ganador |
| Riesgo % | `veces_ganado / total_sorteos × 100` | Probabilidad histórica de que ese número caiga |
| Nivel | Basado en Riesgo % | 🔴 ALTO >3% · 🟡 MEDIO 1–3% · 🟢 BAJO <1% |

---

## Umbrales de riesgo

| Nivel | Condición |
|-------|-----------|
| 🔴 ALTO | `riesgo_pct > 3.0` |
| 🟡 MEDIO | `1.0 <= riesgo_pct <= 3.0` |
| 🟢 BAJO | `riesgo_pct < 1.0` |

---

## Exportación CSV

Botón "Exportar CSV" en la vista. Mismas columnas y mismo orden que la tabla HTML. Se activa con el parámetro GET `?export=csv` junto con los filtros.

---

## Archivos a crear o modificar

| Archivo | Acción |
|---------|--------|
| `core/views.py` | Agregar view `reporte_riesgo_ventas` |
| `chance/urls.py` | Agregar path `reportes/riesgo-ventas/` |
| `core/templates/core/reporte_riesgo_ventas.html` | Crear template nuevo |
| `core/templates/core/reportes.html` | Agregar enlace al nuevo reporte |

---

## Consideraciones de rendimiento

- Dos queries a la base de datos (Query A y Query B) más una COUNT.
- El merge se hace en Python sobre listas en memoria.
- Para loterías con miles de resultados históricos, las queries son eficientes por los índices existentes (`Resultado.loteria`, `Venta.fecha_venta`, `Venta.numero`).
- No se requiere caché ni tabla materializada para el volumen esperado.

---

## Fuera de alcance

- VentaDescargue no se incluye.
- No hay paginación (el número de números únicos por lotería en un rango acotado es manejable).
- No se aplica multiplicador de premio al cálculo de riesgo.
- No hay alertas automáticas ni notificaciones.
