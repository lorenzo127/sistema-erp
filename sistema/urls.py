from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Ya no necesitamos importar AdminLoginView aquí
from core.views import CustomLoginView 

urlpatterns = [
    # --- CORRECCIÓN: Eliminamos la ruta personalizada del admin ---
    # Al quitar esto, Django usará su vista por defecto que pide Username/Pass
    # path('admin/login/', AdminLoginView.as_view(), name='admin_login'),

    # 2. Rutas normales
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)