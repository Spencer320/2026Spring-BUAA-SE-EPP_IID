import json
import uuid
from typing import Any

from django.http import JsonResponse
from django.utils import timezone as dj_tz
from django.views.decorators.http import require_http_methods

from .auth import authenticate_research_user
from .models import AgentTask, ResearchMessage, ResearchSession
from .orchestrator import (
    ACTIVE_STATUSES,
    start_after_approve_thread,
    start_after_revise_thread,
    start_first_segment_thread,
)


def _json_err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "err": msg}, status=status)


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
    return {
        "task_id": str(task.id),
        "session_id": str(task.session_id),
        "status": task.status,
        "step_seq": task.step_seq,
        "updated_at": _format_dt(task.updated_at),
        "steps": task.steps or [],
        "intervention": task.intervention,
        "result": task.result_payload,
        "error": err,
    }


def _active_task(session: ResearchSession) -> AgentTask | None:
    return (
        session.tasks.filter(status__in=["pending", "running", "waiting_user"])
        .order_by("-created_at")
        .first()
    )


@require_http_methods(["GET", "POST"])
@authenticate_research_user
def sessions_collection(request, user):
    if request.method == "GET":
        try:
            page = max(1, int(request.GET.get("page", 1)))
            page_size = min(100, max(1, int(request.GET.get("page_size", 20))))
        except ValueError:
            return _json_err("Invalid pagination", 400)

        qs = ResearchSession.objects.filter(user=user).order_by("-updated_at")
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
        return JsonResponse(
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
    session = ResearchSession.objects.create(user=user, title=title)
    return JsonResponse(
        {
            "session_id": str(session.id),
            "title": session.title,
            "created_at": _format_dt(session.created_at),
        },
        status=201,
    )


@require_http_methods(["GET"])
@authenticate_research_user
def get_session(request, user, session_id):
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        return _json_err("Not found", 404)
    session = ResearchSession.objects.filter(id=sid, user=user).first()
    if not session:
        return _json_err("Not found", 404)

    messages = [
        {
            "role": m.role,
            "content": m.content,
            "created_at": _format_dt(m.created_at),
        }
        for m in session.messages.all()
    ]
    active = _active_task(session)
    payload = {
        "session_id": str(session.id),
        "title": session.title,
        "updated_at": _format_dt(session.updated_at),
        "messages": messages,
        "active_task": _task_to_json(active) if active else None,
    }
    return JsonResponse(payload)


@require_http_methods(["POST"])
@authenticate_research_user
def post_session_message(request, user, session_id):
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        return _json_err("Not found", 404)
    session = ResearchSession.objects.filter(id=sid, user=user).first()
    if not session:
        return _json_err("Not found", 404)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    content = (body.get("content") or "").strip()
    if not content:
        return _json_err("content is required", 400)

    if _active_task(session):
        return _json_err("A task is already in progress for this session", 409)

    if session.title in ("", "新会话"):
        session.title = content[:200] if len(content) > 200 else content
        session.save(update_fields=["title", "updated_at"])

    ResearchMessage.objects.create(session=session, role="user", content=content)
    ResearchMessage.objects.create(
        session=session,
        role="assistant",
        content="已收到您的指令，任务已启动（Mock）。",
    )
    ResearchSession.objects.filter(pk=session.pk).update(updated_at=dj_tz.now())

    task = AgentTask.objects.create(session=session, status="pending", steps=[])
    start_first_segment_thread(task.id)

    return JsonResponse(
        {
            "task_id": str(task.id),
            "status": task.status,
            "session_id": str(session.id),
        },
        status=202,
    )


@require_http_methods(["GET"])
@authenticate_research_user
def get_task(request, user, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = AgentTask.objects.filter(id=tid, session__user=user).select_related("session").first()
    if not task:
        return _json_err("Not found", 404)
    return JsonResponse(_task_to_json(task))


@require_http_methods(["POST"])
@authenticate_research_user
def post_intervention(request, user, task_id):
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
    decision = body.get("decision")
    message = (body.get("message") or "").strip()

    if decision not in ("approve", "reject", "revise"):
        return _json_err("decision must be approve, reject, or revise", 400)

    if task.status != "waiting_user" or not task.intervention:
        return _json_err("Task is not waiting for intervention", 409)

    if decision == "revise" and not message:
        return _json_err("message is required when decision is revise", 400)

    if decision == "reject":
        task.status = "cancelled"
        task.intervention = None
        task.save(update_fields=["status", "intervention", "updated_at"])
        return JsonResponse(
            {
                "task_id": str(task.id),
                "status": "cancelled",
                "intervention": None,
            }
        )

    if decision == "approve":
        task.intervention = None
        task.status = "running"
        task.save(update_fields=["status", "intervention", "updated_at"])
        start_after_approve_thread(task.id)
        return JsonResponse(
            {
                "task_id": str(task.id),
                "status": "running",
                "intervention": None,
            }
        )

    # revise
    task.intervention = None
    task.status = "running"
    task.save(update_fields=["status", "intervention", "updated_at"])
    start_after_revise_thread(task.id, message)
    return JsonResponse(
        {
            "task_id": str(task.id),
            "status": "running",
            "intervention": None,
        }
    )


@require_http_methods(["POST"])
@authenticate_research_user
def post_cancel_task(request, user, task_id):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)
    task = AgentTask.objects.filter(id=tid, session__user=user).first()
    if not task:
        return _json_err("Not found", 404)
    if task.status not in ACTIVE_STATUSES:
        return _json_err("Task cannot be cancelled", 409)
    task.status = "cancelled"
    task.intervention = None
    task.save(update_fields=["status", "intervention", "updated_at"])
    return JsonResponse({"task_id": str(task.id), "status": "cancelled"})
