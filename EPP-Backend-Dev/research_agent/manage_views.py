"""管理端：科研助手 / 深度研究任务列表与统计（按 Run 聚合，非逐步审计日志）。"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Max, Q
from django.utils import timezone as dj_tz
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from business.utils.response import fail, ok

from .auth import authenticate_research_admin
from .models import AgentBehaviorAuditLog, AgentTask, BasicOrchestratorRun, WorkspaceAgentRun
from .orchestrator import ACTIVE_STATUSES
from .run_registry import run_kind
from .views import (
    _extract_run_quota_tokens,
    _format_dt,
    _resolve_user_ids_by_name,
    _resolve_user_name_map,
    _task_progress_percent,
    _task_to_json,
)


def _parse_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_pagination(params: dict[str, Any]) -> tuple[int, int]:
    page_num = _parse_int_or_none(params.get("page_num")) or 1
    page_size = _parse_int_or_none(params.get("page_size")) or 20
    page_size = min(100, max(1, page_size))
    return max(1, page_num), page_size


def _extract_run_query(run) -> str:
    session = run.session
    title = str(getattr(session, "title", "") or "").strip()
    if title and title != "新会话":
        return title
    payload = run.result_payload if isinstance(run.result_payload, dict) else {}
    for key in ("query", "user_query", "question", "input"):
        text = str(payload.get(key, "") or "").strip()
        if text:
            return text
    rc = payload.get("runtime_config")
    if isinstance(rc, dict):
        for key in ("query", "user_query", "question"):
            text = str(rc.get(key, "") or "").strip()
            if text:
                return text
    return title or ""


def _apply_run_list_filters(qs, params: dict[str, Any], *, date_field: str = "created_at"):
    user_id = str(params.get("user_id", "") or "").strip()
    if user_id:
        qs = qs.filter(session__owner_id=user_id)

    username = str(params.get("username", "") or "").strip()
    if username:
        matched = _resolve_user_ids_by_name(username)
        if not matched:
            return qs.none()
        qs = qs.filter(session__owner_id__in=matched)

    keyword = str(params.get("keyword", "") or "").strip()
    if keyword:
        qs = qs.filter(
            Q(session__title__icontains=keyword)
            | Q(result_payload__icontains=keyword)
        )

    status_raw = str(params.get("status", "") or "").strip()
    if status_raw:
        statuses = [x.strip() for x in status_raw.split(",") if x.strip()]
        if statuses:
            qs = qs.filter(status__in=statuses)

    date_from = str(params.get("date_from", "") or "").strip()
    if date_from:
        from_date = parse_date(date_from)
        if from_date is None:
            return qs.none(), "date_from 格式无效"
        qs = qs.filter(**{f"{date_field}__date__gte": from_date})

    date_to = str(params.get("date_to", "") or "").strip()
    if date_to:
        to_date = parse_date(date_to)
        if to_date is None:
            return qs.none(), "date_to 格式无效"
        qs = qs.filter(**{f"{date_field}__date__lte": to_date})

    return qs, ""


def _annotate_dr_audit_stats(qs):
    return qs.annotate(
        log_count=Count("deep_behavior_audit_logs", distinct=True),
        exception_count=Count(
            "deep_behavior_audit_logs",
            filter=Q(deep_behavior_audit_logs__is_exception=True),
            distinct=True,
        ),
        last_audit_at=Max("deep_behavior_audit_logs__occurred_at"),
    )


def _annotate_assistant_audit_stats(qs):
    return qs.annotate(
        basic_log_count=Count("basic_behavior_audit_logs", distinct=True),
        workspace_log_count=Count(
            "workspace_children__workspace_behavior_audit_logs",
            distinct=True,
        ),
        basic_exception_count=Count(
            "basic_behavior_audit_logs",
            filter=Q(basic_behavior_audit_logs__is_exception=True),
            distinct=True,
        ),
        workspace_exception_count=Count(
            "workspace_children__workspace_behavior_audit_logs",
            filter=Q(workspace_children__workspace_behavior_audit_logs__is_exception=True),
            distinct=True,
        ),
        last_basic_audit_at=Max("basic_behavior_audit_logs__occurred_at"),
        last_workspace_audit_at=Max(
            "workspace_children__workspace_behavior_audit_logs__occurred_at"
        ),
        workspace_run_count=Count("workspace_children", distinct=True),
    )


def _run_to_manage_item(run, *, user_name: str) -> dict[str, Any]:
    current_phase = ""
    step_summary = ""
    if run.steps:
        last = run.steps[-1] if isinstance(run.steps[-1], dict) else {}
        current_phase = str(last.get("phase", "") or "")
        step_summary = str(last.get("message", "") or last.get("summary", "") or "")[:200]

    item: dict[str, Any] = {
        "task_id": str(run.id),
        "run_kind": run_kind(run),
        "session_id": str(run.session_id),
        "user_id": str(run.session.owner_id),
        "user_name": user_name,
        "username": user_name,
        "task_name": str(run.session.title or ""),
        "query": _extract_run_query(run),
        "status": run.status,
        "current_phase": current_phase,
        "progress": _task_progress_percent(run),
        "step_seq": int(run.step_seq or 0),
        "step_summary": step_summary,
        "created_at": _format_dt(run.created_at),
        "updated_at": _format_dt(run.updated_at),
        "error_code": run.error_code or "",
        "error_message": run.error_message or "",
    }

    if hasattr(run, "log_count"):
        item["log_count"] = int(run.log_count or 0)
    elif hasattr(run, "basic_log_count"):
        item["log_count"] = int(run.basic_log_count or 0) + int(
            getattr(run, "workspace_log_count", 0) or 0
        )
    if hasattr(run, "exception_count"):
        item["exception_count"] = int(run.exception_count or 0)
    elif hasattr(run, "basic_exception_count"):
        item["exception_count"] = int(run.basic_exception_count or 0) + int(
            getattr(run, "workspace_exception_count", 0) or 0
        )
    last_audit = None
    if hasattr(run, "last_audit_at") and run.last_audit_at:
        last_audit = run.last_audit_at
    else:
        candidates = [
            getattr(run, "last_basic_audit_at", None),
            getattr(run, "last_workspace_audit_at", None),
        ]
        candidates = [x for x in candidates if x]
        if candidates:
            last_audit = max(candidates)
    if last_audit:
        item["last_audit_at"] = _format_dt(last_audit)
    if hasattr(run, "workspace_run_count"):
        item["workspace_run_count"] = int(run.workspace_run_count or 0)

    tokens = _extract_run_quota_tokens(run)
    if tokens is not None:
        item["token_usage"] = tokens

    return item


def _paginate_queryset(qs, params: dict[str, Any]):
    page_num, page_size = _parse_pagination(params)
    sort_by = str(params.get("sort_by", "created_at") or "created_at").strip().lower()
    sort_order = str(params.get("sort_order", "desc") or "desc").strip().lower()
    order_field = "-created_at" if sort_order != "asc" else "created_at"
    if sort_by == "updated_at":
        order_field = "-updated_at" if sort_order != "asc" else "updated_at"
    elif sort_by == "status":
        order_field = "-status" if sort_order != "asc" else "status"
    qs = qs.order_by(order_field, "-id")

    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        page = paginator.page(1)

    user_ids = {str(obj.session.owner_id) for obj in page.object_list}
    user_name_map = _resolve_user_name_map(user_ids)
    items = [
        _run_to_manage_item(
            obj,
            user_name=user_name_map.get(str(obj.session.owner_id), str(obj.session.owner_id)),
        )
        for obj in page.object_list
    ]
    return {
        "total": paginator.count,
        "page_num": page.number,
        "page_size": page_size,
        "items": items,
    }


def _today_range():
    now = dj_tz.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_deep_research_stats(request, _admin):
    today_start, today_end = _today_range()
    base = AgentTask.objects.all()
    running = base.filter(status__in=["running", "pending_action"]).count()
    pending = base.filter(status="pending").count()
    today_qs = base.filter(created_at__gte=today_start, created_at__lt=today_end)
    return ok(
        {
            "running_count": running,
            "pending_count": pending,
            "today_total": today_qs.count(),
            "today_completed": today_qs.filter(status="completed").count(),
            "today_failed": today_qs.filter(status__in=["failed", "cancelled"]).count(),
            "total_count": base.count(),
        }
    )


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_deep_research_tasks(request, _admin):
    qs = _annotate_dr_audit_stats(AgentTask.objects.select_related("session"))
    qs, err = _apply_run_list_filters(qs, request.GET)
    if err:
        return fail({"error": err})
    payload = _paginate_queryset(qs, request.GET)
    payload["run_kind"] = "deep_research"
    return ok(payload)


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_deep_research_task_detail(request, _admin, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return fail({"error": "任务不存在"})
    try:
        task = _annotate_dr_audit_stats(
            AgentTask.objects.select_related("session").filter(id=tid)
        ).get()
    except AgentTask.DoesNotExist:
        return fail({"error": "任务不存在"})

    user_id = str(task.session.owner_id)
    user_name = _resolve_user_name_map({user_id}).get(user_id, user_id)
    detail = _run_to_manage_item(task, user_name=user_name)
    detail.update(_task_to_json(task))
    detail["steps"] = task.steps or []
    return ok(detail)


@require_http_methods(["POST"])
@authenticate_research_admin
def admin_deep_research_task_cancel(request, _admin, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return fail({"error": "任务不存在"})
    try:
        task = AgentTask.objects.get(id=tid)
    except AgentTask.DoesNotExist:
        return fail({"error": "任务不存在"})
    if task.status not in ACTIVE_STATUSES:
        return fail({"error": "任务当前状态不可取消"})
    task.status = "cancelled"
    task.intervention = None
    task.save(update_fields=["status", "intervention", "updated_at"])
    return ok({"task_id": str(task.id), "status": "cancelled"})


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_assistant_stats(request, _admin):
    today_start, today_end = _today_range()
    base = BasicOrchestratorRun.objects.all()
    running = base.filter(status__in=["running", "pending_action"]).count()
    pending = base.filter(status="pending").count()
    today_qs = base.filter(created_at__gte=today_start, created_at__lt=today_end)
    return ok(
        {
            "running_count": running,
            "pending_count": pending,
            "today_total": today_qs.count(),
            "today_completed": today_qs.filter(status="completed").count(),
            "today_failed": today_qs.filter(status__in=["failed", "cancelled"]).count(),
            "total_count": base.count(),
        }
    )


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_assistant_tasks(request, _admin):
    qs = _annotate_assistant_audit_stats(
        BasicOrchestratorRun.objects.select_related("session")
    )
    qs, err = _apply_run_list_filters(qs, request.GET)
    if err:
        return fail({"error": err})
    payload = _paginate_queryset(qs, request.GET)
    payload["run_kind"] = "basic"
    return ok(payload)


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_assistant_task_detail(request, _admin, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return fail({"error": "任务不存在"})
    try:
        task = _annotate_assistant_audit_stats(
            BasicOrchestratorRun.objects.select_related("session").filter(id=tid)
        ).get()
    except BasicOrchestratorRun.DoesNotExist:
        return fail({"error": "任务不存在"})

    user_id = str(task.session.owner_id)
    user_name = _resolve_user_name_map({user_id}).get(user_id, user_id)
    detail = _run_to_manage_item(task, user_name=user_name)
    detail.update(_task_to_json(task))
    detail["steps"] = task.steps or []
    child_ids = list(
        WorkspaceAgentRun.objects.filter(parent_basic_run_id=task.id).values_list("id", flat=True)
    )
    detail["workspace_child_ids"] = [str(x) for x in child_ids]
    return ok(detail)


@require_http_methods(["POST"])
@authenticate_research_admin
def admin_assistant_task_cancel(request, _admin, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return fail({"error": "任务不存在"})
    try:
        task = BasicOrchestratorRun.objects.get(id=tid)
    except BasicOrchestratorRun.DoesNotExist:
        return fail({"error": "任务不存在"})
    if task.status not in ACTIVE_STATUSES:
        return fail({"error": "任务当前状态不可取消"})
    task.status = "cancelled"
    task.intervention = None
    task.save(update_fields=["status", "intervention", "updated_at"])
    return ok({"task_id": str(task.id), "status": "cancelled"})
