from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        try:
            # Buscamos al usuario por su CORREO (email)
            # 'username' es lo que llega del formulario (el texto que escribió el usuario)
            user = UserModel.objects.get(email=username)
        except UserModel.DoesNotExist:
            return None
        else:
            # Si existe el correo, chequeamos la contraseña
            if user.check_password(password):
                return user
        return None