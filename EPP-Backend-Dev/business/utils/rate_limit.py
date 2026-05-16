"""
访问频次 / 配额控制工具函数。

- deep_research：按窗口内任务次数（创建任务前检查，通过即写一条 allowed 日志）
- research_assistant：按窗口内 Token 累计（创建 run 前检查；run 结束后写 tokens 日志）
"""

from __future__ import annotations

import datetime
import threading
from typing import Any

from django.utils import timezone

from business.models.access_frequency import (
    FEATURE_DEEP_RESEARCH,
    FEATURE_QUOTA_MODE,
    FEATURE_RESEARCH_ASSISTANT,
)


def _get_window_start(window: str) -> datetime.datetime:
    """计算指定时间窗口的起始时间点（时区感知）"""
    now = timezone.now()
    if window == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "weekly":
        days_since_monday = now.weekday()
        return (now - datetime.timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if window == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _write_log_async(user, feature: str, ip_address, status: str, extra: dict):
    """在后台线程中异步写入 FeatureAccessLog，失败不抛出异常"""

    def _write():
        try:
            from business.models.access_frequency import FeatureAccessLog

            FeatureAccessLog.objects.create(
                user=user,
                feature=feature,
                ip_address=ip_address,
                status=status,
                extra=extra or {},
            )
        except Exception:
            pass

    threading.Thread(target=_write, daemon=True).start()


def _resolve_quota_limit(user, feature: str) -> dict[str, Any]:
    """
    解析用户对某 feature 的有效配额。
    返回 unlimited, banned, max_limit, window, override_applied, rule_enabled
    """
    from business.models.access_frequency import AccessFrequencyRule, UserAccessQuotaOverride

    override = UserAccessQuotaOverride.objects.filter(user=user, feature=feature).first()
    global_rule = AccessFrequencyRule.objects.filter(feature=feature).first()

    if override is not None:
        max_limit = int(override.max_count)
        window = global_rule.window if global_rule else "daily"
        return {
            "unlimited": max_limit == -1,
            "banned": max_limit == 0,
            "max_limit": max_limit,
            "window": window,
            "override_applied": True,
            "rule_enabled": True,
        }

    rule = AccessFrequencyRule.objects.filter(feature=feature, is_enabled=True).first()
    if rule is None:
        return {
            "unlimited": True,
            "banned": False,
            "max_limit": -1,
            "window": "daily",
            "override_applied": False,
            "rule_enabled": False,
        }

    max_limit = int(rule.max_count)
    return {
        "unlimited": max_limit == -1,
        "banned": max_limit == 0,
        "max_limit": max_limit,
        "window": rule.window,
        "override_applied": False,
        "rule_enabled": True,
    }


def _sum_allowed_tokens(user, feature: str, window_start: datetime.datetime) -> int:
    from business.models.access_frequency import FeatureAccessLog

    total = 0
    qs = FeatureAccessLog.objects.filter(
        user=user,
        feature=feature,
        status=FeatureAccessLog.STATUS_ALLOWED,
        accessed_at__gte=window_start,
    ).only("extra")
    for row in qs.iterator(chunk_size=200):
        extra = row.extra if isinstance(row.extra, dict) else {}
        try:
            total += max(0, int(extra.get("tokens") or 0))
        except (TypeError, ValueError):
            continue
    return total


def _count_allowed_usage(user, feature: str, window_start: datetime.datetime) -> int:
    from business.models.access_frequency import FeatureAccessLog

    return FeatureAccessLog.objects.filter(
        user=user,
        feature=feature,
        status=FeatureAccessLog.STATUS_ALLOWED,
        accessed_at__gte=window_start,
    ).count()


def _window_label(window: str) -> str:
    return {"daily": "今日", "weekly": "本周", "monthly": "本月"}.get(window, "当前周期")


def _quota_unit_label(feature: str) -> str:
    if FEATURE_QUOTA_MODE.get(feature) == "tokens":
        return "Token"
    return "次"


def check_quota_before_start(
    user, feature: str, ip_address: str | None = None, extra: dict | None = None
) -> tuple[bool, str]:
    """
    在用户发起高成本操作**之前**检查配额（仅检查，科研助手不在此时写放行日志）。

    deep_research：按次数，通过时立即写 allowed 日志（与一次任务创建对应）。
    research_assistant：按 Token 累计，通过时不写日志（run 结束后由 record_research_assistant_usage 写入）。
    """
    from business.models.access_frequency import FeatureAccessLog

    extra = dict(extra or {})
    quota = _resolve_quota_limit(user, feature)
    mode = FEATURE_QUOTA_MODE.get(feature, "count")

    if quota["unlimited"]:
        if mode == "count":
            _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_ALLOWED, extra)
        return True, ""

    if quota["banned"]:
        _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_REJECTED, extra)
        return False, "您已被禁止使用该功能，如有疑问请联系管理员。"

    window_start = _get_window_start(quota["window"])
    max_limit = int(quota["max_limit"])
    label = _window_label(quota["window"])
    unit = _quota_unit_label(feature)

    if mode == "tokens":
        used = _sum_allowed_tokens(user, feature, window_start)
        if used >= max_limit:
            _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_REJECTED, extra)
            return (
                False,
                f"{label}科研助手 Token 用量已达上限（{max_limit:,}），请稍后再试或联系管理员提升配额。",
            )
        return True, ""

    used = _count_allowed_usage(user, feature, window_start)
    if used >= max_limit:
        _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_REJECTED, extra)
        return (
            False,
            f"{label}深度研究使用次数已达上限（{max_limit} {unit}），请稍后再试或联系管理员提升配额。",
        )

    _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_ALLOWED, extra)
    return True, ""


def check_rate_limit(
    user, feature: str, ip_address: str | None = None, extra: dict | None = None
) -> tuple[bool, str]:
    """兼容旧名：等同于 check_quota_before_start。"""
    return check_quota_before_start(user, feature, ip_address=ip_address, extra=extra)


def record_research_assistant_usage(
    user,
    tokens: int,
    *,
    run_id: str,
    session_id: str,
    ip_address: str | None = None,
    extra: dict | None = None,
) -> None:
    """科研助手一轮对话结束后记账（累计 Token）。"""
    from business.models.access_frequency import FeatureAccessLog

    payload = dict(extra or {})
    payload.update(
        {
            "tokens": max(0, int(tokens)),
            "run_id": str(run_id),
            "session_id": str(session_id),
        }
    )
    _write_log_async(
        user,
        FEATURE_RESEARCH_ASSISTANT,
        ip_address,
        FeatureAccessLog.STATUS_ALLOWED,
        payload,
    )


def get_user_feature_usage(user, feature: str) -> dict:
    """查询用户当前周期用量（管理端 / 用户侧展示）。"""
    quota = _resolve_quota_limit(user, feature)
    mode = FEATURE_QUOTA_MODE.get(feature, "count")
    window = quota["window"]
    window_start = _get_window_start(window)

    if mode == "tokens":
        used = _sum_allowed_tokens(user, feature, window_start)
    else:
        used = _count_allowed_usage(user, feature, window_start)

    max_limit = int(quota["max_limit"])
    remaining = None if quota["unlimited"] else max(0, max_limit - used)

    return {
        "feature": feature,
        "quota_mode": mode,
        "quota_unit": "tokens" if mode == "tokens" else "count",
        "window": window,
        "limit": max_limit,
        "used": used,
        "remaining": remaining,
        "override_applied": quota["override_applied"],
    }


__all__ = [
    "FEATURE_DEEP_RESEARCH",
    "FEATURE_RESEARCH_ASSISTANT",
    "check_quota_before_start",
    "check_rate_limit",
    "record_research_assistant_usage",
    "get_user_feature_usage",
    "_get_window_start",
]
