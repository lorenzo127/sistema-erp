import datetime
import io
import json
import os
import pandas as pd
import csv

# --- IMPORTS DJANGO ---
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, IntegerField, Q, Sum
from django.db.models.functions import Cast, TruncDay, TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from .forms import SalidaStockForm
# --- IMPORTS TERCEROS ---
try:
    from weasyprint import HTML
except (ImportError, OSError):
    HTML = None

# --- IMPORTS LOCALES ---
from .models import (
    CajaChica, 
    CentroCosto, 
    Clasificacion, 
    Empresa, 
    Ingreso, 
    Trabajador, 
    Cargo, 
    Movimiento,
    Producto, # Nuevo
    Lote      # Nuevo
)

from .forms import (
    CajaChicaForm,
    CargaExcelForm,
    IngresoForm,
    RegistroUsuarioForm,
    TrabajadorForm,
    LoteForm  # Nuevo
)

from .services import DashboardService
from .ia import entrenar_modelo, predecir_categoria


# =========================================================
# 1. DASHBOARD GENERAL (Página de Inicio)
# ========================================================

@login_required
def dashboard(request):
    """VISTA PRINCIPAL: COMANDO CENTRAL"""
    hoy = datetime.date.today()
    fecha_limite = hoy + datetime.timedelta(days=30) # 30 días para alertas

    # --- 1. LOGÍSTICA (Alertas de Stock) ---
    stock_vencido = Lote.objects.filter(fecha_vencimiento__lt=hoy).count()
    stock_por_vencer = Lote.objects.filter(fecha_vencimiento__range=[hoy, fecha_limite]).count()

    # --- 2. FINANZAS (Gastos del Mes Actual) ---
    # Sumamos lo que cargaste en 'Ingresos/Gastos' correspondiente al mes actual
    gastos_mes = Ingreso.objects.filter(
        fecha__year=hoy.year,
        fecha__month=hoy.month
    ).aggregate(total=Sum('monto_transferencia'))['total'] or 0

    # --- 3. RRHH (Personal Activo) ---
    trabajadores_activos = Trabajador.objects.filter(fecha_finiquito__isnull=True).count()
    
    # Calcular variación (ejemplo simple: RRHH)
    # Podrías agregar más lógica aquí si quisieras comparar con el mes anterior

    context = {
        'stock_vencido': stock_vencido,
        'stock_por_vencer': stock_por_vencer,
        'gastos_mes': gastos_mes,
        'trabajadores_activos': trabajadores_activos,
        'hoy': hoy,
    }
    return render(request, 'core/dashboard.html', context)


# =========================================================
# 2. MÓDULO FINANZAS (Control de Movimientos .xlsm)
# =========================================================
@login_required
def finanzas_dashboard(request):
    """Dashboard Financiero con Filtros de Fecha."""
    
    # 1. Capturar Filtros
    anio = request.GET.get('anio')
    mes = request.GET.get('mes')

    # Queryset base (todos los movimientos)
    queryset = Movimiento.objects.all()

    # Aplicar filtros si existen
    if anio:
        queryset = queryset.filter(fecha__year=anio)
    
    if anio and mes: 
        queryset = queryset.filter(fecha__month=mes)

    # 2. Calcular KPIs
    total_ingresos = queryset.filter(tipo='INGRESO').aggregate(Sum('monto'))['monto__sum'] or 0
    total_egresos = queryset.filter(tipo='EGRESO').aggregate(Sum('monto'))['monto__sum'] or 0
    balance = total_ingresos - total_egresos

    # 3. Datos para Gráfico de Evolución
    if anio and mes:
        # Agrupar por DÍA
        evolucion = queryset.annotate(fecha_trunc=TruncDay('fecha'))\
                            .values('fecha_trunc')\
                            .annotate(
                                ingreso=Sum('monto', filter=Q(tipo='INGRESO')),
                                egreso=Sum('monto', filter=Q(tipo='EGRESO'))
                            ).order_by('fecha_trunc')
        formato_fecha = "%d %b"
    else:
        # Agrupar por MES
        evolucion = queryset.annotate(fecha_trunc=TruncMonth('fecha'))\
                            .values('fecha_trunc')\
                            .annotate(
                                ingreso=Sum('monto', filter=Q(tipo='INGRESO')),
                                egreso=Sum('monto', filter=Q(tipo='EGRESO'))
                            ).order_by('fecha_trunc')
        formato_fecha = "%B %Y"

    labels_evolucion = []
    data_ingresos = []
    data_egresos = []

    for e in evolucion:
        if e['fecha_trunc']:
            labels_evolucion.append(e['fecha_trunc'].strftime(formato_fecha))
            data_ingresos.append(e['ingreso'] or 0)
            data_egresos.append(e['egreso'] or 0)

    # 4. Obtener Años Disponibles
    anios_disponibles = Movimiento.objects.dates('fecha', 'year', order='DESC')

    context = {
        'total_ingresos': total_ingresos,
        'total_egresos': total_egresos,
        'balance': balance,
        'movimientos': queryset.order_by('-fecha')[:50],
        'pie_labels': ['Ingresos', 'Egresos'],
        'pie_data': [total_ingresos, total_egresos],
        'bar_labels': labels_evolucion,
        'bar_ingresos': data_ingresos,
        'bar_egresos': data_egresos,
        'anios_disponibles': anios_disponibles,
        'anio_seleccionado': int(anio) if anio else None,
        'mes_seleccionado': int(mes) if mes else None,
    }
    return render(request, 'core/finanzas/dashboard.html', context)

@login_required
def importar_finanzas(request):
    """Importador Específico para Hoja 'Control de Finanzas'"""
    if request.method == 'POST' and request.FILES.get('archivo_excel'):
        archivo = request.FILES['archivo_excel']
        try:
            df = pd.read_excel(
                archivo, 
                engine='openpyxl', 
                sheet_name='Control de Finanzas',
                header=12,
                usecols="B:F"
            )
            
            nuevos_nombres = ['FECHA', 'DESCRIPCION', 'TIPO', 'CATEGORIA', 'MONTO']
            if len(df.columns) == 5:
                df.columns = nuevos_nombres
            
            creados = 0
            
            with transaction.atomic():
                for index, row in df.iterrows():
                    fecha = row.get('FECHA')
                    if pd.isnull(fecha) or str(fecha).strip() == '': continue

                    desc = str(row.get('DESCRIPCION', '')).strip()
                    if desc == 'nan': desc = 'Sin detalle'

                    categoria = str(row.get('CATEGORIA', '')).strip()
                    if categoria and categoria != 'nan':
                        desc = f"{categoria} - {desc}"

                    try:
                        val_monto = row.get('MONTO', 0)
                        if isinstance(val_monto, str):
                             val_monto = val_monto.replace('$', '').replace('.', '').replace(',', '')
                        monto = abs(int(float(val_monto)))
                    except:
                        monto = 0
                        
                    if monto == 0: continue

                    tipo_texto = str(row.get('TIPO', '')).upper()
                    tipo_final = 'EGRESO' 
                    if 'INGRESO' in tipo_texto or 'ABONO' in tipo_texto:
                        tipo_final = 'INGRESO'
                    
                    Movimiento.objects.create(
                        fecha=fecha,
                        descripcion=desc,
                        monto=monto,
                        tipo=tipo_final,
                    )
                    creados += 1

            if creados > 0:
                messages.success(request, f'¡Excelente! Se cargaron {creados} registros.')
            else:
                messages.warning(request, 'Se leyó la hoja, pero no se encontraron filas válidas.')
                
            return redirect('finanzas_dashboard')

        except Exception as e:
            if "Worksheet" in str(e) and "does not exist" in str(e):
                messages.error(request, 'Error: No se encontró la hoja llamada "Control de Finanzas".')
            else:
                messages.error(request, f"Error técnico: {str(e)}")
            print(f"Error Finanzas: {e}")

    return render(request, 'core/finanzas/importar.html')


# =========================================================
# 3. MÓDULO INGRESOS / GASTOS (CRUD Clásico)
# =========================================================
@login_required
def lista_ingresos(request):
    empresas = Empresa.objects.all().order_by('nombre')
    centros = CentroCosto.objects.all().order_by('nombre')
    clasificaciones = Clasificacion.objects.all().order_by('nombre')
    
    f_empresa = request.GET.get('empresa')
    f_centro = request.GET.get('centro')
    f_clasif = request.GET.get('clasificacion')
    f_min = request.GET.get('min_costo')
    f_max = request.GET.get('max_costo')
    f_fecha_inicio = request.GET.get('fecha_inicio')
    f_fecha_fin = request.GET.get('fecha_fin')
    f_orden = request.GET.get('orden', 'fecha_desc')
    
    es_ajax = request.GET.get('modo_ajax') == 'true'
    pagina = request.GET.get('page', 1)
    por_pagina = request.GET.get('per_page', 25) 

    ingresos = Ingreso.objects.select_related('empresa', 'centro_costo', 'clasificacion').annotate(
        monto_real=Cast('monto_transferencia', output_field=IntegerField())
    )

    if f_empresa: ingresos = ingresos.filter(empresa_id=f_empresa)
    if f_centro: ingresos = ingresos.filter(centro_costo_id=f_centro)
    if f_clasif: ingresos = ingresos.filter(clasificacion_id=f_clasif)
    if f_min:
        try: ingresos = ingresos.filter(monto_real__gte=int(f_min.replace('.', '')))
        except ValueError: pass
    if f_max:
        try: ingresos = ingresos.filter(monto_real__lte=int(f_max.replace('.', '')))
        except ValueError: pass
    if f_fecha_inicio: ingresos = ingresos.filter(fecha__gte=f_fecha_inicio)
    if f_fecha_fin: ingresos = ingresos.filter(fecha__lte=f_fecha_fin)

    if f_orden == 'monto_desc': ingresos = ingresos.order_by('-monto_real')
    elif f_orden == 'monto_asc': ingresos = ingresos.order_by('monto_real')
    elif f_orden == 'fecha_asc': ingresos = ingresos.order_by('fecha')
    else: ingresos = ingresos.order_by('-fecha')

    datos_grafico = ingresos.annotate(dia=TruncDay('fecha')).values('dia').annotate(total=Sum('monto_real')).order_by('dia')
    labels_grafico = [d['dia'].strftime("%d/%m/%Y") for d in datos_grafico if d['dia']]
    data_grafico = [d['total'] for d in datos_grafico if d['dia']]

    paginator = Paginator(ingresos, por_pagina)
    page_obj = paginator.get_page(pagina)

    if es_ajax:
        contexto_ajax = {
            'ingresos': page_obj,
            'empresa_sel': int(f_empresa) if f_empresa else None,
            'centro_sel': int(f_centro) if f_centro else None,
            'clasif_sel': int(f_clasif) if f_clasif else None,
        }
        html_tabla = render_to_string('core/partials/tabla_ingresos.html', contexto_ajax)
        html_paginacion = render_to_string('core/partials/paginacion.html', {'page_obj': page_obj})
        
        return JsonResponse({
            'html_tabla': html_tabla, 
            'html_paginacion': html_paginacion,
            'grafico_labels': labels_grafico,
            'grafico_data': data_grafico
        })

    context = {
        'ingresos': page_obj,
        'empresas': empresas,
        'centros': centros,
        'clasificaciones': clasificaciones,
        'empresa_sel': int(f_empresa) if f_empresa else None,
        'centro_sel': int(f_centro) if f_centro else None,
        'clasif_sel': int(f_clasif) if f_clasif else None,
        'min_sel': f_min,
        'max_sel': f_max,
        'inicio_sel': f_fecha_inicio,
        'fin_sel': f_fecha_fin,
        'orden_sel': f_orden,
        'filtros_activos': any([f_empresa, f_centro, f_clasif, f_min, f_max, f_fecha_inicio, f_fecha_fin]),
        'per_page': int(por_pagina),
        'page_obj': page_obj,
        'labels_grafico': labels_grafico,
        'data_grafico': data_grafico,
    }
    return render(request, 'core/lista_ingresos.html', context)

@login_required
def nuevo_ingreso(request):
    if request.method == 'POST':
        form = IngresoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Registro guardado correctamente.')
            return redirect('dashboard')
    else:
        form = IngresoForm()
    return render(request, 'core/nuevo_ingreso.html', {'form': form})

@login_required
def editar_ingreso(request, id):
    ingreso = get_object_or_404(Ingreso, id=id)
    if request.method == 'POST':
        form = IngresoForm(request.POST, instance=ingreso)
        if form.is_valid():
            form.save()
            messages.success(request, 'Registro actualizado correctamente.')
            return redirect('lista_ingresos')
    else:
        form = IngresoForm(instance=ingreso)
    return render(request, 'core/editar_ingreso.html', {'form': form, 'ingreso': ingreso})

@login_required
def eliminar_ingreso(request, id):
    ingreso = get_object_or_404(Ingreso, id=id)
    ingreso.delete()
    messages.success(request, 'Registro eliminado correctamente.')
    return redirect('lista_ingresos')
@login_required
def importar_excel(request):
    """Importador con AUTO-CREACIÓN de Categorías y Centros de Costo"""
    if request.method == 'POST':
        form = CargaExcelForm(request.POST, request.FILES)
        if form.is_valid():
            archivo = request.FILES['archivo_excel']
            creados = 0
            nuevos_datos = 0 # Contador para saber cuántas categorías nuevas creamos
            
            try:
                # 1. Leer Excel (Fila 6 como encabezado)
                try:
                    df = pd.read_excel(archivo, sheet_name='REGISTRO EGRESOS', header=5)
                except:
                    df = pd.read_excel(archivo, header=5)

                df.columns = df.columns.str.strip()

                if 'Fecha' not in df.columns or 'Monto Transferencia' not in df.columns:
                    messages.error(request, 'Error: No se encontraron columnas "Fecha" o "Monto Transferencia" en la fila 6.')
                    return redirect('importar_excel')

                with transaction.atomic():
                    for index, row in df.iterrows():
                        # Validar Fecha y Monto
                        fecha = row.get('Fecha')
                        if pd.isnull(fecha): continue
                        
                        monto = row.get('Monto Transferencia', 0)
                        if pd.isnull(monto) or monto == 0: continue

                        # --- AQUÍ ESTÁ EL CAMBIO MÁGICO: get_or_create ---
                        
                        # 1. Empresa (Si no existe, la crea)
                        nombre_empresa = str(row.get('Empresa', '')).strip()
                        empresa_obj = None
                        if nombre_empresa and nombre_empresa.lower() != 'nan':
                            empresa_obj, created = Empresa.objects.get_or_create(
                                nombre__iexact=nombre_empresa, 
                                defaults={'nombre': nombre_empresa}
                            )

                        # 2. Centro de Costo (Si no existe, lo crea)
                        nombre_centro = str(row.get('Centro de Costo', '')).strip()
                        centro_obj = None
                        if nombre_centro and nombre_centro.lower() != 'nan':
                            centro_obj, _ = CentroCosto.objects.get_or_create(
                                nombre__iexact=nombre_centro,
                                defaults={'nombre': nombre_centro}
                            )

                        # 3. Clasificación (Si no existe, la crea)
                        nombre_clasif = str(row.get('Clasificación', '')).strip()
                        clasif_obj = None
                        if nombre_clasif and nombre_clasif.lower() != 'nan':
                            clasif_obj, _ = Clasificacion.objects.get_or_create(
                                nombre__iexact=nombre_clasif,
                                defaults={'nombre': nombre_clasif}
                            )

                        # Datos de Texto
                        desc_movimiento = str(row.get('Descripcion de Movimiento', 'Sin descripción')).strip()
                        if desc_movimiento.lower() == 'nan': desc_movimiento = 'Sin descripción'

                        detalle_txt = str(row.get('Detalle', '')).strip()
                        if detalle_txt.lower() == 'nan': detalle_txt = ''
                        
                        n_doc = row.get('N° DOCUMENTO')
                        if not pd.isnull(n_doc):
                            detalle_txt = f"Doc: {n_doc} - {detalle_txt}"

                        tipo_doc = str(row.get('Tipo', 'GASTO')).strip()
                        
                        # Guardar
                        Ingreso.objects.create(
                            fecha=fecha,
                            monto_transferencia=monto,
                            descripcion_movimiento=desc_movimiento,
                            tipo_documento=tipo_doc,
                            detalle=detalle_txt,
                            empresa=empresa_obj,       # Ahora sí llevará dato
                            centro_costo=centro_obj,   # Ahora sí llevará dato
                            clasificacion=clasif_obj,  # Ahora sí llevará dato
                            iva=0
                        )
                        creados += 1

                messages.success(request, f'¡Listo! Se cargaron {creados} registros y se crearon las categorías faltantes automáticamente.')

            except Exception as e:
                messages.error(request, f"Error técnico: {str(e)}")
                print(f"Error completo: {e}")
                
            return redirect('importar_excel')
    else:
        form = CargaExcelForm()
        
    return render(request, 'core/importar.html', {'form': form})

@login_required
def descargar_plantilla(request):
    ejemplo = {
        'Fecha': ['01/12/2025'],
        'Empresa': ['Nombre Empresa'],
        'Centro de Costo': ['Administracion'],
        'Clasificación': ['Insumos'],
        'N° DOCUMENTO': ['12345'],
        'Monto Transferencia': [50000],
        'Descripcion de Movimiento': ['Compra'],
        'Estado': ['Pagado'],
        'Detalle': ['Papeleria'],
        'Tipo': ['GASTO']
    }
    df = pd.DataFrame(ejemplo)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='REGISTRO EGRESOS', index=False, startrow=5)
    
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=plantilla_importacion.xlsx'
    return response


# =========================================================
# 4. MÓDULO CAJA CHICA
# =========================================================
@login_required
def lista_caja_chica(request):
    gastos = CajaChica.objects.all().order_by('-fecha')

    resumen_meses = CajaChica.objects.annotate(mes=TruncMonth('fecha'))\
                                     .values('mes')\
                                     .annotate(total=Sum('monto'))\
                                     .order_by('mes')

    labels = []
    data = []
    for registro in resumen_meses:
        if registro['mes']:
            labels.append(registro['mes'].strftime('%B %Y')) 
            data.append(registro['total'])

    context = {
        'gastos': gastos,
        'labels_grafico': labels,
        'data_grafico': data,
    }
    return render(request, 'core/caja_chica_lista.html', context)

@login_required
def caja_chica_crear(request):
    if request.method == 'POST':
        form = CajaChicaForm(request.POST, request.FILES)
        if form.is_valid():
            gasto = form.save(commit=False)
            gasto.responsable = request.user
            gasto.save()
            messages.success(request, 'Gasto registrado correctamente.')
            return redirect('lista_caja_chica')
    else:
        form = CajaChicaForm()
    return render(request, 'core/caja_chica_form.html', {'form': form, 'titulo': 'Nuevo Gasto'})

@login_required
def caja_chica_editar(request, id):
    gasto = get_object_or_404(CajaChica, id=id)
    if request.method == 'POST':
        form = CajaChicaForm(request.POST, request.FILES, instance=gasto)
        if form.is_valid():
            form.save()
            messages.success(request, 'Gasto actualizado.')
            return redirect('lista_caja_chica')
    else:
        form = CajaChicaForm(instance=gasto)
    return render(request, 'core/caja_chica_form.html', {'form': form, 'titulo': 'Editar Gasto'})

@login_required
def caja_chica_eliminar(request, id):
    gasto = get_object_or_404(CajaChica, id=id)
    gasto.delete()
    messages.success(request, 'Gasto eliminado.')
    return redirect('lista_caja_chica')

@login_required
def exportar_caja_chica_pdf(request):
    gastos = CajaChica.objects.all().order_by('-fecha')
    total_gasto = gastos.aggregate(Sum('monto'))['monto__sum'] or 0
    
    context = {
        'gastos': gastos,
        'total_gasto': total_gasto,
        'fecha_emision': datetime.datetime.now(),
        'usuario': request.user,
        'empresa_nombre': "SAMKA / MAQUEHUE",
    }
    
    html_string = render_to_string('core/pdf/reporte_caja.html', context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="rendicion_caja_chica.pdf"'
    
    if HTML:
        HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf(response)
    else:
        return HttpResponse("Error: La librería de PDF no está configurada (Falta GTK).")
    return response


# =========================================================
# 5. MÓDULO RRHH (Trabajadores y Finiquitos)
# =========================================================
@login_required
def dashboard_rrhh(request):
    filtro_empresa = request.GET.get('empresa', '')
    workers_queryset = Trabajador.objects.all()

    nombre_empresa_seleccionada = "Todas las Empresas"
    if filtro_empresa == 'Samka':
        workers_queryset = workers_queryset.filter(empresa__nombre__icontains='Samka')
        nombre_empresa_seleccionada = "Samka SPA"
    elif filtro_empresa == 'Maquehue':
        workers_queryset = workers_queryset.filter(empresa__nombre__icontains='Maquehue')
        nombre_empresa_seleccionada = "Maquehue SPA"

    samka_activos = Trabajador.objects.filter(empresa__nombre__icontains='Samka', fecha_finiquito__isnull=True).count()
    samka_finiquitados = Trabajador.objects.filter(empresa__nombre__icontains='Samka', fecha_finiquito__isnull=False).count()
    maquehue_activos = Trabajador.objects.filter(empresa__nombre__icontains='Maquehue', fecha_finiquito__isnull=True).count()
    maquehue_finiquitados = Trabajador.objects.filter(empresa__nombre__icontains='Maquehue', fecha_finiquito__isnull=False).count()
    total_activos = samka_activos + maquehue_activos
    total_finiquitados = samka_finiquitados + maquehue_finiquitados

    activos_resumen = workers_queryset.values('empresa__nombre', 'cargo').annotate(
        total=Count('id'),
        activos=Count('id', filter=Q(fecha_finiquito__isnull=True)),
        finiquitados=Count('id', filter=Q(fecha_finiquito__isnull=False))
    ).order_by('empresa__nombre', '-activos')
    
    finiquitos = workers_queryset.filter(fecha_finiquito__isnull=False)\
                                 .annotate(mes=TruncMonth('fecha_finiquito'))\
                                 .values('mes')\
                                 .annotate(total=Sum('monto_finiquito'))\
                                 .order_by('mes')

    labels_grafico = [f.get('mes').strftime('%Y-%m') for f in finiquitos if f.get('mes')]
    data_grafico = [f.get('total') for f in finiquitos if f.get('mes')]

    lista_trabajadores = workers_queryset.order_by('empresa', 'nombre')

    if request.GET.get('modo_ajax') == 'true':
        html_tabla = render_to_string(
            'core/partials/tabla_trabajadores.html', 
            {'lista_trabajadores': lista_trabajadores},
            request=request
        )
        return JsonResponse({
            'html_tabla': html_tabla,
            'labels_grafico': labels_grafico,
            'data_grafico': data_grafico,
            'titulo_pagina': nombre_empresa_seleccionada
        })

    context = {
        'lista_trabajadores': lista_trabajadores,
        'activos_resumen': activos_resumen,
        'labels_grafico': labels_grafico,
        'data_grafico': data_grafico,
        'nombre_empresa': nombre_empresa_seleccionada,
        'samka_activos': samka_activos,
        'samka_finiquitados': samka_finiquitados,
        'maquehue_activos': maquehue_activos,
        'maquehue_finiquitados': maquehue_finiquitados,
        'total_activos': total_activos,
        'total_finiquitados': total_finiquitados,
    }
    return render(request, 'core/dashboard_rrhh.html', context)

@login_required
def importar_rrhh(request):
    """Importador Avanzado RRHH"""
    if request.method == 'POST' and request.FILES.get('archivo_excel'):
        archivo = request.FILES['archivo_excel']
        try:
            xls = pd.ExcelFile(archivo, engine='openpyxl')
            hojas = xls.sheet_names
            texto_hojas = "".join(str(h).upper() for h in hojas)
            
            empresa_archivo = None
            if "SAMKA" in texto_hojas and "MAQUEHUE" not in texto_hojas:
                empresa_archivo, _ = Empresa.objects.get_or_create(nombre="Samka SPA")
            elif "MAQUEHUE" in texto_hojas and "SAMKA" not in texto_hojas:
                empresa_archivo, _ = Empresa.objects.get_or_create(nombre="Maquehue SPA")
            
            trabajadores_batch = {} 
            
            for nombre_hoja in hojas:
                nombre_upper = str(nombre_hoja).upper()
                empresa_hoja = None
                if "SAMKA" in nombre_upper:
                    empresa_hoja, _ = Empresa.objects.get_or_create(nombre="Samka SPA")
                elif "MAQUEHUE" in nombre_upper:
                    empresa_hoja, _ = Empresa.objects.get_or_create(nombre="Maquehue SPA")
                
                if not empresa_hoja and ("FINIQUITADO" in nombre_upper or "PERSONAL" in nombre_upper):
                    empresa_hoja = empresa_archivo
                
                if not empresa_hoja: continue 

                df = pd.read_excel(archivo, sheet_name=nombre_hoja)
                df.columns = df.columns.str.strip().str.upper()

                if 'RUT' not in df.columns or 'NOMBRE' not in df.columns: continue

                es_hoja_finiquito = "FINIQUITADO" in nombre_upper or "PERSONAL" in nombre_upper

                for index, row in df.iterrows():
                    rut = str(row.get('RUT', '')).strip().upper()
                    if not rut or len(rut) < 3 or rut == 'NAN': continue

                    nombre = str(row.get('NOMBRE', '')).strip()
                    cargo_txt = str(row.get('CARGO', 'Operario')).strip()
                    if cargo_txt.upper() == 'NAN': cargo_txt = 'Operario'
                    
                    fecha_inicio = row.get('CONTRATO')
                    if pd.isnull(fecha_inicio): fecha_inicio = None
                    
                    fecha_fin = row.get('FINIQUITO')
                    if pd.isnull(fecha_fin) or isinstance(fecha_fin, (int, float)):
                         fecha_fin = None
                    
                    monto = 0
                    if 'FINIQUITO.1' in df.columns:
                        val_monto = row.get('FINIQUITO.1', 0)
                        if isinstance(val_monto, (int, float)) and not pd.isna(val_monto):
                            monto = val_monto
                    
                    estado_nuevo = 'ACTIVO'
                    if fecha_fin or es_hoja_finiquito:
                        estado_nuevo = 'FINIQUITADO'

                    if rut in trabajadores_batch:
                        previo = trabajadores_batch[rut]
                        if previo['estado'] == 'FINIQUITADO':
                            if not previo['fecha_contrato'] and fecha_inicio:
                                previo['fecha_contrato'] = fecha_inicio
                            if not previo['monto_finiquito'] and monto > 0:
                                previo['monto_finiquito'] = monto
                            if not previo['fecha_finiquito'] and fecha_fin:
                                previo['fecha_finiquito'] = fecha_fin
                            continue
                    
                    trabajadores_batch[rut] = {
                        'nombre': nombre,
                        'cargo_txt': cargo_txt,
                        'empresa': empresa_hoja,
                        'fecha_contrato': fecha_inicio,
                        'fecha_finiquito': fecha_fin,
                        'monto_finiquito': monto,
                        'estado': estado_nuevo
                    }

            creados = 0
            actualizados = 0
            
            with transaction.atomic():
                for rut, data in trabajadores_batch.items():
                    cargo_obj, _ = Cargo.objects.get_or_create(
                        nombre__iexact=data['cargo_txt'],
                        defaults={'nombre': data['cargo_txt']}
                    )
                    
                    defaults = {
                        'nombre': data['nombre'],
                        'cargo': cargo_obj,
                        'empresa': data['empresa'],
                        'fecha_contrato': data['fecha_contrato'],
                        'estado': data['estado']
                    }
                    
                    if data['fecha_finiquito']:
                        defaults['fecha_finiquito'] = data['fecha_finiquito']
                    elif data['estado'] == 'ACTIVO':
                        defaults['fecha_finiquito'] = None
                        
                    if data['monto_finiquito'] > 0:
                        defaults['monto_finiquito'] = data['monto_finiquito']

                    obj, created = Trabajador.objects.update_or_create(
                        rut=rut,
                        defaults=defaults
                    )
                    if created: creados += 1
                    else: actualizados += 1

            messages.success(request, f'Procesado correctamente: {creados} nuevos, {actualizados} actualizados.')
            return redirect('dashboard_rrhh')

        except Exception as e:
            print(f"ERROR IMPT: {e}")
            messages.error(request, f"Error al importar: {str(e)}")

    return render(request, 'core/importar_rrhh.html')

@login_required
def nuevo_trabajador(request):
    if request.method == 'POST':
        form = TrabajadorForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Trabajador registrado.')
            return redirect('dashboard_rrhh')
    else:
        form = TrabajadorForm()
    return render(request, 'core/nuevo_trabajador.html', {'form': form})

@login_required
def editar_trabajador(request, id):
    trabajador = get_object_or_404(Trabajador, id=id)
    if request.method == 'POST':
        form = TrabajadorForm(request.POST, instance=trabajador)
        if form.is_valid():
            form.save()
            messages.success(request, f'Datos de {trabajador.nombre} actualizados.')
            return redirect('dashboard_rrhh')
    else:
        form = TrabajadorForm(instance=trabajador)
    return render(request, 'core/nuevo_trabajador.html', {'form': form, 'titulo': 'Editar Trabajador'})


# =========================================================
# 6. MÓDULO LOGÍSTICA / INVENTARIO
# =========================================================
@login_required
def inventario_dashboard(request):
    """Panel de Control de Stock y Vencimientos"""
    hoy = datetime.date.today()
    fecha_limite = hoy + datetime.timedelta(days=30) 

    # 1. LOTES EN PELIGRO
    lotes_vencidos = Lote.objects.filter(fecha_vencimiento__lt=hoy)
    lotes_por_vencer = Lote.objects.filter(fecha_vencimiento__range=[hoy, fecha_limite])

    # 2. INVENTARIO COMPLETO
    productos = Producto.objects.all()

    alerta_roja = lotes_vencidos.count()
    alerta_amarilla = lotes_por_vencer.count()

    context = {
        'lotes_vencidos': lotes_vencidos,
        'lotes_por_vencer': lotes_por_vencer,
        'productos': productos,
        'alerta_roja': alerta_roja,
        'alerta_amarilla': alerta_amarilla,
        'hoy': hoy,
    }
    return render(request, 'core/inventario/dashboard.html', context)

@login_required
def ingresar_lote(request):
    """Formulario para ingresar stock nuevo"""
    if request.method == 'POST':
        form = LoteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Lote ingresado correctamente.')
            return redirect('inventario_dashboard')
    else:
        form = LoteForm()
    
    return render(request, 'core/inventario/form_lote.html', {'form': form})


# =========================================================
# 7. MÓDULO USUARIOS Y LOGIN
# =========================================================
@login_required
def registro_usuario(request):
    if not request.user.is_superuser:
        messages.error(request, 'Acceso denegado.')
        return redirect('dashboard')

    if request.method == 'POST':
        form = RegistroUsuarioForm(request.POST)
        if form.is_valid():
            user = form.save()
            try:
                grupo = Group.objects.get(name='Digitadores')
                user.groups.add(grupo)
            except Group.DoesNotExist: pass
            messages.success(request, f'Usuario {user.username} creado.')
            return redirect('dashboard')
    else:
        form = RegistroUsuarioForm()
    return render(request, 'registration/registro.html', {'form': form})

@login_required
def perfil_usuario(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user) 
            messages.success(request, 'Contraseña actualizada.')
            return redirect('perfil_usuario')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'core/perfil.html', {'form': form})

class CustomLoginView(LoginView):
    """Login para usuarios normales (Azul)"""
    template_name = 'core/login.html'
    redirect_authenticated_user = True 

    def form_valid(self, form):
        recuerdame = self.request.POST.get('recuerdame')
        if recuerdame:
            self.request.session.set_expiry(1209600)
        else:
            self.request.session.set_expiry(0)
        return super().form_valid(form)

# core/views.py (Al final del archivo)

class AdminLoginView(CustomLoginView):
    """Login para administradores (Oscuro)"""
    template_name = 'core/login_admin.html'
    
    # AGREGA ESTA LÍNEA PARA ROMPER EL BUCLE:
    redirect_authenticated_user = False


# =========================================================
# 8. MÓDULO INTELIGENCIA ARTIFICIAL
# =========================================================
@login_required
def api_entrenar_ia(request):
    exito, mensaje = entrenar_modelo()
    return JsonResponse({'status': 'ok' if exito else 'error', 'mensaje': mensaje})

@login_required
def api_predecir_categoria(request):
    texto = request.GET.get('texto', '')
    sugerencia = predecir_categoria(texto)
    return JsonResponse({'categoria': sugerencia if sugerencia else None})

@login_required
def salida_stock(request):
    """Descuenta stock usando lógica FIFO (Lo primero que vence es lo primero que sale)"""
    if request.method == 'POST':
        form = SalidaStockForm(request.POST)
        if form.is_valid():
            producto = form.cleaned_data['producto']
            cantidad_solicitada = form.cleaned_data['cantidad']

            # 1. Verificar Stock Total
            stock_actual = producto.lote_set.aggregate(total=Sum('cantidad'))['total'] or 0
            
            if cantidad_solicitada > stock_actual:
                messages.error(request, f'Error: No hay suficiente stock. Tienes {stock_actual}, pides {cantidad_solicitada}.')
            else:
                # 2. Lógica FIFO (First In, First Out)
                # Traemos los lotes ordenados por vencimiento (el más viejo primero)
                lotes = Lote.objects.filter(producto=producto).order_by('fecha_vencimiento')
                
                cantidad_pendiente = cantidad_solicitada
                
                with transaction.atomic():
                    for lote in lotes:
                        if cantidad_pendiente <= 0:
                            break
                        
                        if lote.cantidad <= cantidad_pendiente:
                            # Este lote se agota completo
                            cantidad_pendiente -= lote.cantidad
                            lote.delete() # Lo borramos para que no genere alertas de vencimiento vacías
                        else:
                            # Este lote tiene suficiente para cubrir lo que falta
                            lote.cantidad -= cantidad_pendiente
                            lote.save()
                            cantidad_pendiente = 0
                
                messages.success(request, f'Se despacharon {cantidad_solicitada} unidades de {producto.nombre} correctamente.')
                return redirect('inventario_dashboard')
    else:
        form = SalidaStockForm()

    return render(request, 'core/inventario/form_salida.html', {'form': form})

@login_required
def enviar_alerta_vencimientos(request):
    """Revisa lotes por vencer y envía un correo al usuario actual."""
    hoy = datetime.date.today()
    fecha_limite = hoy + datetime.timedelta(days=30) 

    # Buscamos lo crítico
    lotes_vencidos = Lote.objects.filter(fecha_vencimiento__lt=hoy)
    lotes_por_vencer = Lote.objects.filter(fecha_vencimiento__range=[hoy, fecha_limite])

    # Si no hay nada urgente, no molestamos
    if not lotes_vencidos.exists() and not lotes_por_vencer.exists():
        messages.info(request, 'No hay productos en riesgo para reportar.')
        return redirect('inventario_dashboard')

    try:
        # Preparamos el mensaje (Asunto y Cuerpo)
        asunto = f"⚠️ ALERTA DE STOCK - {hoy.strftime('%d/%m/%Y')}"
        
        mensaje_html = render_to_string('core/emails/alerta_stock.html', {
            'lotes_vencidos': lotes_vencidos,
            'lotes_por_vencer': lotes_por_vencer,
            'usuario': request.user
        })

        # Enviamos el correo al usuario que está conectado
        send_mail(
            subject=asunto,
            message="", # Mensaje plano vacío porque usamos HTML
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email], 
            html_message=mensaje_html,
            fail_silently=False,
        )

        messages.success(request, f'Informe enviado correctamente a {request.user.email}')
    
    except Exception as e:
        messages.error(request, f'Error al enviar correo: {str(e)}')
        print(f"Error Email: {e}")

    return redirect('inventario_dashboard')


@login_required
def centro_datos(request):
    """Vista principal del panel de exportación"""
    return render(request, 'core/exportar_datos.html')

@login_required
def exportar_finanzas_csv(request):
    """Genera un CSV con todos los gastos e ingresos listo para Power BI"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="dataset_finanzas.csv"'

    writer = csv.writer(response)
    # Encabezados limpios
    writer.writerow(['ID', 'Fecha', 'Año', 'Mes', 'Tipo', 'Empresa', 'Centro Costo', 'Clasificacion', 'Descripcion', 'Detalle', 'Monto'])

    # Consultamos optimizando las relaciones (select_related) para que sea rápido
    movimientos = Ingreso.objects.select_related('empresa', 'centro_costo', 'clasificacion').all().order_by('-fecha')

    for mov in movimientos:
        writer.writerow([
            mov.id,
            mov.fecha,
            mov.fecha.year,
            mov.fecha.month,
            mov.tipo_documento,
            mov.empresa.nombre if mov.empresa else 'Sin Asignar',
            mov.centro_costo.nombre if mov.centro_costo else 'General',
            mov.clasificacion.nombre if mov.clasificacion else 'Sin Clasificar',
            mov.descripcion_movimiento, # Nombre real en tu BD
            mov.detalle,
            mov.monto_transferencia
        ])

    return response

@login_required
def exportar_inventario_csv(request):
    """Genera un CSV con el estado actual del stock (Lotes)"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="dataset_stock_actual.csv"'

    writer = csv.writer(response)
    writer.writerow(['SKU', 'Producto', 'Categoria', 'Nro Lote', 'Fecha Vencimiento', 'Dias para Vencer', 'Estado', 'Cantidad Stock'])

    lotes = Lote.objects.select_related('producto').all().order_by('fecha_vencimiento')
    hoy = datetime.date.today()

    for lote in lotes:
        # Calculamos estado para análisis
        dias = (lote.fecha_vencimiento - hoy).days
        estado = "VENCIDO" if dias < 0 else "POR VENCER" if dias <= 30 else "OK"

        writer.writerow([
            lote.producto.codigo,
            lote.producto.nombre,
            lote.producto.categoria,
            lote.numero_lote,
            lote.fecha_vencimiento,
            dias,
            estado,
            lote.cantidad
        ])

    return response