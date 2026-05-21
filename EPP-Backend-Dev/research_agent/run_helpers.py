"""各编排器共用的轻量持久化与查询辅助（无业务阶段逻辑）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from django.db import connection, models
from django.utils import timezone

from .models import ResearchMessage, ResearchSession


def iso_ts(dt: datetime | None = None) -> str:
    if dt is None:
        dt = timezone.now()
    if timezone.is_naive(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_user_query(session: ResearchSession, *, default: str = "未提供用户请求") -> str:
    msg = (
        ResearchMessage.objects.filter(session=session, role="user")
        .order_by("-created_at")
        .first()
    )
    return (msg.content if msg else "").strip() or default


def runtime_config(run: Any) -> dict[str, Any]:
    payload = run.result_payload if isinstance(run.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    return cfg if isinstance(cfg, dict) else {}


def update_runtime_config(run: Any, **updates: Any) -> None:
    payload = run.result_payload if isinstance(run.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.update(updates)
    payload["runtime_config"] = cfg
    run.result_payload = payload


def task_for_update(model: type[models.Model], task_id: uuid.UUID):
    qs = model.objects.filter(id=task_id)
    if connection.vendor != "sqlite":
        qs = qs.select_for_update()
    return qs.get()
