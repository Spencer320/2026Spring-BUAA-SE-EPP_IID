from __future__ import annotations

import json
import logging
import uuid
from functools import wraps
from typing import Any

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from business.models.user import User
from business.utils.response import fail, ok

from .auth import ResearchIdentity, authenticate_research_admin
from .models import AgentBehaviorAuditLog, SiteAccessPolicyConfig, SiteAccessRule
from .site_access_control import (
    DEFAULT_POLICY_MODE,
    DEFAULT_POLICY_VERSION,
    bump_policy_version,
    current_policy,
    normalize_domain,
)

logger = logging.getLogger(__name__)


def _site_access_schema_unavailable_response() -> JsonResponse:
    return JsonResponse(
        {
            "ok": False,
            "error": {
                "code": "SITE_ACCESS_SCHEMA_UNAVAILABLE",
                "message": "Site access tables are unavailable. Please run migrate research_agent.",
            },
        },
        status=500,
    )


def _handle_site_access_db_errors(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (OperationalError, ProgrammingError):
            logger.exception("Site access API schema unavailable")
            return _site_access_schema_unavailable_response()

    return wrapped


def _admin_name(identity: ResearchIdentity) -> str:
    return str(identity.user_id or "").strip()[:64]


def _parse_bool_or_none(raw: Any) -> bool | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_positive_int(value: Any, default: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, num)


def _normalize_pattern_input(pattern: str, match_type: str) -> str:
    text = (pattern or "").strip().lower()
    text = text.replace("https://", "").replace("http://", "")
    text = text.split("/", 1)[0].strip().rstrip(".")
    if match_type in {"exact", "suffix"}:
        text = normalize_domain(text)
    return text


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
    rows = User.objects.filter(user_id__in=parsed_ids).values("user_id", "username")
    return {str(item["user_id"]): str(item["username"]) for item in rows}


def _attach_user_names(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    user_ids = {
        str(item.get("user_id", "")).strip()
        for item in items
        if str(item.get("user_id", "")).strip()
    }
    user_name_map = _resolve_user_name_map(user_ids)
    for item in items:
        user_id = str(item.get("user_id", "")).strip()
        item["user_name"] = user_name_map.get(user_id, user_id)
    return items


def _site_event_queryset():
    return AgentBehaviorAuditLog.objects.select_related("task", "task__session").filter(
        Q(rule_hit__icontains="site_access") | Q(rule_hit__istartswith="static_allowlist")
    )


@_handle_site_access_db_errors
@require_http_methods(["GET", "PUT"])
@authenticate_research_admin
def admin_site_access_policy(request, admin: ResearchIdentity):
    if request.method == "GET":
        policy = current_policy()
        mode = policy.mode if policy else DEFAULT_POLICY_MODE
        version = int(policy.policy_version) if policy else DEFAULT_POLICY_VERSION
        rule_qs = SiteAccessRule.objects.all()
        return ok(
            {
                "policy": (
                    policy.to_dict()
                    if policy
                    else {
                        "id": None,
                        "mode": mode,
                        "policy_version": version,
                        "updated_by": "",
                        "description": "",
                        "updated_at": "",
                    }
                ),
                "rule_summary": {
                    "total": rule_qs.count(),
                    "enabled": rule_qs.filter(is_enabled=True).count(),
                    "allow": rule_qs.filter(rule_type="allow").count(),
                    "deny": rule_qs.filter(rule_type="deny").count(),
                },
            }
        )

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return fail({"error": "Invalid JSON body"})

    mode = str(body.get("mode", "") or "").strip().lower()
    description = str(body.get("description", "") or "").strip()
    if mode and mode not in {"whitelist", "blacklist"}:
        return fail({"error": "mode must be whitelist or blacklist"})

    with transaction.atomic():
        policy = SiteAccessPolicyConfig.objects.select_for_update().order_by("-id").first()
        if policy is None:
            policy = SiteAccessPolicyConfig.objects.create(
                mode=DEFAULT_POLICY_MODE,
                policy_version=DEFAULT_POLICY_VERSION,
                updated_by=_admin_name(admin),
            )
        changed = False
        if mode and policy.mode != mode:
            policy.mode = mode
            changed = True
        if "description" in body and policy.description != description[:255]:
            policy.description = description[:255]
            changed = True
        if changed:
            policy.policy_version = int(policy.policy_version or DEFAULT_POLICY_VERSION) + 1
            policy.updated_by = _admin_name(admin)
            policy.save(update_fields=["mode", "description", "policy_version", "updated_by", "updated_at"])

    return ok({"policy": policy.to_dict(), "changed": changed})


@_handle_site_access_db_errors
@require_http_methods(["GET", "POST"])
@authenticate_research_admin
def admin_site_access_rules(request, admin: ResearchIdentity):
    if request.method == "GET":
        qs = SiteAccessRule.objects.all().order_by("priority", "rule_id")
        keyword = str(request.GET.get("keyword", "") or "").strip().lower()
        if keyword:
            qs = qs.filter(pattern__icontains=keyword)
        rule_type = str(request.GET.get("rule_type", "") or "").strip().lower()
        if rule_type in {"allow", "deny"}:
            qs = qs.filter(rule_type=rule_type)
        match_type = str(request.GET.get("match_type", "") or "").strip().lower()
        if match_type in {"exact", "suffix", "wildcard"}:
            qs = qs.filter(match_type=match_type)
        enabled = _parse_bool_or_none(request.GET.get("is_enabled"))
        if enabled is not None:
            qs = qs.filter(is_enabled=enabled)
        return ok({"rules": [item.to_dict() for item in qs]})

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return fail({"error": "Invalid JSON body"})

    rule_type = str(body.get("rule_type", "") or "").strip().lower()
    match_type = str(body.get("match_type", "") or "").strip().lower()
    pattern_raw = str(body.get("pattern", "") or "").strip()
    priority = int(body.get("priority", 100))
    is_enabled = bool(body.get("is_enabled", True))
    description = str(body.get("description", "") or "").strip()[:255]

    if rule_type not in {"allow", "deny"}:
        return fail({"error": "rule_type must be allow or deny"})
    if match_type not in {"exact", "suffix", "wildcard"}:
        return fail({"error": "match_type must be exact, suffix, or wildcard"})
    pattern = _normalize_pattern_input(pattern_raw, match_type)
    if not pattern:
        return fail({"error": "pattern is required"})
    if match_type in {"exact", "suffix"} and "*" in pattern:
        return fail({"error": "exact/suffix rule does not support *"})
    if priority < 1 or priority > 9999:
        return fail({"error": "priority must be between 1 and 9999"})

    rule = SiteAccessRule.objects.create(
        rule_type=rule_type,
        match_type=match_type,
        pattern=pattern,
        priority=priority,
        is_enabled=is_enabled,
        description=description,
        created_by=_admin_name(admin),
        updated_by=_admin_name(admin),
    )
    policy = bump_policy_version(updated_by=_admin_name(admin))
    return ok({"rule": rule.to_dict(), "policy_version": int(policy.policy_version or DEFAULT_POLICY_VERSION)})


@_handle_site_access_db_errors
@require_http_methods(["PUT", "DELETE"])
@authenticate_research_admin
def admin_site_access_rule_detail(request, admin: ResearchIdentity, rule_id: int):
    rule = SiteAccessRule.objects.filter(rule_id=rule_id).first()
    if rule is None:
        return fail({"error": "rule not found"})

    if request.method == "DELETE":
        rule.delete()
        policy = bump_policy_version(updated_by=_admin_name(admin))
        return ok({"deleted": True, "rule_id": int(rule_id), "policy_version": int(policy.policy_version or DEFAULT_POLICY_VERSION)})

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return fail({"error": "Invalid JSON body"})

    updated_fields: list[str] = []
    if "rule_type" in body:
        rule_type = str(body.get("rule_type", "") or "").strip().lower()
        if rule_type not in {"allow", "deny"}:
            return fail({"error": "rule_type must be allow or deny"})
        rule.rule_type = rule_type
        updated_fields.append("rule_type")
    if "match_type" in body:
        match_type = str(body.get("match_type", "") or "").strip().lower()
        if match_type not in {"exact", "suffix", "wildcard"}:
            return fail({"error": "match_type must be exact, suffix, or wildcard"})
        rule.match_type = match_type
        updated_fields.append("match_type")
    if "pattern" in body:
        pattern = _normalize_pattern_input(str(body.get("pattern", "") or ""), rule.match_type)
        if not pattern:
            return fail({"error": "pattern is required"})
        if rule.match_type in {"exact", "suffix"} and "*" in pattern:
            return fail({"error": "exact/suffix rule does not support *"})
        rule.pattern = pattern
        updated_fields.append("pattern")
    if "priority" in body:
        try:
            priority = int(body.get("priority"))
        except (TypeError, ValueError):
            return fail({"error": "priority must be integer"})
        if priority < 1 or priority > 9999:
            return fail({"error": "priority must be between 1 and 9999"})
        rule.priority = priority
        updated_fields.append("priority")
    if "is_enabled" in body:
        rule.is_enabled = bool(body.get("is_enabled"))
        updated_fields.append("is_enabled")
    if "description" in body:
        rule.description = str(body.get("description", "") or "").strip()[:255]
        updated_fields.append("description")

    if not updated_fields:
        return ok({"rule": rule.to_dict(), "changed": False})

    rule.updated_by = _admin_name(admin)
    rule.save(update_fields=[*updated_fields, "updated_by", "updated_at"])
    policy = bump_policy_version(updated_by=_admin_name(admin))
    return ok({"rule": rule.to_dict(), "changed": True, "policy_version": int(policy.policy_version or DEFAULT_POLICY_VERSION)})


@_handle_site_access_db_errors
@require_http_methods(["GET"])
@authenticate_research_admin
def admin_site_access_events(request, _admin: ResearchIdentity):
    qs = _site_event_queryset().order_by("-occurred_at", "-id")
    target_domain = str(request.GET.get("target_domain", "") or "").strip().lower()
    if target_domain:
        qs = qs.filter(target_domain__icontains=target_domain)
    status = str(request.GET.get("status", "") or "").strip().lower()
    if status:
        qs = qs.filter(status=status)
    tool_type = str(request.GET.get("tool_type", "") or "").strip().lower()
    if tool_type:
        qs = qs.filter(tool_type=tool_type)

    page_num = _parse_positive_int(request.GET.get("page_num"), 1)
    page_size = min(100, _parse_positive_int(request.GET.get("page_size"), 20))
    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        page = paginator.page(1)

    items = [item.to_dict() for item in page.object_list]
    _attach_user_names(items)
    return ok(
        {
            "items": items,
            "total": paginator.count,
            "page_num": page.number,
            "page_size": page_size,
        }
    )


@_handle_site_access_db_errors
@require_http_methods(["GET"])
@authenticate_research_admin
def admin_site_access_stats(request, _admin: ResearchIdentity):
    policy = current_policy()
    rules = SiteAccessRule.objects.all()
    events = _site_event_queryset()
    blocked_qs = events.filter(status="rejected")
    allowed_qs = events.filter(status__in=["allowed", "succeeded"])

    top_blocked_domains = list(
        blocked_qs.exclude(target_domain="")
        .values("target_domain")
        .annotate(count=Count("id"))
        .order_by("-count", "target_domain")[:10]
    )
    top_allowed_domains = list(
        allowed_qs.exclude(target_domain="")
        .values("target_domain")
        .annotate(count=Count("id"))
        .order_by("-count", "target_domain")[:10]
    )

    return ok(
        {
            "policy": (
                policy.to_dict()
                if policy
                else {
                    "id": None,
                    "mode": DEFAULT_POLICY_MODE,
                    "policy_version": DEFAULT_POLICY_VERSION,
                    "updated_by": "",
                    "description": "",
                    "updated_at": "",
                }
            ),
            "rules": {
                "total": rules.count(),
                "enabled": rules.filter(is_enabled=True).count(),
                "allow": rules.filter(rule_type="allow").count(),
                "deny": rules.filter(rule_type="deny").count(),
            },
            "events": {
                "total": events.count(),
                "blocked": blocked_qs.count(),
                "allowed": allowed_qs.count(),
            },
            "top_blocked_domains": top_blocked_domains,
            "top_allowed_domains": top_allowed_domains,
        }
    )
