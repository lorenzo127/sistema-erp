from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Importamos AMBAS vistas
from core.views import CustomLoginView, AdminLoginView 

urlpatterns = [
    # 1. Login ADMIN (Usa el diseño oscuro)
    path('admin/login/', AdminLoginView.as_view(), name='admin_login'),

    # 2. Rutas normales
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)