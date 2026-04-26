"""科研助手本地鉴权：不依赖 business 用户模型与工具。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps

import jwt
from django.conf import settings
from django.http import JsonResponse


@dataclass(frozen=True)
class ResearchIdentity:
    user_id: str
    role: str = "user"
    auth_source: str = "unknown"


def _unauthorized(message: str) -> JsonResponse:
    return JsonResponse(
        {"ok": False, "error": {"code": "UNAUTHORIZED", "message": message}},
        status=401,
    )


def _extract_token(request) -> str:
    raw = (request.headers.get("Authorization") or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def _decode_legacy_jwt(token: str) -> ResearchIdentity | None:
    secret = getattr(settings, "JWT_SECRET_KEY", "")
    if not secret:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    role = str(payload.get("role", "user"))
    user_id = str(payload.get("user_id", "")).strip()
    if role != "user" or not user_id:
        return None
    return ResearchIdentity(user_id=user_id, role=role, auth_source="legacy_jwt")


def _extract_identity(request) -> ResearchIdentity | None:
    token = _extract_token(request)
    if token:
        ident = _decode_legacy_jwt(token)
        if ident is not None:
            return ident

    header_user = (request.headers.get("X-Research-User-Id") or "").strip()
    if header_user:
        return ResearchIdentity(user_id=header_user, auth_source="header")
    return None


def authenticate_research_user(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        identity = _extract_identity(request)
        if identity is None:
            return _unauthorized("Please login first.")
        return func(request, identity, *args, **kwargs)

    return wrapper
