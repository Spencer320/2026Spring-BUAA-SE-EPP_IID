from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management import BaseCommand

from business.models import Admin


class Command(BaseCommand):
    def handle(self, *args, **options):
        username = settings.ADMIN_USERNAME
        password = make_password(settings.ADMIN_PASSWORD)
        admin = Admin.objects.filter(admin_name=username).first()
        if admin is not None:
            admin.password = password
            admin.save()
            print(f"Updated the admin `{username}`")
        else:
            Admin(admin_name=username, password=password).save()
            print(f"Inserted the admin `{username}`")
