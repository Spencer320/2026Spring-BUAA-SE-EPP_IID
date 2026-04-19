"""
访问频次控制工具函数

核心函数：check_rate_limit(user, feature, ip_address, extra)

在用户侧高成本接口（如创建 Deep Research 任务）的视图函数中调用，
返回 (allowed: bool, message: str)，超限时 message 包含对用户友好的提示。

日志异步写入，不阻塞主请求响应。
"""

import datetime
import threading

from django.utils import timezone


def _get_window_start(window: str) -> datetime.datetime:
    """计算指定时间窗口的起始时间点（时区感知）"""
    now = timezone.now()
    if window == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif window == "weekly":
        days_since_monday = now.weekday()
        return (now - datetime.timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif window == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 默认按日
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


def check_rate_limit(
    user, feature: str, ip_address: str = None, extra: dict = None
) -> tuple[bool, str]:
    """
    检查用户对指定功能的访问频次是否超限。

    优先级：用户级配额覆盖 > 全局规则 > 无规则（放行）

    Args:
        user:        Django User 对象（business.models.User）
        feature:     功能标识符，对应 FEATURE_CHOICES 中的 key，
                     如 "deep_research"、"ai_chat"、"summary"、"export"
        ip_address:  客户端 IP，可通过 request.META.get("REMOTE_ADDR") 获取，可为 None
        extra:       附加信息 dict，存入日志 extra 字段，如 {"task_id": "xxx"}

    Returns:
        (allowed, message)
        - allowed=True  放行，调用方继续处理请求
        - allowed=False 超限，调用方应立即返回 fail({"error": message})

    日志由本函数内部在后台线程中写入 FeatureAccessLog，调用方无需手动处理。

    Usage example (in view):
        allowed, msg = check_rate_limit(user, "deep_research",
                                        ip_address=request.META.get("REMOTE_ADDR"))
        if not allowed:
            return fail({"error": msg})
        # ... 继续创建任务
    """
    from business.models.access_frequency import (
        AccessFrequencyRule,
        FeatureAccessLog,
        UserAccessQuotaOverride,
    )

    extra = extra or {}

    # ── 1. 查询有效配额上限 ──────────────────────────────────────────
    override = UserAccessQuotaOverride.objects.filter(
        user=user, feature=feature
    ).first()

    if override is not None:
        max_count = override.max_count
        # 窗口沿用全局规则，若无全局规则则默认 daily
        global_rule = AccessFrequencyRule.objects.filter(feature=feature).first()
        window = global_rule.window if global_rule else "daily"
    else:
        rule = AccessFrequencyRule.objects.filter(
            feature=feature, is_enabled=True
        ).first()
        if rule is None:
            # 无启用规则，直接放行
            _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_ALLOWED, extra)
            return True, ""
        max_count = rule.max_count
        window = rule.window

    # ── 2. 特殊值判断 ────────────────────────────────────────────────
    if max_count == -1:
        # 不限制
        _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_ALLOWED, extra)
        return True, ""

    if max_count == 0:
        # 完全封禁
        _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_REJECTED, extra)
        return False, "您已被禁止使用该功能，如有疑问请联系管理员。"

    # ── 3. 统计当前时间窗口内已放行次数 ──────────────────────────────
    window_start = _get_window_start(window)
    used_count = FeatureAccessLog.objects.filter(
        user=user,
        feature=feature,
        status=FeatureAccessLog.STATUS_ALLOWED,
        accessed_at__gte=window_start,
    ).count()

    # ── 4. 判断是否超限 ──────────────────────────────────────────────
    if used_count >= max_count:
        _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_REJECTED, extra)
        window_labels = {"daily": "今日", "weekly": "本周", "monthly": "本月"}
        label = window_labels.get(window, "当前周期")
        return (
            False,
            f"{label}该功能使用次数已达上限（{max_count} 次），请稍后再试或联系管理员提升配额。",
        )

    _write_log_async(user, feature, ip_address, FeatureAccessLog.STATUS_ALLOWED, extra)
    return True, ""


def get_user_feature_usage(user, feature: str) -> dict:
    """
    查询用户对某功能的当前周期用量（供用户侧接口展示剩余次数）。

    Returns:
        {
          "feature": str,
          "window": str,          # "daily" / "weekly" / "monthly"
          "limit": int,           # -1 表示不限
          "used": int,
          "remaining": int | None,  # limit=-1 时为 None
          "override_applied": bool
        }
    """
    from business.models.access_frequency import (
        AccessFrequencyRule,
        FeatureAccessLog,
        UserAccessQuotaOverride,
    )

    override = UserAccessQuotaOverride.objects.filter(
        user=user, feature=feature
    ).first()

    if override is not None:
        max_count = override.max_count
        global_rule = AccessFrequencyRule.objects.filter(feature=feature).first()
        window = global_rule.window if global_rule else "daily"
        override_applied = True
    else:
        rule = AccessFrequencyRule.objects.filter(
            feature=feature, is_enabled=True
        ).first()
        if rule is None:
            return {
                "feature": feature,
                "window": "daily",
                "limit": -1,
                "used": 0,
                "remaining": None,
                "override_applied": False,
            }
        max_count = rule.max_count
        window = rule.window
        override_applied = False

    window_start = _get_window_start(window)
    used = FeatureAccessLog.objects.filter(
        user=user,
        feature=feature,
        status=FeatureAccessLog.STATUS_ALLOWED,
        accessed_at__gte=window_start,
    ).count()

    remaining = None if max_count == -1 else max(0, max_count - used)

    return {
        "feature": feature,
        "window": window,
        "limit": max_count,
        "used": used,
        "remaining": remaining,
        "override_applied": override_applied,
    }
