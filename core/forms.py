from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db.models import Q

# Importamos todos los modelos en una sola línea para mantener el orden
from .models import (
    Ingreso, 
    Trabajador, 
    CajaChica, 
    Empresa, 
    CentroCosto, 
    Clasificacion, 
    Producto, 
    Lote
)
class CargaExcelForm(forms.Form):
    archivo_excel = forms.FileField(label="Selecciona tu archivo Excel")

class IngresoForm(forms.ModelForm):
    class Meta:
        model = Ingreso
        fields = '__all__'
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'descripcion_movimiento': forms.Textarea(attrs={'rows': 3}),
        }

class CajaChicaForm(forms.ModelForm):
    class Meta:
        model = CajaChica
        fields = '__all__'
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control'}),
            'responsable': forms.TextInput(attrs={'class': 'form-control'}),
            'negocio': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo_documento': forms.Select(attrs={'class': 'form-control'}),
            'comentario': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

class RutLoginForm(AuthenticationForm):
    username = forms.CharField(label='RUT (Solo números)', widget=forms.TextInput(attrs={
        'class': 'form-control', 
        'placeholder': 'Ej: 12345678', 
        'autofocus': True,
        'id': 'id_rut_cuerpo'
    }))
    password = forms.CharField(label='Contraseña', widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Ingrese su contraseña'
    }))

    def clean(self):
        cuerpo_rut = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if cuerpo_rut and password:
            try:
                # Algoritmo de validación y formateo de RUT para Login
                rut_limpio = str(int(cuerpo_rut))
                
                suma = 0
                multiplo = 2
                
                for c in reversed(rut_limpio):
                    suma += int(c) * multiplo
                    multiplo += 1
                    if multiplo == 8: multiplo = 2
                
                dv_calculado = 11 - (suma % 11)
                if dv_calculado == 11: dv = '0'
                elif dv_calculado == 10: dv = 'K'
                else: dv = str(dv_calculado)

                rut_completo = f"{rut_limpio}-{dv}"
                
                self.cleaned_data['username'] = rut_completo
                self.user_cache = authenticate(self.request, username=rut_completo, password=password)
                
                if self.user_cache is None:
                    raise self.get_invalid_login_error()
                else:
                    self.confirm_login_allowed(self.user_cache)
                    
            except ValueError:
                raise ValidationError("El RUT debe contener solo números.")

        return self.cleaned_data

class RegistroUsuarioForm(UserCreationForm):
    first_name = forms.CharField(label="Nombre", widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(label="Apellido", widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label="Correo Electrónico", widget=forms.EmailInput(attrs={'class': 'form-control'}))
    
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']

class TrabajadorForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtro de empresas
        self.fields['empresa'].queryset = Empresa.objects.filter(
            Q(nombre__icontains='Samka') | Q(nombre__icontains='Maquehue')
        )
        self.fields['empresa'].empty_label = "Seleccione Empresa..."

    class Meta:
        model = Trabajador
        fields = ['empresa', 'nombre', 'rut', 'cargo', 'fecha_contrato', 'fecha_finiquito', 'monto_finiquito']
        widgets = {
            'fecha_contrato': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'fecha_finiquito': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'empresa': forms.Select(attrs={'class': 'form-select'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre Completo'}),
            'rut': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '12.345.678-9'}),
            'cargo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Administrativo'}),
            'monto_finiquito': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
        }

    # --- VALIDACIÓN DE RUT ---
    def clean_rut(self):
        rut = self.cleaned_data.get('rut', '')
        # 1. Limpieza inicial
        rut_limpio = rut.replace('.', '').replace('-', '').upper().strip()
        
        if not rut_limpio or len(rut_limpio) < 2:
            raise ValidationError("El RUT ingresado no es válido.")

        # 2. Separar cuerpo y dígito verificador
        cuerpo = rut_limpio[:-1]
        dv = rut_limpio[-1]

        # 3. Validar que el cuerpo sean números
        if not cuerpo.isdigit():
            raise ValidationError("El RUT contiene caracteres inválidos.")

        # 4. Algoritmo Módulo 11
        suma = 0
        multiplo = 2
        for c in reversed(cuerpo):
            suma += int(c) * multiplo
            multiplo += 1
            if multiplo == 8: 
                multiplo = 2
        
        resultado = 11 - (suma % 11)
        dv_calculado = '0' if resultado == 11 else 'K' if resultado == 10 else str(resultado)

        # 5. Comparación
        if dv_calculado != dv:
            raise ValidationError(f"RUT inválido. El dígito verificador no coincide.")

        # 6. Devolver RUT formateado
        return f"{int(cuerpo):,}".replace(',', '.') + "-" + dv
    
class LoteForm(forms.ModelForm):
    class Meta:
        model = Lote
        fields = ['producto', 'numero_lote', 'fecha_vencimiento', 'cantidad']
        widgets = {
            'producto': forms.Select(attrs={'class': 'form-select'}),
            'numero_lote': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_vencimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'cantidad': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class SalidaStockForm(forms.Form):
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Producto a Despachar"
    )
    cantidad = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label="Cantidad (Unidades)"
    )