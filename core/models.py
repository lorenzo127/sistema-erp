from django.db import models
import calendar
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

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

class Cargo(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre

# --- TABLAS PRINCIPALES ---

class Ingreso(models.Model):
    fecha = models.DateField()
    n_documento = models.CharField(max_length=50, blank=True, null=True)
    
    # Montos
    monto_transferencia = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Monto Transferencia")
    iva = models.DecimalField(max_digits=12, decimal_places=0, default=0, verbose_name="Monto IVA")
    
    descripcion_movimiento = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=50, default='PAGADO', blank=True, null=True)
    detalle = models.TextField(blank=True, null=True)
    tipo_documento = models.CharField(max_length=50, blank=True, null=True)
    
    # Relaciones
    clasificacion = models.ForeignKey(Clasificacion, on_delete=models.PROTECT, null=True)
    centro_costo = models.ForeignKey(CentroCosto, on_delete=models.PROTECT, null=True)
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, null=True)

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        """
        AUTOMATIZACIÓN DE IVA:
        Calcula el 19% automáticamente si es Factura o Boleta.
        Fórmula: Neto = Total / 1.19 | IVA = Total - Neto
        """
        documentos_con_iva = ['FACTURA', 'BOLETA', 'NOTA DE DEBITO', 'NOTA DE CRÉDITO']
        
        # Convertimos a mayúsculas y aseguramos que sea string
        tipo = str(self.tipo_documento).upper() if self.tipo_documento else ''
        
        # Verificamos si el tipo de documento implica IVA y si hay monto
        if any(doc in tipo for doc in documentos_con_iva) and self.monto_transferencia:
            try:
                # Convertimos a float para cálculo matemático seguro
                monto_total = float(self.monto_transferencia)
                monto_neto = int(monto_total / 1.19)
                self.iva = monto_total - monto_neto
            except ValueError:
                self.iva = 0
        else:
            # Si es Recibo, Voucher, etc., asumimos que es exento
            self.iva = 0

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Ingreso {self.n_documento} - ${self.monto_transferencia}"

class Egreso(models.Model):
    fecha = models.DateField()
    n_documento = models.CharField(max_length=50, blank=True, null=True)
    monto_transferencia = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Monto Transferencia")
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
    monto = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Monto Gasto")
    responsable = models.CharField(max_length=100)
    descripcion = models.TextField(verbose_name="Descripción del Gasto") 
    numero_documento = models.CharField(max_length=50, blank=True, null=True)
    tipo_documento = models.CharField(max_length=20, choices=TIPOS_DOCUMENTO, default='BOLETA')

    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Caja Chica"

    def __str__(self):
        return f"{self.fecha} - ${self.monto} - {self.responsable}"
    
    @property
    def iva_recuperable(self):
        tipo = str(self.tipo_documento).upper()
        if tipo in ['BOLETA', 'FACTURA']:
            try:
                monto_float = float(self.monto)
                neto = monto_float / 1.19
                iva = monto_float - neto
                return int(round(iva))
            except:
                return 0
        return 0
    

class Trabajador(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=200)
    rut = models.CharField(max_length=20, unique=True)
    cargo = models.ForeignKey(Cargo, on_delete=models.PROTECT, null=True)
    estado = models.CharField(max_length=50, default='ACTIVO')
    fecha_contrato = models.DateField(null=True, blank=True)
    fecha_finiquito = models.DateField(null=True, blank=True)
    monto_finiquito = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    fecha_carga = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        cargo_nombre = self.cargo.nombre if self.cargo else "Sin Cargo"
        return f"{self.nombre} ({cargo_nombre}) - {self.estado}"
    
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

class Movimiento(models.Model):
    TIPO_CHOICES = [
        ('INGRESO', 'Ingreso'),
        ('EGRESO', 'Egreso'),
    ]

    fecha = models.DateField(default=timezone.now)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    descripcion = models.CharField(max_length=255, verbose_name="Descripción")
    monto = models.IntegerField()
    empresa = models.ForeignKey('Empresa', on_delete=models.SET_NULL, null=True, blank=True)
    centro_costo = models.ForeignKey('CentroCosto', on_delete=models.SET_NULL, null=True, blank=True)
    banco = models.CharField(max_length=100, blank=True, null=True, verbose_name="Banco / Cuenta")
    n_documento = models.CharField(max_length=100, blank=True, null=True, verbose_name="N° Documento")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Movimiento Financiero"
        verbose_name_plural = "Movimientos Financieros"
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.fecha} | {self.descripcion} (${self.monto})"
    
# --- GESTIÓN DE INVENTARIO Y VENCIMIENTOS ---

class Producto(models.Model):
    codigo = models.CharField(max_length=50, unique=True, verbose_name="Código SKU")
    nombre = models.CharField(max_length=200)
    categoria = models.CharField(max_length=100, blank=True, null=True)
    stock_minimo = models.IntegerField(default=10, verbose_name="Alerta Stock Bajo")
    
    def save(self, *args, **kwargs):
        # Si tiene categoría, la convertimos a "Title Case"
        if self.categoria:
            self.categoria = self.categoria.title().strip() 
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre} ({self.categoria})"

    @property
    def stock_total(self):
        return self.lote_set.aggregate(total=models.Sum('cantidad'))['total'] or 0

class Lote(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    numero_lote = models.CharField(max_length=50)
    fecha_elaboracion = models.DateField(blank=True, null=True)
    fecha_vencimiento = models.DateField()
    cantidad = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['fecha_vencimiento']

    def __str__(self):
        return f"{self.producto.nombre} - Lote {self.numero_lote}"

    @property
    def dias_para_vencer(self):
        from datetime import date
        delta = self.fecha_vencimiento - date.today()
        return delta.days
    
    @property
    def estado_vencimiento(self):
        dias = self.dias_para_vencer
        if dias < 0: return 'VENCIDO'
        if dias <= 30: return 'POR_VENCER'
        return 'OK'