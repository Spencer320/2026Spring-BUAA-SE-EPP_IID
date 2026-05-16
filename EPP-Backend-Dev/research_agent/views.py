import json
import uuid
from typing import Any

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import CharField, Count, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, Lower
from django.http import HttpResponse, JsonResponse
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone as dj_tz
from django.views.decorators.http import require_http_methods
from business.models import User
from business.models.access_frequency import FEATURE_CHOICES, WINDOW_CHOICES
from business.utils.rate_limit import (
    FEATURE_DEEP_RESEARCH,
    FEATURE_RESEARCH_ASSISTANT,
    check_quota_before_start,
    get_user_feature_usage,
)
from business.utils.response import fail, ok
from .auth import authenticate_research_admin, authenticate_research_user, ResearchIdentity
from .models import (
    AgentBehaviorAuditLog,
    AgentTask,
    BasicOrchestratorRun,
    ResearchMessage,
    ResearchPaperShelfItem,
    ResearchSession,
    WorkspaceAgentRun,
)
from .orchestrator import (
    ACTIVE_STATUSES,
    start_after_approve_thread,
    start_after_revise_thread,
    start_deep_research_thread,
    start_first_segment_thread,
)
from .paper_shelf import add_workspace_item, shelf_item_to_api_dict
from .run_registry import AnyRun, resolve_owned_run, resolve_run_by_id, run_kind

# 管理端行为审计范围：科研助手（basic + 工作区子运行）与深度研究（AgentTask）分开展示
AUDIT_SCOPE_ASSISTANT = "assistant"
AUDIT_SCOPE_DEEP_RESEARCH = "deep_research"
_AUDIT_SCOPES = frozenset({AUDIT_SCOPE_ASSISTANT, AUDIT_SCOPE_DEEP_RESEARCH})


def _json_ok(data: dict[str, Any], status: int = 200) -> JsonResponse:
    return JsonResponse({"ok": True, "data": data}, status=status)


def _json_err(msg: str, status: int = 400, code: str = "BAD_REQUEST") -> JsonResponse:
    return JsonResponse(
        {"ok": False, "error": {"code": code, "message": msg}},
        status=status,
    )


def _client_ip(request) -> str | None:
    return request.META.get("REMOTE_ADDR") or request.META.get("HTTP_X_FORWARDED_FOR")


_WINDOW_LABELS = dict(WINDOW_CHOICES)
_FEATURE_LABELS = dict(FEATURE_CHOICES)


def _quota_item_for_user(user, feature: str) -> dict[str, Any]:
    usage = get_user_feature_usage(user, feature)
    limit = int(usage.get("limit", -1))
    unlimited = limit == -1
    banned = limit == 0
    window = str(usage.get("window") or "daily")
    return {
        **usage,
        "feature_label": _FEATURE_LABELS.get(feature, feature),
        "window_label": _WINDOW_LABELS.get(window, window),
        "unlimited": unlimited,
        "banned": banned,
    }


@require_http_methods(["GET"])
@authenticate_research_user
def user_my_quota(request, identity: ResearchIdentity):
    """GET /api/research-agent/quota/ — 当前登录用户的访问配额与剩余额度。"""
    user = User.objects.filter(user_id=identity.user_id).first()
    if user is None:
        return _json_err("用户不存在或未同步到业务库", 403, code="USER_NOT_FOUND")

    features = [
        _quota_item_for_user(user, FEATURE_RESEARCH_ASSISTANT),
        _quota_item_for_user(user, FEATURE_DEEP_RESEARCH),
    ]
    return _json_ok({"features": features})


def _quota_precheck(request, identity: ResearchIdentity, feature: str) -> JsonResponse | None:
    """配额检查；通过返回 None，否则返回应直接响应给客户端的 JsonResponse。"""
    user = User.objects.filter(user_id=identity.user_id).first()
    if user is None:
        return _json_err("用户不存在或未同步到业务库", 403, code="USER_NOT_FOUND")
    allowed, msg = check_quota_before_start(
        user,
        feature,
        ip_address=_client_ip(request),
    )
    if not allowed:
        return _json_err(msg, 429, code="QUOTA_EXCEEDED")
    return None


def _format_dt(dt) -> str:
    if dt is None:
        return ""
    from django.utils import timezone as dj_tz

    if dj_tz.is_naive(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.astimezone(dj_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _task_progress_percent(run: AnyRun) -> int:
    if run.status == "completed":
        return 100
    if run.status in ("failed", "cancelled"):
        base = int(run.step_seq or 0)
        return max(1, min(99, base * 10 if base else 1))
    orch = run_kind(run)
    if orch == "deep_research":
        total = 6
        seq = int(run.step_seq or 0)
        return int(min(99, (seq / total) * 100))
    if orch == "basic":
        payload = run.result_payload if isinstance(run.result_payload, dict) else {}
        cfg = payload.get("runtime_config")
        if not isinstance(cfg, dict):
            cfg = {}
        plan = cfg.get("smart_plan")
        if isinstance(plan, dict):
            steps = plan.get("steps")
            if isinstance(steps, list) and len(steps) > 0:
                try:
                    nxt = int(cfg.get("smart_plan_next_index", 0))
                except (TypeError, ValueError):
                    nxt = 0
                denom = len(steps)
                done = max(0, min(nxt, denom))
                return int(min(99, (done / denom) * 100))
        seq = int(run.step_seq or 0)
        return int(min(99, max(5, seq * 8)))
    seq = int(run.step_seq or 0)
    return int(min(99, max(5, seq * 12)))


def _task_to_json(task: AnyRun) -> dict[str, Any]:
    err = None
    if task.error_code or task.error_message:
        err = {
            "code": task.error_code or "UNKNOWN",
            "message": task.error_message or "",
        }
    progress = _task_progress_percent(task)
    if task.status == "completed":
        progress = 100
    elif task.status in ("failed", "cancelled"):
        progress = max(progress, 1)
    current_phase = ""
    if task.steps:
        current_phase = str(task.steps[-1].get("phase", "") or "")
    out: dict[str, Any] = {
        "task_id": str(task.id),
        "orchestrator": run_kind(task),
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
    rp = task.result_payload if isinstance(task.result_payload, dict) else {}
    rc = rp.get("runtime_config")
    if isinstance(rc, dict) and "workspace_fs_generation" in rc:
        try:
            out["workspace_fs_generation"] = int(rc["workspace_fs_generation"])
        except (TypeError, ValueError):
            out["workspace_fs_generation"] = 0
    return out


def _mark_local_command_approved(task: AnyRun) -> None:
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


def _mark_local_file_action_approved(task: AnyRun) -> None:
    intervention = task.intervention if isinstance(task.intervention, dict) else {}
    if intervention.get("tool") != "local_file":
        return
    action = str(intervention.get("action", "")).strip()
    if not action:
        return
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        cfg = {}
    approved = cfg.get("approved_local_file_actions", [])
    if not isinstance(approved, list):
        approved = []
    if action not in approved:
        approved.append(action)
    cfg["approved_local_file_actions"] = approved
    payload["runtime_config"] = cfg
    task.result_payload = payload


def _active_task(session: ResearchSession) -> AnyRun | None:
    candidates: list[AnyRun] = []
    b = (
        session.basic_runs.filter(status__in=["pending", "running", "pending_action"])
        .order_by("-created_at")
        .first()
    )
    if b:
        candidates.append(b)
    d = (
        session.deep_research_tasks.filter(status__in=["pending", "running", "pending_action"])
        .order_by("-created_at")
        .first()
    )
    if d:
        candidates.append(d)
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.created_at)


def _latest_root_run(session: ResearchSession) -> AgentTask | BasicOrchestratorRun | None:
    b = session.basic_runs.order_by("-created_at").first()
    d = session.deep_research_tasks.order_by("-created_at").first()
    if b and d:
        return b if b.created_at >= d.created_at else d
    return b or d


def _behavior_audit_fk_kwargs(run: AnyRun) -> dict[str, Any]:
    if isinstance(run, AgentTask):
        return {"session": run.session, "deep_task": run, "basic_run": None, "workspace_run": None}
    if isinstance(run, BasicOrchestratorRun):
        return {"session": run.session, "deep_task": None, "basic_run": run, "workspace_run": None}
    if isinstance(run, WorkspaceAgentRun):
        return {"session": run.session, "deep_task": None, "basic_run": None, "workspace_run": run}
    raise TypeError(type(run))


def _behavior_logs_for_run(run: AnyRun):
    if isinstance(run, AgentTask):
        qs = AgentBehaviorAuditLog.objects.filter(deep_task=run)
    elif isinstance(run, BasicOrchestratorRun):
        qs = AgentBehaviorAuditLog.objects.filter(basic_run=run)
    elif isinstance(run, WorkspaceAgentRun):
        qs = AgentBehaviorAuditLog.objects.filter(workspace_run=run)
    else:
        return AgentBehaviorAuditLog.objects.none()
    return qs.select_related(
        "session", "deep_task", "basic_run", "workspace_run"
    ).order_by("occurred_at", "id")


def _behavior_logs_base_qs():
    return AgentBehaviorAuditLog.objects.select_related(
        "session", "deep_task", "basic_run", "workspace_run"
    )


def _apply_audit_scope_filter(qs, audit_scope: str):
    if audit_scope == AUDIT_SCOPE_ASSISTANT:
        return qs.filter(Q(basic_run__isnull=False) | Q(workspace_run__isnull=False))
    if audit_scope == AUDIT_SCOPE_DEEP_RESEARCH:
        return qs.filter(deep_task__isnull=False)
    raise ValueError(f"unknown audit_scope: {audit_scope}")


def _behavior_logs_for_assistant_run(run: AnyRun):
    """科研助手链路：basic 运行聚合其下 workspace 子运行的审计。"""
    if isinstance(run, BasicOrchestratorRun):
        return (
            _behavior_logs_base_qs()
            .filter(Q(basic_run=run) | Q(workspace_run__parent_basic_run=run))
            .order_by("occurred_at", "id")
        )
    return _behavior_logs_for_run(run)


_LEGACY_BASIC_AUDIT_OPS = frozenset(
    {
        "basic_plan",
        "basic_read",
        "basic_search",
        "basic_write",
        "basic_workspace_agent",
    }
)


def _should_hide_audit_log(log: AgentBehaviorAuditLog) -> bool:
    """过滤照搬用户可见步骤或无效 JSON 占位的历史审计。"""
    detail = str(log.trace_detail or "").strip()
    op = str(log.operation_type or "").strip()
    if op in _LEGACY_BASIC_AUDIT_OPS and str(log.tool_type or "") == "basic_orchestrator":
        return True
    if op == "workspace_agent" and detail.startswith("{") and "tool_calls_n" in detail:
        return True
    if op in ("workspace_agent_plan", "workspace_agent_tools"):
        return True
    return False


def _resolve_run_for_audit_scope(task_id: uuid.UUID, audit_scope: str) -> AnyRun | None:
    run = resolve_run_by_id(task_id)
    if run is None:
        return None
    if audit_scope == AUDIT_SCOPE_DEEP_RESEARCH and not isinstance(run, AgentTask):
        return None
    if audit_scope == AUDIT_SCOPE_ASSISTANT and isinstance(run, AgentTask):
        return None
    return run


def _extract_run_quota_tokens(run: AnyRun) -> int | None:
    """科研助手 BasicOrchestratorRun 本轮 Token 消耗（与访频记账一致）。"""
    if not isinstance(run, BasicOrchestratorRun):
        return None
    rp = run.result_payload if isinstance(run.result_payload, dict) else {}
    qu = rp.get("quota_usage")
    if isinstance(qu, dict) and "tokens" in qu:
        try:
            return max(0, int(qu.get("tokens") or 0))
        except (TypeError, ValueError):
            pass
    try:
        from business.models.access_frequency import FeatureAccessLog

        row = (
            FeatureAccessLog.objects.filter(
                feature=FEATURE_RESEARCH_ASSISTANT,
                status=FeatureAccessLog.STATUS_ALLOWED,
                extra__run_id=str(run.id),
            )
            .order_by("-accessed_at")
            .first()
        )
        if row and isinstance(row.extra, dict):
            return max(0, int(row.extra.get("tokens") or 0))
    except Exception:
        pass
    return None


def _run_to_audit_task_json(run: AnyRun, *, user_name: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": str(run.id),
        "run_kind": run_kind(run),
        "task_name": str(run.session.title or ""),
        "session_id": str(run.session_id),
        "user_id": str(run.session.owner_id),
        "user_name": user_name,
        "status": run.status,
        "step_seq": run.step_seq,
        "created_at": _format_dt(run.created_at),
        "updated_at": _format_dt(run.updated_at),
    }
    if isinstance(run, WorkspaceAgentRun) and run.parent_basic_run_id:
        payload["parent_basic_run_id"] = str(run.parent_basic_run_id)
    tokens = _extract_run_quota_tokens(run)
    if tokens is not None:
        payload["token_usage"] = tokens
    return payload


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


def _normalize_audit_status(raw: str, *, is_exception: bool) -> str:
    status = (raw or "").strip().lower()
    mapping = {
        "ok": "succeeded",
        "success": "succeeded",
        "succeeded": "succeeded",
        "error": "failed",
        "failed": "failed",
        "pending_action": "pending_action",
        "pending": "pending_action",
        "allowed": "allowed",
        "rejected": "rejected",
        "blocked": "rejected",
    }
    if status in mapping:
        return mapping[status]
    return "failed" if is_exception else "succeeded"


def _sanitize_actor_type(raw: Any, default: str) -> str:
    actor = str(raw or "").strip().lower() or default
    if actor not in {"system", "user", "admin"}:
        actor = default
    return actor


def _compact_rule_hit(raw: Any) -> str:
    if isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw if str(item).strip()]
        return ",".join(values)[:255]
    if isinstance(raw, dict):
        try:
            return json.dumps(raw, ensure_ascii=False)[:255]
        except TypeError:
            return str(raw)[:255]
    return str(raw or "").strip()[:255]


def _resolve_user_name_map(user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    parsed_ids: list[uuid.UUID] = []
    for user_id in user_ids:
        try:
            parsed_ids.append(uuid.UUID(str(user_id)))
        except (TypeError, ValueError):
            continue
    if not parsed_ids:
        return {}
    from business.models.user import User

    rows = User.objects.filter(user_id__in=parsed_ids).values("user_id", "username")
    return {str(item["user_id"]): str(item["username"]) for item in rows}


def _resolve_user_ids_by_name(keyword: str) -> list[str]:
    text = (keyword or "").strip()
    if not text:
        return []
    from business.models.user import User

    rows = User.objects.filter(username__icontains=text).values_list("user_id", flat=True)
    return [str(user_id) for user_id in rows]


def _attach_behavior_display_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return items
    user_ids = {
        str(item.get("user_id", "")).strip()
        for item in items
        if str(item.get("user_id", "")).strip()
    }
    user_name_map = _resolve_user_name_map(user_ids)
    for item in items:
        user_id = str(item.get("user_id", "")).strip()
        item["user_name"] = user_name_map.get(user_id, user_id)
        task_name = str(item.get("task_name", "")).strip()
        if not task_name:
            task_id = str(item.get("task_id", "")).strip()
            item["task_name"] = f"任务-{task_id[:8]}" if task_id else ""
    return items


def _apply_behavior_filters(
    qs,
    params: dict[str, Any],
    *,
    default_scope: bool = True,
    audit_scope: str | None = None,
):
    if audit_scope:
        qs = _apply_audit_scope_filter(qs, audit_scope)

    terminal = ("completed", "failed", "cancelled")
    status_values = [*ACTIVE_STATUSES, *terminal]
    if default_scope:
        if audit_scope == AUDIT_SCOPE_DEEP_RESEARCH:
            qs = qs.filter(deep_task__status__in=status_values)
        elif audit_scope == AUDIT_SCOPE_ASSISTANT:
            qs = qs.filter(
                Q(basic_run__status__in=status_values)
                | Q(workspace_run__status__in=status_values)
            )
        else:
            qs = qs.filter(
                Q(deep_task__status__in=status_values)
                | Q(basic_run__status__in=status_values)
                | Q(workspace_run__status__in=status_values)
            )

    user_id = str(params.get("user_id", "") or "").strip()
    if user_id:
        qs = qs.filter(session__owner_id=user_id)

    user_name = str(params.get("user_name", "") or "").strip()
    if user_name:
        matched_ids = _resolve_user_ids_by_name(user_name)
        if not matched_ids:
            return qs.none(), ""
        qs = qs.filter(session__owner_id__in=matched_ids)

    task_id = str(params.get("task_id", "") or "").strip()
    if task_id:
        try:
            tid_uuid = uuid.UUID(task_id)
        except ValueError:
            return qs.none(), "task_id 格式无效"
        qs = qs.filter(
            Q(deep_task_id=tid_uuid) | Q(basic_run_id=tid_uuid) | Q(workspace_run_id=tid_uuid)
        )

    task_name = str(params.get("task_name", "") or "").strip()
    if task_name:
        qs = qs.filter(session__title__icontains=task_name)

    run_kind_filter = str(params.get("run_kind", "") or "").strip().lower()
    if run_kind_filter and audit_scope == AUDIT_SCOPE_ASSISTANT:
        if run_kind_filter == "basic":
            qs = qs.filter(basic_run__isnull=False)
        elif run_kind_filter == "workspace":
            qs = qs.filter(workspace_run__isnull=False)

    target_domain = str(params.get("target_domain", "") or "").strip()
    if target_domain:
        qs = qs.filter(target_domain__icontains=target_domain.lower())

    operation_type = str(params.get("operation_type", "") or "").strip()
    if operation_type:
        qs = qs.filter(operation_type=operation_type)

    tool_type = str(params.get("tool_type", "") or "").strip()
    if tool_type:
        qs = qs.filter(tool_type=tool_type)

    actor_type = str(params.get("actor_type", "") or "").strip().lower()
    if actor_type:
        qs = qs.filter(actor_type=actor_type)

    risk_level = str(params.get("risk_level", "") or "").strip().lower()
    if risk_level:
        qs = qs.filter(risk_level=risk_level)

    audit_status = str(params.get("audit_status", "") or "").strip().lower()
    if audit_status:
        qs = qs.filter(status=audit_status)

    trace_id = str(params.get("trace_id", "") or "").strip()
    if trace_id:
        qs = qs.filter(trace_id=trace_id)

    step_id = _parse_int_or_none(params.get("step_id"))
    if step_id is not None:
        qs = qs.filter(step_id=step_id)

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
            if audit_scope == AUDIT_SCOPE_DEEP_RESEARCH:
                qs = qs.filter(deep_task__status__in=statuses)
            elif audit_scope == AUDIT_SCOPE_ASSISTANT:
                qs = qs.filter(
                    Q(basic_run__status__in=statuses)
                    | Q(workspace_run__status__in=statuses)
                )
            else:
                qs = qs.filter(
                    Q(deep_task__status__in=statuses)
                    | Q(basic_run__status__in=statuses)
                    | Q(workspace_run__status__in=statuses)
                )

    return qs, ""


def _normalize_behavior_sort_order(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value in {"asc", "ascending", "ascend"}:
        return "asc"
    return "desc"


def _apply_behavior_ordering(qs, params: dict[str, Any]):
    sort_alias = {
        "time": "occurred_at",
        "occurred_at": "occurred_at",
        "user_name": "user_name",
        "username": "user_name",
        "task_name": "task_name",
        "step_id": "step_id",
    }
    raw_sort_by = str(params.get("sort_by", "occurred_at") or "occurred_at").strip().lower()
    sort_by = sort_alias.get(raw_sort_by, "occurred_at")
    sort_order = _normalize_behavior_sort_order(params.get("sort_order", "desc"))
    descending = sort_order == "desc"

    if sort_by == "occurred_at":
        return qs.order_by("-occurred_at", "-id") if descending else qs.order_by("occurred_at", "id")

    if sort_by == "step_id":
        sentinel_step = -1 if descending else 2147483647
        qs = qs.annotate(sort_step_id=Coalesce("step_id", Value(sentinel_step)))
        step_order_field = "-sort_step_id" if descending else "sort_step_id"
        return qs.order_by(step_order_field, "-occurred_at", "-id")

    if sort_by == "task_name":
        qs = qs.annotate(
            sort_task_name=Lower(
                Coalesce(
                    "session__title",
                    Value("", output_field=CharField()),
                )
            )
        )
        task_order_field = "-sort_task_name" if descending else "sort_task_name"
        return qs.order_by(task_order_field, "-occurred_at", "-id")

    # user_name
    from business.models.user import User

    user_name_subquery = User.objects.filter(
        user_id=OuterRef("session__owner_id")
    ).values("username")[:1]
    qs = qs.annotate(
        sort_user_name=Lower(
            Coalesce(
                Subquery(user_name_subquery, output_field=CharField()),
                F("session__owner_id"),
                Value("", output_field=CharField()),
            )
        )
    )
    user_order_field = "-sort_user_name" if descending else "sort_user_name"
    return qs.order_by(user_order_field, "-occurred_at", "-id")


def _collect_operation_type_options(qs, *, limit: int = 20) -> list[str]:
    rows = (
        qs.exclude(operation_type="")
        .values("operation_type")
        .annotate(total=Count("id"))
        .order_by("-total", "operation_type")[:limit]
    )
    return [str(item.get("operation_type", "")).strip() for item in rows if str(item.get("operation_type", "")).strip()]


def _validate_task_options(body: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    risk_confirmation = (
        str(body.get("risk_confirmation_strategy", "on_high_risk")).strip()
        or "on_high_risk"
    )
    if risk_confirmation not in {"on_high_risk", "always", "never"}:
        return {}, "risk_confirmation_strategy must be on_high_risk, always, or never"

    max_reflect_rounds_raw = body.get("max_reflect_rounds", 5)
    try:
        max_reflect_rounds = int(max_reflect_rounds_raw)
    except (TypeError, ValueError):
        return {}, "max_reflect_rounds must be an integer"
    if max_reflect_rounds < 1 or max_reflect_rounds > 5:
        return {}, "max_reflect_rounds must be between 1 and 5"

    options = {
        "risk_confirmation_strategy": risk_confirmation,
        "max_reflect_rounds": max_reflect_rounds,
    }

    local_command = body.get("local_command")
    if local_command is not None:
        if not isinstance(local_command, dict):
            return {}, "local_command must be object"
        options["local_command"] = local_command

    local_file_action = body.get("local_file_action")
    if local_file_action is not None:
        if not isinstance(local_file_action, dict):
            return {}, "local_file_action must be object"
        action = str(local_file_action.get("action", "")).strip()
        action_args = local_file_action.get("args", {})
        if not action:
            return {}, "local_file_action.action is required"
        if not isinstance(action_args, dict):
            return {}, "local_file_action.args must be object"
        options["local_file_action"] = {"action": action, "args": action_args}

    ws_preflight = str(body.get("workspace_preflight_summary") or "").strip()
    if ws_preflight:
        options["workspace_preflight_summary"] = ws_preflight[:8000]

    return options, None


_MAX_DEEP_RESEARCH_SELECTED_PAPERS = 50


def _validate_selected_papers_from_shelf(
    session: ResearchSession, papers: list[Any]
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    独立深度研究入口：``selected_papers`` 须对应当前会话「论文展示区」中的条目（检索外链或工作区文件）。

    每项为展示区条目的 UUID 字符串，或 ``{"shelf_item_id"|"item_id"|"id": "<uuid>"}``。
    返回去重后的规范化列表（顺序与请求首次出现顺序一致）。
    """
    if not papers:
        return [], None
    if len(papers) > _MAX_DEEP_RESEARCH_SELECTED_PAPERS:
        return None, f"selected_papers must contain at most {_MAX_DEEP_RESEARCH_SELECTED_PAPERS} items"

    ids_ordered: list[uuid.UUID] = []
    seen_ids: set[uuid.UUID] = set()

    for idx, raw in enumerate(papers):
        sid: uuid.UUID | None = None
        if isinstance(raw, str):
            token = raw.strip()
            if not token:
                return None, f"selected_papers[{idx}] must be a non-empty shelf item id"
            try:
                sid = uuid.UUID(token)
            except ValueError:
                return None, f"selected_papers[{idx}] must be a valid UUID"
        elif isinstance(raw, dict):
            cand = raw.get("shelf_item_id") or raw.get("item_id") or raw.get("id")
            if cand is None or str(cand).strip() == "":
                return None, (
                    f"selected_papers[{idx}] must be a string id or an object with "
                    "shelf_item_id, item_id, or id"
                )
            try:
                sid = uuid.UUID(str(cand).strip())
            except ValueError:
                return None, f"selected_papers[{idx}] has invalid shelf item UUID"
        else:
            return None, f"selected_papers[{idx}] must be a string or object"

        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        ids_ordered.append(sid)

    rows = list(
        ResearchPaperShelfItem.objects.filter(session=session, id__in=ids_ordered)
    )
    by_id = {r.id: r for r in rows}

    normalized: list[dict[str, Any]] = []
    for sid in ids_ordered:
        row = by_id.get(sid)
        if row is None:
            return None, f"selected_papers: shelf item not in this session: {sid}"
        normalized.append(
            {
                "shelf_item_id": str(row.id),
                "source_kind": row.source_kind,
                "dedupe_key": row.dedupe_key,
                "title": (row.display_title or "")[:512],
                "primary_url": (row.primary_url or "")[:2048],
                "workspace_rel_path": (row.workspace_rel_path or "")[:1024],
                "context_tier": row.context_tier,
                "added_via": (row.added_via or "")[:64],
            }
        )
    return normalized, None


def _extract_workspace_refs(body: dict[str, Any], user_id: str) -> tuple[list[dict[str, str]] | None, str | None]:
    """请求体未带 ``workspace_refs`` 键时返回 ``(None, None)``；带了则校验并返回列表（可为空）。"""
    if "workspace_refs" not in body:
        return None, None
    from .session_context import parse_and_validate_workspace_refs

    return parse_and_validate_workspace_refs(user_id, body.get("workspace_refs"))


def _start_task_for_content(
    session: ResearchSession,
    content: str,
    options: dict[str, Any],
    *,
    user_id: str,
    workspace_refs: list[dict[str, str]] | None = None,
) -> BasicOrchestratorRun:
    if session.title in ("", "新会话"):
        session.title = content[:200] if len(content) > 200 else content
        session.save(update_fields=["title", "updated_at"])

    runtime_options = dict(options)
    if workspace_refs is not None:
        runtime_options["workspace_refs"] = list(workspace_refs)

    msg_meta: dict[str, Any] = {}
    if workspace_refs is not None:
        msg_meta["workspace_refs"] = list(workspace_refs)
    ResearchMessage.objects.create(session=session, role="user", content=content, metadata=msg_meta)
    ResearchMessage.objects.create(
        session=session,
        role="assistant",
        content="已收到请求，任务已启动。",
    )
    ResearchSession.objects.filter(pk=session.pk).update(updated_at=dj_tz.now())
    print(
        "[research_agent][request] "
        f"user={user_id} session={session.id} content={content[:120]}",
        flush=True,
    )

    run = BasicOrchestratorRun.objects.create(
        session=session,
        status="pending",
        steps=[],
        result_payload={"runtime_config": runtime_options},
    )
    start_first_segment_thread(run.id)
    return run


def _start_deep_research_task(
    session: ResearchSession,
    content: str,
    options: dict[str, Any],
    *,
    selected_papers: list[Any],
) -> AgentTask:
    """独立深度研究：与 basic 编排器分离的入口。"""
    if session.title in ("", "新会话"):
        session.title = content[:200] if len(content) > 200 else content
        session.save(update_fields=["title", "updated_at"])

    runtime_options = dict(options)
    runtime_options["deep_research_pipeline"] = True
    runtime_options["selected_papers"] = selected_papers

    ResearchMessage.objects.create(session=session, role="user", content=content)
    ResearchMessage.objects.create(
        session=session,
        role="assistant",
        content="已收到深度研究请求，任务已启动。",
    )
    ResearchSession.objects.filter(pk=session.pk).update(updated_at=dj_tz.now())

    task = AgentTask.objects.create(
        session=session,
        status="pending",
        steps=[],
        result_payload={"runtime_config": runtime_options},
    )
    start_deep_research_thread(task.id)
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
            latest_task = _latest_root_run(s)
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
    wrefs, werr = _extract_workspace_refs(body, identity.user_id)
    if werr:
        return _json_err(werr, 400)

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

    blocked = _quota_precheck(request, identity, FEATURE_RESEARCH_ASSISTANT)
    if blocked is not None:
        return blocked

    task = _start_task_for_content(
        session, content, options, user_id=identity.user_id, workspace_refs=wrefs
    )
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
    wrefs, werr = _extract_workspace_refs(body, identity.user_id)
    if werr:
        return _json_err(werr, 400)
    title = (body.get("title") or "新会话").strip() or "新会话"

    session = ResearchSession.objects.create(owner_id=identity.user_id, title=title)

    blocked = _quota_precheck(request, identity, FEATURE_RESEARCH_ASSISTANT)
    if blocked is not None:
        return blocked

    task = _start_task_for_content(
        session, content, options, user_id=identity.user_id, workspace_refs=wrefs
    )

    return _json_ok(
        {
            "task_id": str(task.id),
            "status": task.status,
            "session_id": str(session.id),
        },
        status=202,
    )


@require_http_methods(["POST"])
@authenticate_research_user
def create_deep_research_task(request, identity: ResearchIdentity):
    """独立深度研究 API（与会话 basic 编排无关）。``selected_papers`` 仅允许本会话展示区条目的 id，并在入口规范化。"""
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

    papers_raw = body.get("selected_papers")
    if papers_raw is None:
        papers: list[Any] = []
    elif isinstance(papers_raw, list):
        papers = papers_raw
    else:
        return _json_err("selected_papers must be an array", 400)

    session_id_raw = body.get("session_id")
    if papers and not session_id_raw:
        return _json_err("session_id is required when selected_papers is non-empty", 400)

    session = None
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
        title = (body.get("title") or "深度研究").strip() or "深度研究"
        session = ResearchSession.objects.create(owner_id=identity.user_id, title=title)

    papers_norm, perr = _validate_selected_papers_from_shelf(session, papers)
    if perr:
        return _json_err(perr, 400)

    blocked = _quota_precheck(request, identity, FEATURE_DEEP_RESEARCH)
    if blocked is not None:
        return blocked

    task = _start_deep_research_task(session, content, options, selected_papers=papers_norm or [])
    return _json_ok(
        {"task_id": str(task.id), "status": task.status, "session_id": str(session.id)},
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
            "metadata": m.metadata if isinstance(getattr(m, "metadata", None), dict) else {},
            "created_at": _format_dt(m.created_at),
        }
        for m in session.messages.all()
    ]
    active = _active_task(session)
    latest = _latest_root_run(session)
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
    wrefs, werr = _extract_workspace_refs(body, identity.user_id)
    if werr:
        return _json_err(werr, 400)

    if _active_task(session):
        return _json_err("A task is already in progress for this session", 409)

    blocked = _quota_precheck(request, identity, FEATURE_RESEARCH_ASSISTANT)
    if blocked is not None:
        return blocked

    task = _start_task_for_content(
        session, content, options, user_id=identity.user_id, workspace_refs=wrefs
    )

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
    task = resolve_owned_run(identity.user_id, tid)
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
    parent_task = resolve_owned_run(identity.user_id, tid)
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
    wrefs, werr = _extract_workspace_refs(body, identity.user_id)
    if werr:
        return _json_err(werr, 400)

    blocked = _quota_precheck(request, identity, FEATURE_RESEARCH_ASSISTANT)
    if blocked is not None:
        return blocked

    task = _start_task_for_content(
        parent_task.session, content, options, user_id=identity.user_id, workspace_refs=wrefs
    )
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
    task = resolve_owned_run(identity.user_id, tid)
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
    task = resolve_owned_run(identity.user_id, tid)
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
        _mark_local_file_action_approved(task)
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
    _mark_local_file_action_approved(task)
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
    task = resolve_owned_run(identity.user_id, tid)
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
def post_task_behavior_log(request, identity: ResearchIdentity, task_id):
    """
    用户态行为日志上报接口（供科研助手执行引擎日志探针调用）。
    """
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return _json_err("Not found", 404)

    task = resolve_owned_run(identity.user_id, tid)
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

    actor_type = _sanitize_actor_type(body.get("actor_type"), "user")
    raw_tool_type = str(body.get("tool_type") or "").strip()
    raw_status = str(body.get("status") or "").strip()
    trace_id = str(body.get("trace_id") or "").strip()
    step_id = _parse_int_or_none(body.get("step_id"))

    log = AgentBehaviorAuditLog.objects.create(
        **_behavior_audit_fk_kwargs(task),
        operation_type=operation_type,
        target_url=target_url,
        target_domain=target_domain,
        request_headers=_ensure_json_obj(body.get("request_headers")),
        request_payload=_ensure_json_obj(body.get("request_payload")),
        action_payload=_ensure_json_obj(body.get("action_payload")),
        step_id=step_id,
        trace_id=trace_id,
        actor_type=actor_type,
        tool_type=raw_tool_type,
        risk_level=str(body.get("risk_level") or "").strip().lower(),
        rule_hit=_compact_rule_hit(body.get("rule_hit")),
        policy_version=str(body.get("policy_version") or "").strip(),
        status=_normalize_audit_status(raw_status, is_exception=is_exception),
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


def _admin_behavior_logs_impl(request, audit_scope: str):
    qs = _behavior_logs_base_qs()
    qs, err = _apply_behavior_filters(
        qs, request.GET, default_scope=True, audit_scope=audit_scope
    )
    if err:
        return fail({"error": err})

    operation_type_options = _collect_operation_type_options(qs)
    qs = _apply_behavior_ordering(qs, request.GET)
    page_num = _parse_int_or_none(request.GET.get("page_num")) or 1
    page_size = _parse_int_or_none(request.GET.get("page_size")) or 20
    page_size = min(100, max(1, page_size))

    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        page = paginator.page(1)

    items = [item.to_dict() for item in page.object_list]
    _attach_behavior_display_fields(items)
    return ok(
        {
            "audit_scope": audit_scope,
            "total": paginator.count,
            "page_num": page.number,
            "page_size": page_size,
            "items": items,
            "operation_type_options": operation_type_options,
        }
    )


def _admin_task_behavior_chain_impl(_request, _admin, task_id, audit_scope: str):
    try:
        tid = uuid.UUID(str(task_id))
    except ValueError:
        return fail({"error": "任务不存在"})

    task = _resolve_run_for_audit_scope(tid, audit_scope)
    if task is None:
        return fail({"error": "任务不存在或类型与审计范围不匹配"})

    if audit_scope == AUDIT_SCOPE_ASSISTANT:
        logs = _behavior_logs_for_assistant_run(task)
    else:
        logs = _behavior_logs_for_run(task)

    user_id = str(task.session.owner_id)
    user_name = _resolve_user_name_map({user_id}).get(user_id, user_id)
    task_payload = _run_to_audit_task_json(task, user_name=user_name)
    if audit_scope == AUDIT_SCOPE_ASSISTANT and isinstance(task, BasicOrchestratorRun):
        task_payload["workspace_run_count"] = WorkspaceAgentRun.objects.filter(
            parent_basic_run_id=task.id
        ).count()

    visible_logs = [item for item in logs if not _should_hide_audit_log(item)]
    logs_payload = [item.to_dict() for item in visible_logs]
    _attach_behavior_display_fields(logs_payload)

    return ok(
        {
            "audit_scope": audit_scope,
            "task": task_payload,
            "logs": logs_payload,
        }
    )


def _audit_export_title(audit_scope: str) -> str:
    if audit_scope == AUDIT_SCOPE_DEEP_RESEARCH:
        return "深度研究行为审计报告"
    return "科研助手行为审计报告"


def _audit_export_file_prefix(audit_scope: str) -> str:
    if audit_scope == AUDIT_SCOPE_DEEP_RESEARCH:
        return "deep-research-audit"
    return "research-assistant-audit"


def _admin_export_behavior_logs_impl(request, _admin, audit_scope: str):
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return fail({"error": "请求体不是有效 JSON"})

    qs = _behavior_logs_base_qs()
    qs, err = _apply_behavior_filters(
        qs, body, default_scope=True, audit_scope=audit_scope
    )
    if err:
        return fail({"error": err})
    logs = list(qs.order_by("-occurred_at", "-id")[:500])

    generated_at = dj_tz.now().strftime("%Y-%m-%d %H:%M:%S")
    file_ts = dj_tz.now().strftime("%Y%m%d_%H%M%S")
    report_title = _audit_export_title(audit_scope)
    filters_text = {
        "user_name": str(body.get("user_name", "") or ""),
        "user_id": str(body.get("user_id", "") or ""),
        "task_name": str(body.get("task_name", "") or ""),
        "task_id": str(body.get("task_id", "") or ""),
        "task_status": str(body.get("task_status", "") or ""),
        "target_domain": str(body.get("target_domain", "") or ""),
        "operation_type": str(body.get("operation_type", "") or ""),
        "tool_type": str(body.get("tool_type", "") or ""),
        "actor_type": str(body.get("actor_type", "") or ""),
        "risk_level": str(body.get("risk_level", "") or ""),
        "audit_status": str(body.get("audit_status", "") or ""),
        "trace_id": str(body.get("trace_id", "") or ""),
        "step_id": str(body.get("step_id", "") or ""),
        "exception_status": str(body.get("exception_status", "") or "all"),
        "date_from": str(body.get("date_from", "") or ""),
        "date_to": str(body.get("date_to", "") or ""),
    }
    user_filter_text = filters_text["user_name"] or filters_text["user_id"] or "全部"
    task_filter_text = filters_text["task_name"] or filters_text["task_id"] or "全部"
    owner_ids = {
        str(item.session.owner_id).strip()
        for item in logs
        if item.session_id and str(item.session.owner_id or "").strip()
    }
    user_name_map = _resolve_user_name_map(owner_ids)

    lines = [
        f"# {report_title}",
        "",
        f"- 审计范围：{audit_scope}",
        f"- 生成时间：{generated_at}",
        f"- 记录条数：{len(logs)}（最多导出 500 条）",
        "- 筛选条件：",
        f"  - 用户名: {user_filter_text}",
        f"  - 任务名: {task_filter_text}",
        f"  - task_status: {filters_text['task_status'] or '全部'}",
        f"  - target_domain: {filters_text['target_domain'] or '全部'}",
        f"  - operation_type: {filters_text['operation_type'] or '全部'}",
        f"  - tool_type: {filters_text['tool_type'] or '全部'}",
        f"  - actor_type: {filters_text['actor_type'] or '全部'}",
        f"  - risk_level: {filters_text['risk_level'] or '全部'}",
        f"  - audit_status: {filters_text['audit_status'] or '全部'}",
        f"  - trace_id: {filters_text['trace_id'] or '全部'}",
        f"  - step_id: {filters_text['step_id'] or '全部'}",
        f"  - exception_status: {filters_text['exception_status'] or 'all'}",
        f"  - date_from: {filters_text['date_from'] or '不限'}",
        f"  - date_to: {filters_text['date_to'] or '不限'}",
        "",
        "| 时间 | 用户名 | 任务名 | 步骤ID | 追踪ID | 主体 | 工具 | 操作类型 | 审计状态 | 风险 | HTTP状态 | 异常 | 规则命中 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    operation_type_counts: dict[str, int] = {}
    task_status_counts: dict[str, int] = {}

    for item in logs:
        t_run = item.linked_run()
        session = item.session
        task_status = str(getattr(t_run, "status", "") or "").strip() or "-"
        task_status_counts[task_status] = task_status_counts.get(task_status, 0) + 1
        user_id = str(getattr(session, "owner_id", "") or "").strip()
        user_name = (user_name_map.get(user_id, user_id) or "-").replace("|", "\\|")
        task_name = str(getattr(session, "title", "") or "").strip()
        if not task_name:
            linked = item.linked_run()
            task_id_text = str(linked.id) if linked else ""
            task_name = f"任务-{task_id_text[:8]}" if task_id_text else "-"
        task_name = task_name.replace("|", "\\|")
        occurred = item.occurred_at.isoformat() if item.occurred_at else ""
        exception_text = "是" if item.is_exception else "否"
        summary = (item.exception_message or item.trace_detail or "").replace("\n", " ").strip()
        if len(summary) > 80:
            summary = f"{summary[:80]}..."
        summary = summary.replace("|", "\\|")
        operation_type = str(item.operation_type or "").strip() or "-"
        operation_type_counts[operation_type] = operation_type_counts.get(operation_type, 0) + 1
        lines.append(
            f"| {occurred} | {user_name} | {task_name} | {item.step_id or '-'} | "
            f"{item.trace_id or '-'} | {item.actor_type or '-'} | {item.tool_type or '-'} | "
            f"{item.operation_type} | {item.status or '-'} | {item.risk_level or '-'} | {item.response_status or '-'} | "
            f"{exception_text} | {item.rule_hit or '-'} | {summary or '-'} |"
        )

    lines.extend(["", "## 分布统计", "", "### task_status 分布"])
    if task_status_counts:
        for key, count in sorted(task_status_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- 无")

    lines.extend(["", "### operation_type 分布"])
    if operation_type_counts:
        for key, count in sorted(operation_type_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- 无")

    return ok(
        {
            "audit_scope": audit_scope,
            "file_name": f"{_audit_export_file_prefix(audit_scope)}-{file_ts}.md",
            "content": "\n".join(lines),
            "count": len(logs),
        }
    )


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_behavior_logs(request, _admin):
    """兼容旧路由：须传 query audit_scope=assistant|deep_research。"""
    scope = str(request.GET.get("audit_scope", "") or "").strip()
    if scope not in _AUDIT_SCOPES:
        return fail(
            {
                "error": (
                    "请使用 /manage/assistant/behavior-logs/ 或 "
                    "/manage/deep-research/behavior-logs/，"
                    "或提供 audit_scope=assistant|deep_research"
                )
            }
        )
    return _admin_behavior_logs_impl(request, scope)


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_task_behavior_chain(request, _admin, task_id):
    scope = str(request.GET.get("audit_scope", "") or "").strip()
    if scope not in _AUDIT_SCOPES:
        return fail(
            {
                "error": (
                    "请使用 /manage/assistant/tasks/<id>/behavior-chain/ 或 "
                    "/manage/deep-research/tasks/<id>/behavior-chain/，"
                    "或提供 audit_scope=assistant|deep_research"
                )
            }
        )
    return _admin_task_behavior_chain_impl(request, _admin, task_id, scope)


@require_http_methods(["POST"])
@authenticate_research_admin
def admin_export_behavior_logs(request, _admin):
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return fail({"error": "请求体不是有效 JSON"})
    scope = str(body.get("audit_scope", "") or "").strip()
    if scope not in _AUDIT_SCOPES:
        return fail(
            {
                "error": (
                    "请使用 /manage/assistant/behavior-logs/export/ 或 "
                    "/manage/deep-research/behavior-logs/export/，"
                    "或在 body 中提供 audit_scope=assistant|deep_research"
                )
            }
        )
    return _admin_export_behavior_logs_impl(request, _admin, scope)


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
    task = resolve_owned_run(identity.user_id, tid)
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
    task = resolve_owned_run(identity.user_id, tid)
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
    task = resolve_owned_run(identity.user_id, tid)
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
        # post_cancel_task / post_intervention 都被 @authenticate_research_user 装饰，
        # 装饰器会自己从请求里解析 identity 并注入；这里再手动传 identity 会让真正的
        # view 函数收到 4 个位置参数，触发 TypeError。
        return post_cancel_task(request, task_id)

    mapped = "approve" if action == "allow" else "revise"
    req_body = {"decision": mapped}
    if action == "revise":
        req_body["message"] = body.get("message", "")
    request._body = json.dumps(req_body).encode("utf-8")
    return post_intervention(request, task_id)


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
    deep = list(
        AgentTask.objects.filter(
            id__in=task_ids,
            session__owner_id=identity.user_id,
            status="completed",
        ).select_related("session")
    )
    basic = list(
        BasicOrchestratorRun.objects.filter(
            id__in=task_ids,
            session__owner_id=identity.user_id,
            status="completed",
        ).select_related("session")
    )
    workspace = list(
        WorkspaceAgentRun.objects.filter(
            id__in=task_ids,
            session__owner_id=identity.user_id,
            status="completed",
        ).select_related("session")
    )
    tasks: list[AnyRun] = [*deep, *basic, *workspace]
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


def _session_owned_or_404(identity: ResearchIdentity, session_id) -> ResearchSession | None:
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        return None
    return ResearchSession.objects.filter(id=sid, owner_id=identity.user_id).first()


@require_http_methods(["GET"])
@authenticate_research_user
def paper_shelf_list(request, identity: ResearchIdentity, session_id):
    session = _session_owned_or_404(identity, session_id)
    if not session:
        return _json_err("Not found", 404)
    items = [
        shelf_item_to_api_dict(x)
        for x in ResearchPaperShelfItem.objects.filter(session=session).order_by("-created_at")[:500]
    ]
    return _json_ok({"session_id": str(session.id), "items": items, "total": len(items)})


@require_http_methods(["POST"])
@authenticate_research_user
def paper_shelf_add_workspace(request, identity: ResearchIdentity, session_id):
    session = _session_owned_or_404(identity, session_id)
    if not session:
        return _json_err("Not found", 404)
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return _json_err("Invalid JSON", 400)
    rel = str(body.get("workspace_rel_path") or body.get("rel_path") or "").strip()
    if not rel:
        return _json_err("workspace_rel_path is required", 400)
    item = add_workspace_item(session, identity.user_id, rel)
    if item is None:
        return _json_err("工作区路径无效、越界或目标不是文件", 400, "WORKSPACE_PATH_INVALID")
    return _json_ok({"item": shelf_item_to_api_dict(item)}, status=201)


@require_http_methods(["DELETE"])
@authenticate_research_user
def paper_shelf_delete_item(request, identity: ResearchIdentity, session_id, item_id):
    session = _session_owned_or_404(identity, session_id)
    if not session:
        return _json_err("Not found", 404)
    try:
        iid = uuid.UUID(str(item_id))
    except ValueError:
        return _json_err("Not found", 404)
    deleted, _ = ResearchPaperShelfItem.objects.filter(session=session, id=iid).delete()
    if not deleted:
        return _json_err("Not found", 404)
    return _json_ok({"deleted": True, "id": str(iid)})
