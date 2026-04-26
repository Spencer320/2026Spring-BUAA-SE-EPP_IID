"""JWT 鉴权（用户/管理员），供 research_agent 模块独立使用。"""

from django.conf import settings

from business.models import Admin, User
from business.utils.jwt_provider import JwtExpiredError, JwtInvalidError, JwtProvider
from business.utils.response import unauthorized

JWT = JwtProvider(settings.JWT_SECRET_KEY)


def authenticate_research_user(func):
    def wrapper(request, *args, **kwargs):
        token = request.headers.get("Authorization")
        try:
            payload = JWT.decode(token)
        except JwtExpiredError:
            return unauthorized(err="Token expired.")
        except JwtInvalidError:
            return unauthorized(err="Please login first.")
        if payload.get("role") != "user":
            return unauthorized(err="Please login as a USER first.")
        user_id = payload.get("user_id")
        user = User.objects.filter(user_id=user_id).first()
        if user is None:
            return unauthorized(err="Please login first.")
        return func(request, user, *args, **kwargs)

    return wrapper


def authenticate_research_admin(func):
    def wrapper(request, *args, **kwargs):
        token = request.headers.get("Authorization")
        try:
            payload = JWT.decode(token)
        except JwtExpiredError:
            return unauthorized(err="Token expired.")
        except JwtInvalidError:
            return unauthorized(err="Please login first.")
        if payload.get("role") != "admin":
            return unauthorized(err="Please login as an ADMIN first.")
        admin_id = payload.get("admin_id")
        admin = Admin.objects.filter(admin_id=admin_id).first()
        if admin is None:
            return unauthorized(err="Please login as admin first.")
        return func(request, admin, *args, **kwargs)

    return wrapper
