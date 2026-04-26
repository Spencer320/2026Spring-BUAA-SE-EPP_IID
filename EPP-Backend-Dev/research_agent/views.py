import json
import uuid
from typing import Any

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpResponse, JsonResponse
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone as dj_tz
from django.views.decorators.http import require_http_methods
from business.utils.response import fail, ok
from .auth import authenticate_research_admin, authenticate_research_user, ResearchIdentity
from .models import AgentBehaviorAuditLog, AgentTask, ResearchMessage, ResearchSession
from .orchestrator import (
    ACTIVE_STATUSES,
    start_after_approve_thread,
    start_after_revise_thread,
    start_first_segment_thread,
)


def _json_ok(data: dict[str, Any], status: int = 200) -> JsonResponse:
    return JsonResponse({"ok": True, "data": data}, status=status)


def _json_err(msg: str, status: int = 400, code: str = "BAD_REQUEST") -> JsonResponse:
    return JsonResponse(
        {"ok": False, "error": {"code": code, "message": msg}},
        status=status,
    )


def _format_dt(dt) -> str:
    if dt is None:
        return ""
    from django.utils import timezone as dj_tz

    if dj_tz.is_naive(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.astimezone(dj_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _task_to_json(task: AgentTask) -> dict[str, Any]:
    err = None
    if task.error_code or task.error_message:
        err = {
            "code": task.error_code or "UNKNOWN",
            "message": task.error_message or "",
        }
    total_expected_steps = 6
    progress = int(min(100, (task.step_seq / total_expected_steps) * 100))
    if task.status == "completed":
        progress = 100
    elif task.status in ("failed", "cancelled"):
        progress = max(progress, 1)
    current_phase = ""
    if task.steps:
        current_phase = str(task.steps[-1].get("phase", "") or "")
    return {
        "task_id": str(task.id),
        "session_id": str(task.session_id),
        "status": task.status,
        "current_phase": current_phase,
        "progress": progress,
        "step_seq": task.step_seq,
        "updated_at": _format_dt(task.updated_at),
        "steps": task.steps or [],
        "intervention": task.intervention,
        "result": task.result_payload,
        "error": err,
    }


def _mark_local_command_approved(task: AgentTask) -> None:
    intervention = task.intervention if isinstance(task.intervention, dict) else {}
    if intervention.get("tool") != "local_command":
        return
    template = str(intervention.get("template", "")).strip()
    if not template:
        return
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        cfg = {}
    approved = cfg.get("approved_local_command_templates", [])
    if not isinstance(approved, list):
        approved = []
    if template not in approved:
        approved.append(template)
    cfg["approved_local_command_templates"] = approved
    payload["runtime_config"] = cfg
    task.result_payload = payload


def _active_task(session: ResearchSession) -> AgentTask | None:
    return (
        session.tasks.filter(status__in=["pending", "running", "pending_action"])
        .order_by("-created_at")
        .first()
    )


def _to_domain(url: str) -> str:
    from urllib.parse import urlparse

    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _ensure_json_obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_exception_flag(value: str) -> bool | None:
    v = (value or "").strip().lower()
    if v in ("", "all"):
        return None
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return None


def _apply_behavior_filters(
    qs,
    params: dict[str, Any],
    *,
    default_scope: bool = True,
):
    if default_scope:
        qs = qs.filter(task__status__in=[*ACTIVE_STATUSES, "completed"])

    user_id = str(params.get("user_id", "") or "").strip()
    if user_id:
        qs = qs.filter(task__session__user__user_id=user_id)

    task_id = str(params.get("task_id", "") or "").strip()
    if task_id:
        qs = qs.filter(task_id=task_id)

    target_domain = str(params.get("target_domain", "") or "").strip()
    if target_domain:
        qs = qs.filter(target_domain__icontains=target_domain.lower())

    operation_type = str(params.get("operation_type", "") or "").strip()
    if operation_type:
        qs = qs.filter(operation_type=operation_type)

    exception_status = _parse_exception_flag(str(params.get("exception_status", "")))
    if exception_status is True:
        qs = qs.filter(is_exception=True)
    elif exception_status is False:
        qs = qs.filter(is_exception=False)

    date_from = str(params.get("date_from", "") or "").strip()
    if date_from:
        from_date = parse_date(date_from)
        if from_date is None:
            return None, "date_from 格式无效"
        qs = qs.filter(occurred_at__date__gte=from_date)

    date_to = str(params.get("date_to", "") or "").strip()
    if date_to:
        to_date = parse_date(date_to)
        if to_date is None:
            return None, "date_to 格式无效"
        qs = qs.filter(occurred_at__date__lte=to_date)

    status_raw = str(params.get("task_status", "") or "").strip()
    if status_raw:
        statuses = [x.strip() for x in status_raw.split(",") if x.strip()]
        if statuses:
            qs = qs.filter(task__status__in=statuses)

    return qs, ""


def _validate_task_options(body: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    mode = str(body.get("mode", "standard")).strip() or "standard"
    if mode not in {"standard", "deep"}:
        return {}, "mode must be standard or deep"

    enable_image = body.get("enable_image", False)
    if not isinstance(enable_image, bool):
        return {}, "enable_image must be boolean"

    risk_confirmation = (
        str(body.get("risk_confirmation_strategy", "on_high_risk")).strip()
        or "on_high_risk"
    )
    if risk_confirmation not in {"on_high_risk", "always", "never"}:
        return {}, "risk_confirmation_strategy must be on_high_risk, always, or never"

    max_reflect_rounds_raw = body.get("max_reflect_rounds", 2)
    try:
        max_reflect_rounds = int(max_reflect_rounds_raw)
    except (TypeError, ValueError):
        return {}, "max_reflect_rounds must be an integer"
    if max_reflect_rounds < 1 or max_reflect_rounds > 5:
        return {}, "max_reflect_rounds must be between 1 and 5"

    return (
        {
            "mode": mode,
            "enable_image": enable_image,
            "risk_confirmation_strategy": risk_confirmation,
            "max_reflect_rounds": max_reflect_rounds,
        },
        None,
    )


def _start_task_for_content(
    session: ResearchSession, content: str, options: dict[str, Any]
) -> AgentTask:
    if session.title in ("", "新会话"):
        session.title = content[:200] if len(content) > 200 else content
        session.save(update_fields=["title", "updated_at"])

    ResearchMessage.objects.create(session=session, role="user", content=content)
    ResearchMessage.objects.create(
        session=session,
        role="assistant",
        content=(
            "已收到研究请求，任务已启动。"
        ),
    )
    ResearchSession.objects.filter(pk=session.pk).update(updated_at=dj_tz.now())

    task = AgentTask.objects.create(
        session=session,
        status="pending",
        steps=[],
        result_payload={"runtime_config": options},
    )
    start_first_segment_thread(task.id)
    return task


def _normalize_query_field(body: dict[str, Any]) -> str:
    content = str(body.get("content") or "").strip()
    if content:
        return content
    return str(body.get("query") or "").strip()


@require_http_methods(["GET", "POST"])
@authenticate_research_user
def sessions_collection(request, identity: ResearchIdentity):
    if request.method == "GET":
        try:
            page = max(1, int(request.GET.get("page", 1)))
            page_size = min(100, max(1, int(request.GET.get("page_size", 20))))
        except ValueError:
            return _json_err("Invalid pagination", 400)

        qs = ResearchSession.objects.filter(owner_id=identity.user_id).order_by("-updated_at")
        total = qs.count()
        start = (page - 1) * page_size
        items = []
        for s in qs[start : start + page_size]:
            latest_task = s.tasks.order_by("-created_at").first()
            items.append(
                {
                    "session_id": str(s.id),
                    "title": s.title,
                    "status": s.status,
                    "updated_at": _format_dt(s.updated_at),
                    "latest_task_id": str(latest_task.id) if latest_task else None,
                }
            )
        return _json_ok(
            {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        )

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    title = (body.get("title") or "新会话").strip() or "新会话"
    session = ResearchSession.objects.create(owner_id=identity.user_id, title=title)
    return _json_ok(
        {
            "session_id": str(session.id),
            "title": session.title,
            "created_at": _format_dt(session.created_at),
        },
        status=201,
    )


@require_http_methods(["POST"])
@authenticate_research_user
def create_task(request, identity: ResearchIdentity):
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    content = _normalize_query_field(body)
    if not content:
        return _json_err("content or query is required", 400)
    options, err = _validate_task_options(body)
    if err:
        return _json_err(err, 400)

    session = None
    session_id_raw = body.get("session_id")
    if session_id_raw:
        try:
            sid = uuid.UUID(str(session_id_raw))
        except ValueError:
            return _json_err("Invalid session_id", 400)
        session = ResearchSession.objects.filter(id=sid, owner_id=identity.user_id).first()
        if session is None:
            return _json_err("session not found", 404)
        if _active_task(session):
            return _json_err("A task is already in progress for this session", 409)
    if session is None:
        title = (body.get("title") or "新会话").strip() or "新会话"
        session = ResearchSession.objects.create(owner_id=identity.user_id, title=title)

    task = _start_task_for_content(session, content, options)
    return _json_ok(
        {"task_id": str(task.id), "status": task.status, "session_id": str(session.id)},
        status=202,
    )


@require_http_methods(["POST"])
@authenticate_research_user
def create_session_with_first_message(request, identity: ResearchIdentity):
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    content = (body.get("content") or "").strip()
    if not content:
        return _json_err("content is required", 400)
    options, err = _validate_task_options(body)
    if err:
        return _json_err(err, 400)
    title = (body.get("title") or "新会话").strip() or "新会话"

    session = ResearchSession.objects.create(owner_id=identity.user_id, title=title)
    task = _start_task_for_content(session, content, options)

    return _json_ok(
        {
            "task_id": str(task.id),
            "status": task.status,
            "session_id": str(session.id),
        },
        status=202,
    )


@require_http_methods(["GET", "DELETE", "PATCH"])
@authenticate_research_user
def get_session(request, identity: ResearchIdentity, session_id):
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        return _json_err("Not found", 404)
    session = ResearchSession.objects.filter(id=sid, owner_id=identity.user_id).first()
    if not session:
        return _json_err("Not found", 404)
    if request.method == "DELETE":
        session.delete()
        return _json_ok({"session_id": str(sid), "deleted": True})
    if request.method == "PATCH":
        try:
            body = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return _json_err("Invalid JSON", 400)
        title = (body.get("title") or "").strip()
        if not title:
            return _json_err("title is required", 400)
        session.title = title[:200]
        session.save(update_fields=["title", "updated_at"])
        return _json_ok(
            {
                "session_id": str(session.id),
                "title": session.title,
                "updated_at": _format_dt(session.updated_at),
            }
        )

    messages = [
        {
            "role": m.role,
            "content": m.content,
            "created_at": _format_dt(m.created_at),
        }
        for m in session.messages.all()
    ]
    active = _active_task(session)
    latest = session.tasks.order_by("-created_at").first()
    payload = {
        "session_id": str(session.id),
        "title": session.title,
        "updated_at": _format_dt(session.updated_at),
        "messages": messages,
        "active_task": _task_to_json(active) if active else None,
        "latest_task": _task_to_json(latest) if latest else None,
    }
    return _json_ok(payload)


@require_http_methods(["POST"])
@authenticate_research_user
def post_session_message(request, identity: ResearchIdentity, session_id):
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        return _json_err("Not found", 404)
    session = ResearchSession.objects.filter(id=sid, owner_id=identity.user_id).first()
    if not session:
        return _json_err("Not found", 404)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    content = (body.get("content") or "").strip()
    if not content:
        return _json_err("content is required", 400)
    options, err = _validate_task_options(body)
    if err:
        return _json_err(err, 400)

    if _active_task(session):
        return _json_err("A task is already in progress for this session", 409)
    task = _start_task_for_content(session, content, options)

    return _json_ok(
        {
            "task_id": str(task.id),
            "status": task.status,
            "session_id": str(session.id),
        },
        status=202,
    )


@require_http_methods(["GET"])
@authenticate_research_user
def get_task(request, identity: ResearchIdentity, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = (
        AgentTask.objects.filter(id=tid, session__owner_id=identity.user_id)
        .select_related("session")
        .first()
    )
    if not task:
        return _json_err("Not found", 404)
    return _json_ok(_task_to_json(task))


@require_http_methods(["POST"])
@authenticate_research_user
def post_task_follow_up(request, identity: ResearchIdentity, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    parent_task = (
        AgentTask.objects.filter(id=tid, session__owner_id=identity.user_id)
        .select_related("session")
        .first()
    )
    if not parent_task:
        return _json_err("Not found", 404)
    if parent_task.status != "completed":
        return _json_err("Task is not completed yet", 409)
    if _active_task(parent_task.session):
        return _json_err("A task is already in progress for this session", 409)
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    content = (body.get("content") or "").strip()
    if not content:
        return _json_err("content is required", 400)
    options, err = _validate_task_options(body)
    if err:
        return _json_err(err, 400)
    options["follow_up_from_task_id"] = str(parent_task.id)
    task = _start_task_for_content(parent_task.session, content, options)
    return _json_ok(
        {
            "task_id": str(task.id),
            "status": task.status,
            "session_id": str(parent_task.session_id),
        },
        status=202,
    )


@require_http_methods(["GET"])
@authenticate_research_user
def download_task_report(request, identity: ResearchIdentity, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = AgentTask.objects.filter(id=tid, session__owner_id=identity.user_id).first()
    if not task:
        return _json_err("Not found", 404)
    if task.status != "completed":
        return _json_err("Task is not completed yet", 409)
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    body = str(payload.get("body", "")).strip()
    if not body:
        return _json_err("No report body available", 409)
    response = HttpResponse(body, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="research-report-{task.id}.md"'
    return response


@require_http_methods(["POST"])
@authenticate_research_user
def post_intervention(request, identity: ResearchIdentity, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = AgentTask.objects.filter(id=tid, session__owner_id=identity.user_id).first()
    if not task:
        return _json_err("Not found", 404)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    decision = body.get("decision")
    message = (body.get("message") or "").strip()

    if decision not in ("approve", "reject", "revise"):
        return _json_err("decision must be approve, reject, or revise", 400)

    if task.status != "pending_action" or not task.intervention:
        return _json_err("Task is not waiting for intervention", 409)

    if decision == "revise" and not message:
        return _json_err("message is required when decision is revise", 400)

    if decision == "reject":
        task.status = "cancelled"
        task.intervention = None
        task.save(update_fields=["status", "intervention", "updated_at"])
        return _json_ok(
            {
                "task_id": str(task.id),
                "status": "cancelled",
                "intervention": None,
            }
        )

    if decision == "approve":
        _mark_local_command_approved(task)
        task.intervention = None
        task.status = "running"
        task.save(update_fields=["status", "intervention", "result_payload", "updated_at"])
        start_after_approve_thread(task.id)
        return _json_ok(
            {
                "task_id": str(task.id),
                "status": "running",
                "intervention": None,
            }
        )

    # revise
    _mark_local_command_approved(task)
    task.intervention = None
    task.status = "running"
    task.save(update_fields=["status", "intervention", "result_payload", "updated_at"])
    start_after_revise_thread(task.id, message)
    return _json_ok(
        {
            "task_id": str(task.id),
            "status": "running",
            "intervention": None,
        }
    )


@require_http_methods(["POST"])
@authenticate_research_user
def post_cancel_task(request, identity: ResearchIdentity, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = AgentTask.objects.filter(id=tid, session__owner_id=identity.user_id).first()
    if not task:
        return _json_err("Not found", 404)
    if task.status not in ACTIVE_STATUSES:
        return _json_err("Task cannot be cancelled", 409)
    task.status = "cancelled"
    task.intervention = None
    task.save(update_fields=["status", "intervention", "updated_at"])
    return _json_ok({"task_id": str(task.id), "status": "cancelled"})


@require_http_methods(["POST"])
@authenticate_research_user
def post_task_behavior_log(request, user, task_id):
    """
    用户态行为日志上报接口（供科研助手执行引擎日志探针调用）。
    """
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)

    task = AgentTask.objects.filter(id=tid, session__user=user).first()
    if not task:
        return _json_err("Not found", 404)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)

    operation_type = str(body.get("operation_type") or "").strip()
    if not operation_type:
        return _json_err("operation_type is required", 400)

    target_url = str(body.get("target_url") or "").strip()
    target_domain = str(body.get("target_domain") or "").strip().lower() or _to_domain(target_url)
    response_status = _parse_int_or_none(body.get("response_status"))

    occurred_at = dj_tz.now()
    occurred_raw = body.get("occurred_at")
    if occurred_raw:
        parsed = parse_datetime(str(occurred_raw))
        if parsed is None:
            return _json_err("occurred_at format invalid", 400)
        occurred_at = parsed

    is_exception = bool(body.get("is_exception", False))
    if response_status is not None and response_status >= 400:
        is_exception = True

    log = AgentBehaviorAuditLog.objects.create(
        task=task,
        operation_type=operation_type,
        target_url=target_url,
        target_domain=target_domain,
        request_headers=_ensure_json_obj(body.get("request_headers")),
        request_payload=_ensure_json_obj(body.get("request_payload")),
        action_payload=_ensure_json_obj(body.get("action_payload")),
        response_status=response_status,
        is_exception=is_exception,
        exception_message=str(body.get("exception_message") or ""),
        trace_detail=str(body.get("trace_detail") or ""),
        occurred_at=occurred_at,
    )
    return JsonResponse(
        {"log_id": log.id, "task_id": str(task.id), "message": "行为日志记录成功"},
        status=201,
    )


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_behavior_logs(request, _admin):
    qs = AgentBehaviorAuditLog.objects.select_related("task", "task__session", "task__session__user")
    qs, err = _apply_behavior_filters(qs, request.GET, default_scope=True)
    if err:
        return fail({"error": err})

    qs = qs.order_by("-occurred_at", "-id")
    page_num = _parse_int_or_none(request.GET.get("page_num")) or 1
    page_size = _parse_int_or_none(request.GET.get("page_size")) or 20
    page_size = min(100, max(1, page_size))

    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        page = paginator.page(1)

    return ok(
        {
            "total": paginator.count,
            "page_num": page.number,
            "page_size": page_size,
            "items": [item.to_dict() for item in page.object_list],
        }
    )


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_task_behavior_chain(request, _admin, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return fail({"error": "任务不存在"})

    task = (
        AgentTask.objects.select_related("session", "session__user")
        .filter(id=tid)
        .first()
    )
    if task is None:
        return fail({"error": "任务不存在"})

    logs = (
        task.behavior_audit_logs.select_related("task", "task__session", "task__session__user")
        .order_by("occurred_at", "id")
    )
    return ok(
        {
            "task": {
                "task_id": str(task.id),
                "session_id": str(task.session_id),
                "user_id": str(task.session.user_id),
                "status": task.status,
                "step_seq": task.step_seq,
                "created_at": _format_dt(task.created_at),
                "updated_at": _format_dt(task.updated_at),
            },
            "logs": [item.to_dict() for item in logs],
        }
    )


@require_http_methods(["POST"])
@authenticate_research_admin
def admin_export_behavior_logs(request, _admin):
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return fail({"error": "请求体不是有效 JSON"})

    qs = AgentBehaviorAuditLog.objects.select_related("task", "task__session", "task__session__user")
    qs, err = _apply_behavior_filters(qs, body, default_scope=True)
    if err:
        return fail({"error": err})
    logs = list(qs.order_by("-occurred_at", "-id")[:500])

    generated_at = dj_tz.now().strftime("%Y-%m-%d %H:%M:%S")
    file_ts = dj_tz.now().strftime("%Y%m%d_%H%M%S")
    filters_text = {
        "user_id": str(body.get("user_id", "") or ""),
        "task_id": str(body.get("task_id", "") or ""),
        "target_domain": str(body.get("target_domain", "") or ""),
        "operation_type": str(body.get("operation_type", "") or ""),
        "exception_status": str(body.get("exception_status", "") or "all"),
        "date_from": str(body.get("date_from", "") or ""),
        "date_to": str(body.get("date_to", "") or ""),
    }

    lines = [
        "# 科研助手行为审计报告",
        "",
        f"- 生成时间：{generated_at}",
        f"- 记录条数：{len(logs)}（最多导出 500 条）",
        "- 筛选条件：",
        f"  - user_id: {filters_text['user_id'] or '全部'}",
        f"  - task_id: {filters_text['task_id'] or '全部'}",
        f"  - target_domain: {filters_text['target_domain'] or '全部'}",
        f"  - operation_type: {filters_text['operation_type'] or '全部'}",
        f"  - exception_status: {filters_text['exception_status'] or 'all'}",
        f"  - date_from: {filters_text['date_from'] or '不限'}",
        f"  - date_to: {filters_text['date_to'] or '不限'}",
        "",
        "| 时间 | 用户ID | 任务ID | 目标域名 | 操作类型 | HTTP状态 | 异常 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for item in logs:
        occurred = item.occurred_at.isoformat() if item.occurred_at else ""
        exception_text = "是" if item.is_exception else "否"
        summary = (item.exception_message or item.trace_detail or "").replace("\n", " ").strip()
        if len(summary) > 80:
            summary = f"{summary[:80]}..."
        lines.append(
            f"| {occurred} | {item.task.session.user_id} | {item.task_id} | "
            f"{item.target_domain or '-'} | {item.operation_type} | {item.response_status or '-'} | "
            f"{exception_text} | {summary or '-'} |"
        )

    return ok(
        {
            "file_name": f"research-assistant-audit-{file_ts}.md",
            "content": "\n".join(lines),
            "count": len(logs),
        }
    )

@require_http_methods(["POST"])
@authenticate_research_user
def post_batch_delete_sessions(request, identity: ResearchIdentity):
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    ids = body.get("session_ids")
    if not isinstance(ids, list) or not ids:
        return _json_err("session_ids must be a non-empty list", 400)

    uuids = []
    for sid in ids:
        try:
            uuids.append(uuid.UUID(str(sid)))
        except ValueError:
            return _json_err("Invalid session id in session_ids", 400)

    qs = ResearchSession.objects.filter(owner_id=identity.user_id, id__in=uuids)
    session_count = qs.count()
    qs.delete()
    return _json_ok({"deleted_count": session_count})


@require_http_methods(["GET"])
@authenticate_research_user
def get_task_status(request, identity: ResearchIdentity, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = (
        AgentTask.objects.filter(id=tid, session__owner_id=identity.user_id)
        .select_related("session")
        .first()
    )
    if not task:
        return _json_err("Not found", 404)
    return _json_ok(_task_to_json(task))


@require_http_methods(["GET"])
@authenticate_research_user
def get_task_events(request, identity: ResearchIdentity, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = AgentTask.objects.filter(id=tid, session__owner_id=identity.user_id).first()
    if not task:
        return _json_err("Not found", 404)
    try:
        since_seq = max(0, int(request.GET.get("since_seq", "0")))
    except ValueError:
        return _json_err("since_seq must be integer", 400)

    steps = [step for step in (task.steps or []) if int(step.get("seq", 0)) > since_seq]
    events = []
    for step in steps:
        events.append(
            {
                "seq": int(step.get("seq", 0)),
                "phase": str(step.get("phase", "")),
                "type": "step",
                "summary": str(step.get("title", "")),
                "detail": str(step.get("detail", "")),
                "created_at": str(step.get("ts", "")),
            }
        )
    next_seq = int(task.step_seq or 0)
    return _json_ok(
        {"task_id": str(task.id), "events": events, "next_seq": next_seq, "has_more": False}
    )


@require_http_methods(["GET"])
@authenticate_research_user
def get_task_report(request, identity: ResearchIdentity, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = AgentTask.objects.filter(id=tid, session__owner_id=identity.user_id).first()
    if not task:
        return _json_err("Not found", 404)
    if task.status != "completed":
        return _json_err("Task is not completed yet", 409)
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    report_md = str(payload.get("body", "")).strip()
    report = {
        "markdown": report_md,
        "format": payload.get("format", "markdown"),
        "citations": payload.get("citations", []),
        "attachments": payload.get("attachments", []),
    }
    return _json_ok({"task_id": str(task.id), "status": task.status, "report": report})


@require_http_methods(["POST"])
@authenticate_research_user
def post_task_actions(request, identity: ResearchIdentity, task_id):
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    action = str(body.get("action", "")).strip()
    if action not in {"allow", "revise", "abort"}:
        return _json_err("action must be allow, revise, or abort", 400)

    if action == "abort":
        return post_cancel_task(request, identity, task_id)

    mapped = "approve" if action == "allow" else "revise"
    req_body = {"decision": mapped}
    if action == "revise":
        req_body["message"] = body.get("message", "")
    request._body = json.dumps(req_body).encode("utf-8")
    return post_intervention(request, identity, task_id)


@require_http_methods(["POST"])
@authenticate_research_user
def export_tasks(request, identity: ResearchIdentity):
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)

    task_ids_raw = body.get("task_ids")
    if not isinstance(task_ids_raw, list) or not task_ids_raw:
        return _json_err("task_ids must be a non-empty list", 400)

    task_ids: list[uuid.UUID] = []
    for item in task_ids_raw:
        try:
            task_ids.append(uuid.UUID(str(item)))
        except ValueError:
            return _json_err("invalid task id in task_ids", 400)
    tasks = AgentTask.objects.filter(
        id__in=task_ids,
        session__owner_id=identity.user_id,
        status="completed",
    ).select_related("session")
    exported = []
    for task in tasks:
        payload = task.result_payload if isinstance(task.result_payload, dict) else {}
        exported.append(
            {
                "task_id": str(task.id),
                "session_id": str(task.session_id),
                "title": task.session.title,
                "report": str(payload.get("body", "")),
                "citations": payload.get("citations", []),
            }
        )
    return _json_ok({"items": exported, "total": len(exported)})
