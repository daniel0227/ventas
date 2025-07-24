
from django.contrib import admin
from django.urls import path
from core import views
from core.views import CustomLoginView, importar_resultados_api, prueba_post, importar_resultados_via_get

from django.contrib.auth.views import LogoutView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.home, name="home"),
    path('loterias', views.loteria, name="loterias"),
    path('ventas', views.crear_venta, name="ventas"),
    path('ventas_list/', views.ventas_list, name='ventas_list'),  # Aquí agregas la URL para la lista de ventas
    path('historico-ventas/', views.historico_ventas, name='historico_ventas'),
    path('premios/', views.premios, name='premios'),
    path('registro-resultados/', views.registro_resultados, name='registro_resultados'),
    path('resultados/', views.resultados, name='resultados'),
    path('reporte-descargas/', views.reporte_descargas, name='reporte_descargas'),
    path('admin/', admin.site.urls),
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('login-required/', views.login_required_view, name='login_required'),
    path("api/importar_resultados/", views.importar_resultados_api, name="importar_resultados_api"),
    path("api/importar_resultados_via_get/", importar_resultados_via_get, name="importar_resultados_via_get"),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)