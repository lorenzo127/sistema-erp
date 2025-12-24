from django.db import models
import calendar
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# --- TABLAS AUXILIARES (CATÁLOGOS) ---

class Empresa(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

class CentroCosto(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    codigo = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.nombre

class Clasificacion(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

# --- TABLAS PRINCIPALES ---

class Ingreso(models.Model):
    fecha = models.DateField()
    n_documento = models.CharField(max_length=50, blank=True, null=True)
    
    # Monto Total
    monto_transferencia = models.IntegerField(verbose_name="Monto Transferencia")
    
    # Campo para almacenar IVA en Ingresos
    iva = models.IntegerField(default=0, verbose_name="Monto IVA")
    
    descripcion_movimiento = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=50) 
    detalle = models.TextField(blank=True, null=True)
    tipo_documento = models.CharField(max_length=50, blank=True, null=True)
    
    # Relaciones
    clasificacion = models.ForeignKey(Clasificacion, on_delete=models.PROTECT, null=True)
    centro_costo = models.ForeignKey(CentroCosto, on_delete=models.PROTECT, null=True)
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, null=True)

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Ingreso {self.n_documento} - ${self.monto_transferencia}"

class Egreso(models.Model):
    fecha = models.DateField()
    n_documento = models.CharField(max_length=50, blank=True, null=True)
    monto_transferencia = models.IntegerField(verbose_name="Monto Transferencia")
    descripcion_movimiento = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=50)
    clasificacion = models.ForeignKey(Clasificacion, on_delete=models.PROTECT, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Egreso {self.n_documento} - ${self.monto_transferencia}"
    
class CajaChica(models.Model):
    TIPOS_DOCUMENTO = [
        ('FACTURA', 'Factura'),
        ('BOLETA', 'Boleta'),
        ('PEAJE', 'Peaje'),
        ('VALE', 'Vale / Recibo'),
        ('OTRO', 'Otro Documento'),
    ]

    fecha = models.DateField()
    monto = models.IntegerField(verbose_name="Monto Gasto")
    responsable = models.CharField(max_length=100)
    descripcion = models.TextField(verbose_name="Descripción del Gasto") 
    numero_documento = models.CharField(max_length=50, blank=True, null=True)
    tipo_documento = models.CharField(max_length=20, choices=TIPOS_DOCUMENTO, default='BOLETA')

    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Caja Chica"

    def __str__(self):
        return f"{self.fecha} - ${self.monto} - {self.responsable}"
    
    # --- AQUÍ ESTÁ LA CORRECCIÓN: Indentado dentro de la clase ---
    @property
    def iva_recuperable(self):
        # 1. Normalizar tipo
        tipo = str(self.tipo_documento).upper()
        
        # 2. Calcular solo si es Boleta o Factura
        if tipo in ['BOLETA', 'FACTURA']:
            try:
                # El monto es TOTAL, así que sacamos el neto dividiendo por 1.19
                neto = self.monto / 1.19
                iva = self.monto - neto
                # CORRECCIÓN: Usamos round() para redondear al más cercano
                return int(round(iva))
            except:
                return 0
        return 0
    

class Trabajador(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=200)
    rut = models.CharField(max_length=20)
    cargo = models.CharField(max_length=100)
    fecha_contrato = models.DateField(null=True, blank=True)
    fecha_finiquito = models.DateField(null=True, blank=True)
    monto_finiquito = models.IntegerField(default=0)
    fecha_carga = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        estado = "Finiquitado" if self.fecha_finiquito else "Activo"
        return f"{self.nombre} ({self.cargo}) - {estado}"
    
    @property
    def tiempo_servicio(self):
        if self.fecha_contrato and self.fecha_finiquito:
            inicio = self.fecha_contrato
            fin = self.fecha_finiquito
            
            anios = fin.year - inicio.year
            meses = fin.month - inicio.month
            dias = fin.day - inicio.day
            
            if dias < 0:
                meses -= 1
                year_prev = fin.year
                month_prev = fin.month - 1
                if month_prev == 0:
                    month_prev = 12
                    year_prev -= 1
                _, dias_en_mes_prev = calendar.monthrange(year_prev, month_prev)
                dias += dias_en_mes_prev
            
            if meses < 0:
                anios -= 1
                meses += 12
            
            partes = []
            if anios > 0:
                partes.append(f"{anios} año{'s' if anios != 1 else ''}")
            if meses > 0:
                partes.append(f"{meses} mes{'es' if meses != 1 else ''}")
            if dias > 0:
                partes.append(f"{dias} día{'s' if dias != 1 else ''}")
            
            if not partes:
                return "1 día"
                
            return ", ".join(partes)
        return "-"
    
class Perfil(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    imagen = models.ImageField(default='default.jpg', upload_to='perfiles_pics')
    telefono = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f'{self.user.username} Perfil'

# --- SEÑALES ---

@receiver(post_save, sender=User)
def crear_perfil(sender, instance, created, **kwargs):
    if created:
        Perfil.objects.create(user=instance)

@receiver(post_save, sender=User)
def guardar_perfil(sender, instance, **kwargs):
    try:
        instance.perfil.save()
    except Exception:
        Perfil.objects.create(user=instance)