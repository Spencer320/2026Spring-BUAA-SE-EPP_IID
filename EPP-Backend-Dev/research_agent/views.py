import json
import uuid
from typing import Any

from django.http import HttpResponse, JsonResponse
from django.utils import timezone as dj_tz
from django.views.decorators.http import require_http_methods

from .auth import ResearchIdentity, authenticate_research_user
from .models import AgentTask, ResearchMessage, ResearchSession
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
