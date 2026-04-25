from django.contrib import admin
from django.urls import path
from core import views
from core.views import CustomLoginView, importar_resultados_api, reportes

from django.contrib.auth.views import LogoutView
from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
from django.http import FileResponse, Http404
import os, mimetypes, logging

logger = logging.getLogger(__name__)

def _serve_media(request, path):
    full = os.path.normpath(os.path.join(str(settings.MEDIA_ROOT), path))
    if not full.startswith(str(settings.MEDIA_ROOT)):
        raise Http404()
    logger.warning("MEDIA SERVE: path=%s exists=%s", full, os.path.exists(full))
    if not os.path.exists(full):
        raise Http404(f"No existe: {full}")
    ct, _ = mimetypes.guess_type(full)
    return FileResponse(open(full, "rb"), content_type=ct or "application/octet-stream")

urlpatterns = [
    path('', views.home, name="home"),
    path('loterias', views.loteria, name="loterias"),
    path('ventas', views.crear_venta, name="ventas"),
    path('descargues/', views.descargues, name='descargues'),
    path('mis-descargues/', views.mis_descargues, name='mis_descargues'),
    path('ventas_list/', views.ventas_list, name='ventas_list'),
    path('historico-ventas/', views.historico_ventas, name='historico_ventas'),
    path('premios/', views.premios, name='premios'),
    path('premios/reporte-rango/', views.premios_reporte_rango, name='premios_reporte_rango'),
    path('registro-resultados/', views.registro_resultados, name='registro_resultados'),
    path('resultados/', views.resultados, name='resultados'),
    path('reporte-descargas/', views.reporte_descargas, name='reporte_descargas'),
    path('reportes/', views.reportes, name='reportes'),
    path('reportes/ventas-vs-premios/', views.reporte_ventas_vs_premios, name='reporte_ventas_vs_premios'),
    path('reportes/conciliacion/', views.reporte_conciliacion, name='reporte_conciliacion'),
    path('reportes/riesgo-ventas/', views.reporte_riesgo_ventas, name='reporte_riesgo_ventas'),
    path('admin/', admin.site.urls),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('login-required/', views.login_required_view, name='login_required'),
    path("api/importar_resultados/", views.importar_resultados_api, name="importar_resultados_api"),
    path("api/notificaciones/count/", views.notificaciones_count_api, name="notificaciones_count"),
    path("api/notificaciones/", views.notificaciones_list, name="notificaciones_list"),
]

# Servir archivos de media con vista explícita (evita problemas con static() en producción)
urlpatterns += [re_path(r'^media/(?P<path>.*)$', _serve_media)]
