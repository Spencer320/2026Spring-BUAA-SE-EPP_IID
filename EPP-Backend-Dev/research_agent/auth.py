"""JWT 用户鉴权（语义与 business.utils.authenticate.authenticate_user 一致，供本 app 独立使用）。"""

from django.conf import settings

from business.models import User
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
