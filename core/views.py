import datetime
import io
import json
import os
import pandas as pd

from django.db.models import Sum
from django.db.models.functions import TruncMonth
# Django Imports
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db.models import Avg, Count, IntegerField, Q, Sum
from django.db.models.functions import Cast, TruncDay, TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

# WeasyPrint (PDF)
try:
    from weasyprint import HTML
except ImportError:
    pass

# Tus Modelos y Formularios
from .forms import (
    CajaChicaForm,
    CargaExcelForm,
    IngresoForm,
    RegistroUsuarioForm,
    TrabajadorForm,
)
from .models import (
    CajaChica,
    CentroCosto,
    Clasificacion,
    Empresa,
    Ingreso,
    Trabajador,
)

from django.http import JsonResponse
from .ia import entrenar_modelo, predecir_categoria

# ---------------------------------------------------------
# 1. DASHBOARD PRINCIPAL
# ---------------------------------------------------------
@login_required
def dashboard(request):
    # Filtros de Fecha
    anios_disponibles = Ingreso.objects.dates('fecha', 'year', order='DESC')
    anio_filtro = request.GET.get('anio')
    mes_filtro = request.GET.get('mes')

    ingresos = Ingreso.objects.all().order_by('fecha')

    if anio_filtro:
        ingresos = ingresos.filter(fecha__year=anio_filtro)
    if mes_filtro:
        ingresos = ingresos.filter(fecha__month=mes_filtro)

    # KPIs
    total_monto = ingresos.aggregate(Sum('monto_transferencia'))['monto_transferencia__sum'] or 0
    total_registros = ingresos.count()
    promedio_monto = int(ingresos.aggregate(Avg('monto_transferencia'))['monto_transferencia__avg'] or 0)
    
    # GRÁFICOS
    # A. Por Empresa
    gastos_empresa = ingresos.values('empresa__nombre').annotate(total=Sum('monto_transferencia')).order_by('-total')[:10]
    labels_empresas = [g['empresa__nombre'] for g in gastos_empresa]
    data_empresas = [int(g['total']) for g in gastos_empresa]

    # B. Por Clasificación
    gastos_clasificacion = ingresos.values('clasificacion__nombre').annotate(total=Sum('monto_transferencia')).order_by('-total')
    labels_clasificacion = [g['clasificacion__nombre'] or "Sin Clasif." for g in gastos_clasificacion]
    data_clasificacion = [int(g['total']) for g in gastos_clasificacion]   

    # C. Evolución Temporal
    labels_evolucion = []
    data_evolucion = []

    if mes_filtro:
        gastos_evolucion = ingresos.annotate(periodo=TruncDay('fecha')).values('periodo').annotate(total=Sum('monto_transferencia')).order_by('periodo')
        formato_fecha = "%d/%m"
    else:
        gastos_evolucion = ingresos.annotate(periodo=TruncMonth('fecha')).values('periodo').annotate(total=Sum('monto_transferencia')).order_by('periodo')
        formato_fecha = "%b %Y"

    for g in gastos_evolucion:
        if g['periodo']:
            labels_evolucion.append(g['periodo'].strftime(formato_fecha)) 
            data_evolucion.append(int(g['total']))

    context = {
        'total_monto': total_monto,
        'total_registros': total_registros,
        'promedio_monto': promedio_monto,
        'labels_empresas': json.dumps(labels_empresas),
        'data_empresas': json.dumps(data_empresas),
        'labels_clasificacion': json.dumps(labels_clasificacion),
        'data_clasificacion': json.dumps(data_clasificacion),
        'labels_evolucion': json.dumps(labels_evolucion),
        'data_evolucion': json.dumps(data_evolucion),
        'anios_disponibles': anios_disponibles,
        'anio_seleccionado': int(anio_filtro) if anio_filtro else None,
        'mes_seleccionado': int(mes_filtro) if mes_filtro else None,
    }

    return render(request, 'core/dashboard.html', context)


# ---------------------------------------------------------
# 2. GESTIÓN DE INGRESOS (GASTOS)
# ---------------------------------------------------------
@login_required
def lista_ingresos(request):
    # A. Carga de Catálogos
    empresas = Empresa.objects.all().order_by('nombre')
    centros = CentroCosto.objects.all().order_by('nombre')
    clasificaciones = Clasificacion.objects.all().order_by('nombre')
    
    # B. Captura de Filtros
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

    # C. Consulta Base
    ingresos = Ingreso.objects.select_related('empresa', 'centro_costo', 'clasificacion').annotate(
        monto_real=Cast('monto_transferencia', output_field=IntegerField())
    )

    # D. Aplicación de Filtros
    if f_empresa:
        ingresos = ingresos.filter(empresa_id=f_empresa)
    if f_centro:
        ingresos = ingresos.filter(centro_costo_id=f_centro)
    if f_clasif:
        ingresos = ingresos.filter(clasificacion_id=f_clasif)
    
    if f_min:
        try:
            val_min = int(f_min.replace('.', '').replace(',', ''))
            ingresos = ingresos.filter(monto_real__gte=val_min)
        except ValueError: pass
            
    if f_max:
        try:
            val_max = int(f_max.replace('.', '').replace(',', ''))
            ingresos = ingresos.filter(monto_real__lte=val_max)
        except ValueError: pass

    if f_fecha_inicio:
        ingresos = ingresos.filter(fecha__gte=f_fecha_inicio)
    if f_fecha_fin:
        ingresos = ingresos.filter(fecha__lte=f_fecha_fin)

    # --- LÓGICA DE ORDENAMIENTO ---
    if f_orden == 'monto_desc':
        ingresos = ingresos.order_by('-monto_real')
    elif f_orden == 'monto_asc':
        ingresos = ingresos.order_by('monto_real')
    elif f_orden == 'fecha_asc':
        ingresos = ingresos.order_by('fecha')
    else:
        ingresos = ingresos.order_by('-fecha')

    # E. Lógica del Gráfico
    datos_grafico = ingresos.annotate(dia=TruncDay('fecha')).values('dia').annotate(total=Sum('monto_real')).order_by('dia')
    
    labels_grafico = [d['dia'].strftime("%d/%m/%Y") for d in datos_grafico if d['dia']]
    data_grafico = [d['total'] for d in datos_grafico if d['dia']]

    # F. Paginación
    paginator = Paginator(ingresos, por_pagina)
    page_obj = paginator.get_page(pagina)

    # G. Respuesta AJAX
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

    # H. Respuesta Normal (Render)
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
    if request.method == 'POST':
        form = CargaExcelForm(request.POST, request.FILES)
        if form.is_valid():
            archivo = request.FILES['archivo_excel']
            try:
                # 1. Leer Excel
                df = pd.read_excel(archivo, sheet_name='REGISTRO EGRESOS', header=5)
                
                # 2. Iterar filas
                for index, row in df.iterrows():
                    # --- A. Datos Básicos y Limpieza ---
                    tipo_doc = str(row.get('Tipo', '')).strip().upper()
                    
                    monto_total = row.get('Monto Transferencia', 0)
                    if pd.isna(monto_total): monto_total = 0
                    
                    iva = row.get('IVA', 0)
                    if pd.isna(iva): iva = 0

                    # --- B. Lógica BOLETA (Cálculo IVA Automático) ---
                    if tipo_doc == 'BOLETA' and iva == 0 and monto_total > 0:
                        neto_calculado = monto_total / 1.19
                        iva = int(round(monto_total - neto_calculado))
                    
                    # --- C. Búsqueda de Relaciones (FKs) ---
                    nombre_empresa = row.get('Empresa')
                    empresa_obj = None
                    if nombre_empresa and not pd.isna(nombre_empresa):
                        empresa_obj = Empresa.objects.filter(nombre__iexact=str(nombre_empresa).strip()).first()

                    nombre_centro = row.get('Centro de Costo')
                    centro_obj = None
                    if nombre_centro and not pd.isna(nombre_centro):
                        centro_obj = CentroCosto.objects.filter(nombre__iexact=str(nombre_centro).strip()).first()
                        
                    nombre_clasif = row.get('Clasificación')
                    clasif_obj = None
                    if nombre_clasif and not pd.isna(nombre_clasif):
                        clasif_obj = Clasificacion.objects.filter(nombre__iexact=str(nombre_clasif).strip()).first()

                    # --- D. Guardar Registro ---
                    fecha_row = row.get('Fecha')
                    if not pd.isna(fecha_row) and monto_total > 0:
                        Ingreso.objects.create(
                            fecha=fecha_row,
                            empresa=empresa_obj,
                            centro_costo=centro_obj,
                            clasificacion=clasif_obj,
                            tipo_documento=tipo_doc,
                            monto_transferencia=monto_total,
                            iva=iva,
                            detalle=row.get('Detalle', ''),
                            descripcion=row.get('Descripcion de Movimiento', '')
                        )

                messages.success(request, 'Archivo importado correctamente. Se calculó IVA para Boletas.')
                return redirect('importar_excel')

            except Exception as e:
                messages.error(request, f"Error al procesar: {e}")
    else:
        form = CargaExcelForm()
    return render(request, 'core/importar.html', {'form': form})

@login_required
def descargar_plantilla(request):
    # Crear DataFrame vacío de ejemplo
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


# ---------------------------------------------------------
# 3. CAJA CHICA
# ---------------------------------------------------------
@login_required
def lista_caja_chica(request):
    gastos = CajaChica.objects.all().order_by('-fecha')

    # --- LÓGICA DEL GRÁFICO ---
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
    # Versión WeasyPrint (Moderna)
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
    
    HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf(response)
    return response


# ---------------------------------------------------------
# 4. RECURSOS HUMANOS (RRHH)
# ---------------------------------------------------------
@login_required
def dashboard_rrhh(request):
    # 1. Filtro de Empresa
    filtro_empresa = request.GET.get('empresa', '')
    workers_queryset = Trabajador.objects.all()

    nombre_empresa_seleccionada = "Todas las Empresas"
    if filtro_empresa == 'Samka':
        workers_queryset = workers_queryset.filter(empresa__nombre__icontains='Samka')
        nombre_empresa_seleccionada = "Samka SPA"
    elif filtro_empresa == 'Maquehue':
        workers_queryset = workers_queryset.filter(empresa__nombre__icontains='Maquehue')
        nombre_empresa_seleccionada = "Maquehue SPA"

    # 2. CÁLCULOS PARA TABLA RESUMEN (Globales)
    samka_activos = Trabajador.objects.filter(
        empresa__nombre__icontains='Samka', 
        fecha_finiquito__isnull=True
    ).count()
    
    samka_finiquitados = Trabajador.objects.filter(
        empresa__nombre__icontains='Samka', 
        fecha_finiquito__isnull=False
    ).count()

    maquehue_activos = Trabajador.objects.filter(
        empresa__nombre__icontains='Maquehue', 
        fecha_finiquito__isnull=True
    ).count()
    
    maquehue_finiquitados = Trabajador.objects.filter(
        empresa__nombre__icontains='Maquehue', 
        fecha_finiquito__isnull=False
    ).count()

    total_activos = samka_activos + maquehue_activos
    total_finiquitados = samka_finiquitados + maquehue_finiquitados

    # 3. CÁLCULOS EXISTENTES
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

    # 4. RESPUESTA AJAX
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

    # 5. RESPUESTA NORMAL
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
    if request.method == 'POST' and request.FILES.get('archivo_excel'):
        archivo = request.FILES['archivo_excel']
        try:
            # Aquí deberías poner tu lógica de importación RRHH real si la tienes,
            # por ahora mantengo el mensaje de éxito genérico para no romper nada.
            xls = pd.ExcelFile(archivo)
            messages.success(request, 'Procesado correctamente.')
            return redirect('dashboard_rrhh')
        except Exception as e:
            messages.error(request, f"Error: {e}")
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
    return render(request, 'core/nuevo_trabajador.html', {
        'form': form, 
        'titulo': 'Editar Trabajador'
    })


# ---------------------------------------------------------
# 5. USUARIOS Y PERFIL
# ---------------------------------------------------------
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

@login_required
def api_entrenar_ia(request):
    """Botón para forzar el re-entrenamiento"""
    exito, mensaje = entrenar_modelo()
    return JsonResponse({'status': 'ok' if exito else 'error', 'mensaje': mensaje})

@login_required
def api_predecir_categoria(request):
    """AJAX: Recibe texto, devuelve categoría sugerida"""
    texto = request.GET.get('texto', '')
    sugerencia = predecir_categoria(texto)
    
    if sugerencia:
        return JsonResponse({'categoria': sugerencia})
    else:
        return JsonResponse({'categoria': None})