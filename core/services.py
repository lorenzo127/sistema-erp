# core/services.py
import json
from django.db.models import Sum, Avg
from django.db.models.functions import TruncDay, TruncMonth
from .models import Ingreso # <--- Verifica que esta línea exista

class DashboardService:
    def __init__(self, anio=None, mes=None):
        self.anio = anio
        self.mes = mes
        self.queryset = Ingreso.objects.all().order_by('fecha')
        self._aplicar_filtros()

    def _aplicar_filtros(self):
        if self.anio:
            self.queryset = self.queryset.filter(fecha__year=self.anio)
        if self.mes:
            self.queryset = self.queryset.filter(fecha__month=self.mes)

    def obtener_kpis(self):
        total_monto = self.queryset.aggregate(Sum('monto_transferencia'))['monto_transferencia__sum'] or 0
        total_registros = self.queryset.count()
        promedio = int(self.queryset.aggregate(Avg('monto_transferencia'))['monto_transferencia__avg'] or 0)
        
        return {
            'total_monto': total_monto,
            'total_registros': total_registros,
            'promedio_monto': promedio
        }

    def obtener_datos_graficos(self):
        # A. Por Empresa
        gastos_empresa = self.queryset.values('empresa__nombre').annotate(total=Sum('monto_transferencia')).order_by('-total')[:10]
        
        # B. Por Clasificación
        gastos_clasif = self.queryset.values('clasificacion__nombre').annotate(total=Sum('monto_transferencia')).order_by('-total')

        # C. Evolución Temporal
        if self.mes:
            gastos_evol = self.queryset.annotate(periodo=TruncDay('fecha')).values('periodo').annotate(total=Sum('monto_transferencia')).order_by('periodo')
            fmt = "%d/%m"
        else:
            gastos_evol = self.queryset.annotate(periodo=TruncMonth('fecha')).values('periodo').annotate(total=Sum('monto_transferencia')).order_by('periodo')
            fmt = "%b %Y"

        return {
            'labels_empresas': json.dumps([g['empresa__nombre'] for g in gastos_empresa]),
            'data_empresas': json.dumps([int(g['total']) for g in gastos_empresa]),
            'labels_clasificacion': json.dumps([g['clasificacion__nombre'] or "Sin Clasif." for g in gastos_clasif]),
            'data_clasificacion': json.dumps([int(g['total']) for g in gastos_clasif]),
            'labels_evolucion': json.dumps([g['periodo'].strftime(fmt) for g in gastos_evol if g['periodo']]),
            'data_evolucion': json.dumps([int(g['total']) for g in gastos_evol]),
        }