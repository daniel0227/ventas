from django.contrib import admin
from django.urls import path
from core import views
from core import views_2fa
from core.views import CustomLoginView, importar_resultados_api, reportes

from django.contrib.auth.views import LogoutView
from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
from django.http import FileResponse, Http404
import os, mimetypes, logging

logger = logging.getLogger(__name__)

def _serve_media(request, path):
    media_root = os.path.normpath(str(settings.MEDIA_ROOT))
    full = os.path.normpath(os.path.join(media_root, path))
    if full != media_root and not full.startswith(media_root + os.sep):
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
    path('registro-resultados/', views.registro_resultados, name='registro_resultados'),
    path('resultados/', views.resultados, name='resultados'),
    path('reporte-descargas/', views.reporte_descargas, name='reporte_descargas'),
    path('descargues-por-persona/', views.descargues_por_persona, name='descargues_por_persona'),
    path('reportes/', views.reportes, name='reportes'),
    path('reportes/ventas-vs-premios/', views.reporte_ventas_vs_premios, name='reporte_ventas_vs_premios'),
    path('reportes/conciliacion/', views.reporte_conciliacion, name='reporte_conciliacion'),
    path('admin/', admin.site.urls),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('login-required/', views.login_required_view, name='login_required'),
    path("api/importar_resultados/", views.importar_resultados_api, name="importar_resultados_api"),
    path("api/notificaciones/count/", views.notificaciones_count_api, name="notificaciones_count"),
    path("api/notificaciones/", views.notificaciones_list, name="notificaciones_list"),

    # 2FA (verificacion en dos pasos) — cuentas staff/superuser
    path("2fa/setup/", views_2fa.dos_factor_setup, name="dos_factor_setup"),
    path("2fa/verify/", views_2fa.dos_factor_verify, name="dos_factor_verify"),

    # Abonados
    path('abonados/', views.abonados_list, name='abonados_list'),
    path('abonados/nuevo/', views.abonado_crear, name='abonado_crear'),
    path('abonados/<int:pk>/', views.abonado_detalle, name='abonado_detalle'),
    path('abonados/<int:pk>/editar/', views.abonado_editar, name='abonado_editar'),
    path('abonados/<int:pk>/eliminar/', views.abonado_eliminar, name='abonado_eliminar'),
    path('abonados/<int:pk>/borrar/', views.abonado_borrar, name='abonado_borrar'),
    path('abonados/<int:pk>/reactivar/', views.abonado_reactivar, name='abonado_reactivar'),
    path('abonados/<int:pk>/apostar/', views.abonado_apostar, name='abonado_apostar'),
    path('abonados/<int:pk>/historico/', views.abonado_historico, name='abonado_historico'),
]

# Servir archivos de media con vista explícita (evita problemas con static() en producción)
urlpatterns += [re_path(r'^media/(?P<path>.*)$', _serve_media)]
