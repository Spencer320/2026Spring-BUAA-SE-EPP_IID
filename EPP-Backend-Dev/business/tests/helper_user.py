import uuid
from typing import Tuple

from django.contrib.auth.hashers import make_password


def insert_user() -> Tuple[str, str]:
    from business.models import User

    username = str(uuid.uuid4())
    password = str(uuid.uuid4())

    User.objects.create(username=username, password=make_password(password))
    return username, password


def login_user(client, username, password):
    response = client.post(
        "/api/login",
        data={"username": username, "userpassword": password},
        content_type="application/json",
    )
    return response


def insert_admin() -> Tuple[str, str]:
    from business.models import Admin

    username = str(uuid.uuid4())
    password = str(uuid.uuid4())

    Admin.objects.create(admin_name=username, password=make_password(password))
    return username, password


def login_admin(client, username, password):
    response = client.post(
        "/api/managerLogin",
        data={"managerName": username, "manpassowrd": password},
        content_type="application/json",
    )
    assert response.status_code == 200, f"Login failed, get {response.status_code}"
    return response
