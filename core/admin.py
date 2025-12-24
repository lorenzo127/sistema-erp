# core/admin.py
from django.contrib import admin
from .models import Ingreso, Empresa, CentroCosto, Clasificacion

# Configuración avanzada para la tabla principal
@admin.register(Ingreso)
class IngresoAdmin(admin.ModelAdmin):
    # Columnas que se verán en la lista
    list_display = ('fecha', 'n_documento', 'monto_transferencia', 'empresa', 'estado', 'centro_costo')
    
    # Barra de búsqueda (puedes buscar por documento o nombre de empresa)
    search_fields = ('n_documento', 'empresa__nombre', 'descripcion_movimiento')
    
    # Filtros laterales (para navegar rápido)
    list_filter = ('estado', 'empresa', 'centro_costo', 'fecha')
    
    # Paginación (para no mostrar los 2300 de golpe)
    list_per_page = 50

# Registramos las tablas simples
admin.site.register(Empresa)
admin.site.register(CentroCosto)
admin.site.register(Clasificacion)