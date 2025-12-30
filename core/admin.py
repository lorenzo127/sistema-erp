from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import (
    Ingreso, Empresa, CentroCosto, Clasificacion, 
    Egreso, CajaChica, Trabajador, Cargo, Perfil
)

# --- 1. CONFIGURACIÓN DE USUARIO (Con Script de RUT) ---
admin.site.unregister(User) # Quitamos el admin original

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Hemos eliminado la clase Media y el js.
    # Ahora se comporta como el admin por defecto de Django.
    pass

# --- 2. CONFIGURACIÓN DE INGRESOS ---
@admin.register(Ingreso)
class IngresoAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'n_documento', 'monto_transferencia', 'empresa', 'estado', 'centro_costo')
    search_fields = ('n_documento', 'empresa__nombre')
    list_filter = ('estado', 'empresa', 'centro_costo', 'fecha')
    list_per_page = 50

# --- 3. CONFIGURACIÓN DE TRABAJADORES ---
@admin.register(Trabajador)
class TrabajadorAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'rut', 'cargo', 'empresa', 'estado')
    search_fields = ('nombre', 'rut')
    list_filter = ('empresa', 'estado')

# --- 4. CONFIGURACIÓN DE CAJA CHICA ---
@admin.register(CajaChica)
class CajaChicaAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'responsable', 'monto', 'tipo_documento', 'descripcion')
    list_filter = ('tipo_documento',)

# --- 5. REGISTRO DE MODELOS SIMPLES ---
admin.site.register(Empresa)
admin.site.register(CentroCosto)
admin.site.register(Clasificacion)
admin.site.register(Egreso)
admin.site.register(Cargo)
admin.site.register(Perfil)

from django.contrib import admin
from .models import Producto, Lote

class LoteInline(admin.TabularInline):
    model = Lote
    extra = 1

class ProductoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'stock_total')
    inlines = [LoteInline] # Esto te permite agregar lotes DENTRO del producto

admin.site.register(Producto, ProductoAdmin)
admin.site.register(Lote)