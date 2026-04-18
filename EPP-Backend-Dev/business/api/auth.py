"""
用户认证及管理员认证模块
登录、注册、登出、用户信息
"""

import json
from datetime import date

from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.contrib.auth.hashers import make_password, check_password

from business.utils.futures import deprecated
from business.utils.response import ok, fail
from business.utils.jwt_provider import JwtProvider
from business.models.admin import Admin
from business.models.statistic import UserDailyAddition
from business.models.user import User


JWT = JwtProvider(settings.JWT_SECRET_KEY)


@require_http_methods(["POST"])
def login(request):
    data = json.loads(request.body)
    username = data.get("username")
    password = data.get("userpassword")
    user = User.objects.filter(username=username).first()
    if user and check_password(password, user.password):
        request.session["username"] = user.username
        expired_time = request.session.get_expiry_date()
        jwt = JWT.encode("login", {"user_id": str(user.user_id), "role": "user"})
        return ok(
            {
                "expired_time": expired_time,
                "ULogin_legal": True,
                "user_id": user.user_id,
                "username": user.username,
                "avatar": user.avatar.url,
                "token": jwt,
            },
            msg="登录成功",
        )
    else:
        return fail({"ULogin_legal": False}, err="用户名或密码错误")


@require_http_methods(["POST"])
def signup(request):
    data = json.loads(request.body)
    username = data.get("username")
    password = make_password(data.get("password"))
    user = User.objects.filter(username=username).first()
    if user:
        return fail({"userExists": True}, err="用户名已存在")
    else:
        user = User(username=username, password=password)
        user.save()
        current_day = date.today()
        record = UserDailyAddition.objects.filter(date=current_day).first()
        if record:
            # 有记录
            record.addition += 1
            record.save()
        else:
            # 没有记录
            UserDailyAddition(addition=1).save()

        return ok(
            {
                "userExists": False,
                "user_id": user.user_id,
                "username": user.username,
                "avatar": user.avatar.url,
            },
            msg="注册成功",
        )


@require_http_methods(["GET"])
def logout(request):
    request.session.flush()
    return ok(msg="登出成功")


@deprecated("May no usage found")
@require_http_methods(["GET"])
def test_login(request):
    # TODO: Check the real usage of this api
    username = request.session.get("username")
    if not username:
        return fail(err="未登录")
    return ok({"username": username})


@require_http_methods(["POST"])
def manager_login(request):
    """管理员登录"""
    data = json.loads(request.body)
    username = data.get("managerName")
    password = data.get("manpassowrd")
    manager = Admin.objects.filter(admin_name=username).first()
    if manager and check_password(password, manager.password):
        request.session["managerName"] = manager.admin_name
        jwt = JWT.encode(
            "login-admin", {"admin_id": str(manager.admin_id), "role": "admin"}
        )
        return ok({"MLogin_legal": True, "token": jwt}, msg="登录成功")
    else:
        return fail({"MLogin_legal": False}, err="用户名或密码错误")


@require_http_methods(["GET"])
def manager_logout(request):
    request.session.flush()
    return ok(msg="登出成功")
