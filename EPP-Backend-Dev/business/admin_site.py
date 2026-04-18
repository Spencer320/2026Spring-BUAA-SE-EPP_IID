from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password
from business.models.admin import Admin


class CustomAdminBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        admin = Admin.objects.filter(admin_name=username).first()
        if admin and check_password(password, admin.password):
            return admin
        return None

    def get_user(self, user_id):
        q = Admin.objects.filter(admin_id=user_id)
        if q.count() == 0:
            return None
        return q.first()
