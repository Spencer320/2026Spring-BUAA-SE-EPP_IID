"""
管理端——访问频次控制接口
路由前缀：/api/manage/access-frequency/

接口列表：
  规则管理
    GET  /rules                               rule_list_create (GET)
    POST /rules                               rule_list_create (POST)
    PUT  /rules/<rule_id>                     rule_update_delete (PUT)
    DELETE /rules/<rule_id>                   rule_update_delete (DELETE)

  用户配额覆盖
    GET  /user-overrides                      override_list_create (GET)
    POST /user-overrides                      override_list_create (POST)
    DELETE /user-overrides/<override_id>      override_delete

  统计查询
    GET  /stats                               global_stats
    GET  /stats/users                         user_stats_ranking
    GET  /stats/users/<user_id>               user_stats_detail
"""

import json

from django.db.models import Count, Q
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from business.models import Admin, User
from business.models.access_frequency import (
    FEATURE_CHOICES,
    AccessFrequencyRule,
    FeatureAccessLog,
    UserAccessQuotaOverride,
)
from business.utils.authenticate import authenticate_admin
from business.utils.rate_limit import _get_window_start
from business.utils.response import fail, ok


# ══════════════════════════════════════════════════════════════════════
# 规则管理
# ══════════════════════════════════════════════════════════════════════


@authenticate_admin
def rule_list_create(request, admin: Admin):
    """
    GET  /api/manage/access-frequency/rules  查询全部规则
    POST /api/manage/access-frequency/rules  新增规则
    """
    if request.method == "GET":
        rules = AccessFrequencyRule.objects.all().order_by("rule_id")
        return ok({"rules": [r.to_dict() for r in rules]})

    if request.method == "POST":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return fail({"error": "请求体不是合法 JSON"})

        feature = body.get("feature", "").strip()
        window = body.get("window", "daily")
        max_count = body.get("max_count")
        is_enabled = body.get("is_enabled", True)
        description = body.get("description", "")

        valid_features = [k for k, _ in FEATURE_CHOICES]
        if feature not in valid_features:
            return fail({"error": f"feature 无效，可选值：{valid_features}"})
        if window not in ("daily", "weekly", "monthly"):
            return fail({"error": "window 无效，可选值：daily / weekly / monthly"})
        if max_count is None or not isinstance(max_count, int):
            return fail({"error": "max_count 必须为整数"})

        if AccessFrequencyRule.objects.filter(feature=feature).exists():
            return fail({"error": f"功能 '{feature}' 的规则已存在，请使用 PUT 接口修改"})

        rule = AccessFrequencyRule.objects.create(
            feature=feature,
            window=window,
            max_count=max_count,
            is_enabled=is_enabled,
            description=description,
            updated_by=admin.admin_name,
        )
        return ok({"rule": rule.to_dict()})

    return fail({"error": "不支持的请求方法"})


@authenticate_admin
def rule_update_delete(request, admin: Admin, rule_id: int):
    """
    PUT    /api/manage/access-frequency/rules/<rule_id>  修改规则
    DELETE /api/manage/access-frequency/rules/<rule_id>  删除规则
    """
    rule = AccessFrequencyRule.objects.filter(rule_id=rule_id).first()
    if rule is None:
        return fail({"error": "规则不存在"})

    if request.method == "PUT":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return fail({"error": "请求体不是合法 JSON"})

        if "window" in body:
            if body["window"] not in ("daily", "weekly", "monthly"):
                return fail({"error": "window 无效"})
            rule.window = body["window"]
        if "max_count" in body:
            if not isinstance(body["max_count"], int):
                return fail({"error": "max_count 必须为整数"})
            rule.max_count = body["max_count"]
        if "is_enabled" in body:
            rule.is_enabled = bool(body["is_enabled"])
        if "description" in body:
            rule.description = str(body["description"])

        rule.updated_by = admin.admin_name
        rule.save()
        return ok({"rule": rule.to_dict()})

    if request.method == "DELETE":
        rule.delete()
        return ok({"message": "规则已删除"})

    return fail({"error": "不支持的请求方法"})


# ══════════════════════════════════════════════════════════════════════
# 用户配额覆盖
# ══════════════════════════════════════════════════════════════════════


@authenticate_admin
def override_list_create(request, admin: Admin):
    """
    GET  /api/manage/access-frequency/user-overrides  查询覆盖列表
         支持查询参数：user_id、feature
    POST /api/manage/access-frequency/user-overrides  新增或更新覆盖
    """
    if request.method == "GET":
        qs = UserAccessQuotaOverride.objects.select_related("user").all()
        user_id = request.GET.get("user_id")
        feature = request.GET.get("feature")
        if user_id:
            qs = qs.filter(user__user_id=user_id)
        if feature:
            qs = qs.filter(feature=feature)
        return ok({"overrides": [o.to_dict() for o in qs.order_by("pk")]})

    if request.method == "POST":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return fail({"error": "请求体不是合法 JSON"})

        user_id = body.get("user_id", "").strip()
        feature = body.get("feature", "").strip()
        max_count = body.get("max_count")
        reason = body.get("reason", "")

        user = User.objects.filter(user_id=user_id).first()
        if user is None:
            return fail({"error": "用户不存在"})

        valid_features = [k for k, _ in FEATURE_CHOICES]
        if feature not in valid_features:
            return fail({"error": f"feature 无效，可选值：{valid_features}"})
        if max_count is None or not isinstance(max_count, int):
            return fail({"error": "max_count 必须为整数"})

        override, _ = UserAccessQuotaOverride.objects.update_or_create(
            user=user,
            feature=feature,
            defaults={
                "max_count": max_count,
                "reason": reason,
                "updated_by": admin.admin_name,
            },
        )
        return ok({"override": override.to_dict()})

    return fail({"error": "不支持的请求方法"})


@authenticate_admin
@require_http_methods(["DELETE"])
def override_delete(request, admin: Admin, override_id: int):
    """DELETE /api/manage/access-frequency/user-overrides/<override_id>"""
    override = UserAccessQuotaOverride.objects.filter(pk=override_id).first()
    if override is None:
        return fail({"error": "覆盖记录不存在"})
    override.delete()
    return ok({"message": "覆盖记录已删除，该用户将恢复适用全局规则"})


# ══════════════════════════════════════════════════════════════════════
# 统计查询
# ══════════════════════════════════════════════════════════════════════


@authenticate_admin
@require_http_methods(["GET"])
def global_stats(request, _: Admin):
    """
    GET /api/manage/access-frequency/stats
    返回各功能今日的总调用次数、放行次数、被拒次数，以及当前启用规则数量。
    """
    today_start = _get_window_start("daily")
    features = [k for k, _ in FEATURE_CHOICES]

    today_data = {}
    for feature in features:
        logs = FeatureAccessLog.objects.filter(
            feature=feature, accessed_at__gte=today_start
        )
        total = logs.count()
        allowed = logs.filter(status=FeatureAccessLog.STATUS_ALLOWED).count()
        rejected = logs.filter(status=FeatureAccessLog.STATUS_REJECTED).count()
        today_data[feature] = {"total": total, "allowed": allowed, "rejected": rejected}

    active_rules = AccessFrequencyRule.objects.filter(is_enabled=True).count()
    override_count = UserAccessQuotaOverride.objects.count()

    return ok(
        {
            "today": today_data,
            "active_rules": active_rules,
            "override_count": override_count,
        }
    )


@authenticate_admin
@require_http_methods(["GET"])
def user_stats_ranking(request, _: Admin):
    """
    GET /api/manage/access-frequency/stats/users
    查询用户访问频次排行（按今日放行次数降序）。
    支持查询参数：feature、date（YYYY-MM-DD，不传默认今日）、top_n（默认20）
    """
    feature = request.GET.get("feature")
    date_str = request.GET.get("date")
    top_n = int(request.GET.get("top_n", 20))

    if date_str:
        try:
            from django.utils.dateparse import parse_date

            d = parse_date(date_str)
            if d is None:
                raise ValueError
            day_start = timezone.make_aware(
                timezone.datetime(d.year, d.month, d.day, 0, 0, 0)
            )
            day_end = timezone.make_aware(
                timezone.datetime(d.year, d.month, d.day, 23, 59, 59)
            )
        except (ValueError, TypeError):
            return fail({"error": "date 格式无效，应为 YYYY-MM-DD"})
    else:
        day_start = _get_window_start("daily")
        day_end = timezone.now()

    qs = FeatureAccessLog.objects.filter(
        status=FeatureAccessLog.STATUS_ALLOWED,
        accessed_at__gte=day_start,
        accessed_at__lte=day_end,
    )
    if feature:
        qs = qs.filter(feature=feature)

    ranking = (
        qs.values("user__user_id", "user__username", "feature")
        .annotate(count=Count("pk"))
        .order_by("-count")[:top_n]
    )

    items = [
        {
            "user_id": str(r["user__user_id"]),
            "username": r["user__username"],
            "feature": r["feature"],
            "count": r["count"],
        }
        for r in ranking
    ]
    return ok({"items": items})


@authenticate_admin
@require_http_methods(["GET"])
def user_stats_detail(request, _: Admin, user_id: str):
    """
    GET /api/manage/access-frequency/stats/users/<user_id>
    查询特定用户对所有受限功能的当前周期用量（含剩余次数）。
    """
    user = User.objects.filter(user_id=user_id).first()
    if user is None:
        return fail({"error": "用户不存在"})

    from business.utils.rate_limit import get_user_feature_usage

    features = [k for k, _ in FEATURE_CHOICES]
    feature_stats = [get_user_feature_usage(user, f) for f in features]

    return ok(
        {
            "user_id": str(user.user_id),
            "username": user.username,
            "features": feature_stats,
        }
    )
