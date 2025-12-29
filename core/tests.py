# core/tests.py
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
import datetime

from .models import Ingreso, Empresa, CentroCosto, Clasificacion
from .services import DashboardService

class CalculosFinancierosTest(TestCase):
    def setUp(self):
        # Configuración inicial: Creamos datos de prueba (Fixtures)
        self.empresa = Empresa.objects.create(nombre="Empresa Test")
        self.centro = CentroCosto.objects.create(nombre="Centro Test")
        self.clasif = Clasificacion.objects.create(nombre="Clasif Test")
        
        # Creamos un usuario para las pruebas de vista
        self.user = User.objects.create_user(username='testuser', password='password123')

    def test_precision_decimal(self):
        """Prueba que los montos se guarden como Decimales exactos y no floats"""
        ingreso = Ingreso.objects.create(
            fecha=timezone.now(),
            monto_transferencia=Decimal('10500'), # Usamos string para asegurar precisión
            empresa=self.empresa,
            centro_costo=self.centro,
            clasificacion=self.clasif,
            estado="Pagado"
        )
        
        # Verificamos que sea instancia de Decimal
        self.assertIsInstance(ingreso.monto_transferencia, Decimal)
        # Verificamos que el valor sea exacto
        self.assertEqual(ingreso.monto_transferencia, Decimal('10500'))

    def test_dashboard_service_suma(self):
        """Prueba que el servicio sume correctamente los KPIs"""
        # Creamos 2 ingresos de 50.000 cada uno
        Ingreso.objects.create(
            fecha=datetime.date(2025, 1, 15),
            monto_transferencia=50000,
            empresa=self.empresa,
            centro_costo=self.centro,
            clasificacion=self.clasif,
            estado="Pagado"
        )
        Ingreso.objects.create(
            fecha=datetime.date(2025, 1, 20),
            monto_transferencia=50000,
            empresa=self.empresa,
            centro_costo=self.centro,
            clasificacion=self.clasif,
            estado="Pagado"
        )

        # Instanciamos el servicio filtrando por ese año y mes
        servicio = DashboardService(anio=2025, mes=1)
        kpis = servicio.obtener_kpis()

        # La suma debería ser 100.000 exactos
        self.assertEqual(kpis['total_monto'], 100000)
        self.assertEqual(kpis['total_registros'], 2)

    def test_vista_dashboard_protegida(self):
        """Prueba que el dashboard requiere login y carga bien (Status 200)"""
        client = Client()
        
        # 1. Intento sin login (debería redirigir)
        response = client.get(reverse('dashboard'))
        self.assertNotEqual(response.status_code, 200) 
        
        # 2. Login
        client.login(username='testuser', password='password123')
        
        # 3. Intento con login
        response = client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        # Verificamos que use el template correcto
        self.assertTemplateUsed(response, 'core/dashboard.html')