from django import template
from django.contrib.auth.models import Group

register = template.Library()

@register.filter(name='has_group')
def has_group(user, group_name):
    # El superusuario (Admin) siempre tiene acceso a todo (True)
    if user.is_superuser:
        return True

    # Si el usuario pertenece al grupo solicitado devuelve True