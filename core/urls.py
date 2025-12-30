from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    # --- DASHBOARD PRINCIPAL ---
    path('', views.dashboard, name='dashboard'),

    # --- FINANZAS ---
    path('ingresos/', views.lista_ingresos, name='lista_ingresos'),
    path('ingresos/nuevo/', views.nuevo_ingreso, name='nuevo_ingreso'),
    path('ingresos/editar/<int:id>/', views.editar_ingreso, name='editar_ingreso'),
    path('ingresos/eliminar/<int:id>/', views.eliminar_ingreso, name='eliminar_ingreso'),
    
    path('importar-finanzas/', views.importar_excel, name='importar_excel'),
    path('descargar-plantilla/', views.descargar_plantilla, name='descargar_plantilla'),

    # --- CAJA CHICA ---
    path('caja-chica/', views.lista_caja_chica, name='lista_caja_chica'),
    path('caja-chica/nueva/', views.caja_chica_crear, name='caja_chica_crear'),
    path('caja-chica/editar/<int:id>/', views.caja_chica_editar, name='caja_chica_editar'),
    
    # --- CORRECCIÓN FINAL AQUÍ ---
    # El name debe ser 'caja_chica_eliminar' para coincidir con tu HTML
    path('caja-chica/eliminar/<int:id>/', views.caja_chica_eliminar, name='caja_chica_eliminar'),
    
    path('caja-chica/exportar/', views.exportar_caja_chica_pdf, name='exportar_caja_chica_pdf'),

    # --- RRHH Y OTROS ---
    path('rrhh/', views.dashboard_rrhh, name='dashboard_rrhh'),
    path('rrhh/importar/', views.importar_rrhh, name='importar_rrhh'),
    path('rrhh/nuevo/', views.nuevo_trabajador, name='nuevo_trabajador'),
    path('rrhh/editar/<int:id>/', views.editar_trabajador, name='editar_trabajador'),

    # --- USUARIO ---
    path('perfil/', views.perfil_usuario, name='perfil_usuario'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    path('api/entrenar-ia/', views.api_entrenar_ia, name='api_entrenar_ia'),
    path('api/predecir/', views.api_predecir_categoria, name='api_predecir_categoria'),

    path('finanzas/', views.finanzas_dashboard, name='finanzas_dashboard'),
    path('finanzas/importar/', views.importar_finanzas, name='importar_finanzas'),

    path('inventario/', views.inventario_dashboard, name='inventario_dashboard'),
    path('inventario/nuevo-lote/', views.ingresar_lote, name='ingresar_lote'),
    path('inventario/salida/', views.salida_stock, name='salida_stock'),
    path('inventario/enviar-alerta/', views.enviar_alerta_vencimientos, name='enviar_alerta'),

    path('datos/', views.centro_datos, name='centro_datos'),
    path('datos/exportar-finanzas/', views.exportar_finanzas_csv, name='export_finanzas'),
    path('datos/exportar-stock/', views.exportar_inventario_csv, name='export_stock'),

    path('reportes/excel/', views.exportar_excel, name='exportar_excel'),
]
