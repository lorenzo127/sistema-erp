from django import template

register = template.Library()

@register.filter
def dinero_hibrido(valor):
    """
    Formato Chileno Forzado:
    Siempre usa PUNTOS para separar miles.
    Ej: 1.000 | 100.000 | 1.000.000
    """
    try:
        val_float = float(valor)
        entero = int(val_float)
    except (ValueError, TypeError):
        return valor

    # Truco infalible: 
    # 1. Formateamos con comas (estándar python): "1,000,000"
    # 2. Reemplazamos todas las comas por puntos: "1.000.000"
    return f"{entero:,}".replace(",", ".")