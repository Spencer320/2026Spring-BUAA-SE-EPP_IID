"""
Deep Research 模块接口

本文件包含两部分：

【用户端接口】（路由前缀 /api/deep-research/）
  由 DR 主模块开发者负责填充具体业务逻辑。
  当前以 TODO stub 形式存在，确保路由可注册、管理端可立即联调。

【管理端接口】（路由前缀 /api/manage/deep-research/）
  已完整实现，供管理员实时监控与干预 DR 任务。

管理端接口列表：
  GET    /api/manage/deep-research/stats
  GET    /api/manage/deep-research/tasks
  GET    /api/manage/deep-research/tasks/<task_id>
  GET    /api/manage/deep-research/tasks/<task_id>/trace
  POST   /api/manage/deep-research/tasks/<task_id>/force-stop
  POST   /api/manage/deep-research/tasks/<task_id>/suppress-output
  POST   /api/manage/deep-research/tasks/<task_id>/unsuppress-output
  GET    /api/manage/deep-research/tasks/<task_id>/audit-logs
  GET    /api/manage/deep-research/audit-logs
"""

import json

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q, Sum
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from business.models import Admin, User
from business.models.deep_research_task import (
    DeepResearchAuditLog,
    DeepResearchStep,
    DeepResearchTask,
)
from business.utils.authenticate import authenticate_admin, authenticate_user
from business.utils.response import fail, ok


# ══════════════════════════════════════════════════════════════════════
# 用户端接口（TODO stubs）
# 由 DR 主模块开发者实现；此处仅确保路由可注册并返回占位响应。
# 详细对接说明见 Deep-Research-对接说明.md
# ══════════════════════════════════════════════════════════════════════


@authenticate_user
@require_http_methods(["POST"])
def user_create_task(request, user: User):
    """
    POST /api/deep-research/tasks
    创建 Deep Research 任务。
    TODO: 由 DR 主模块开发者实现编排器启动逻辑。

    需调用 check_rate_limit(user, "deep_research") 进行限频检查，
    详见 Deep-Research-对接说明.md § 2.1
    """
    return fail({"error": "Deep Research 主模块尚未实现，敬请期待"})


@authenticate_user
@require_http_methods(["GET"])
def user_task_status(request, user: User, task_id: str):
    """
    GET /api/deep-research/tasks/<task_id>/status
    轮询任务状态。
    TODO: 由 DR 主模块开发者实现。
    """
    task = DeepResearchTask.objects.filter(task_id=task_id, user=user).first()
    if task is None:
        return fail({"error": "任务不存在"})
    return ok(task.to_user_status_dict())


@authenticate_user
@require_http_methods(["GET"])
def user_task_events(request, user: User, task_id: str):
    """
    GET /api/deep-research/tasks/<task_id>/events?since_seq=<n>
    增量获取执行步骤（可选）。
    TODO: 由 DR 主模块开发者实现。
    """
    task = DeepResearchTask.objects.filter(task_id=task_id, user=user).first()
    if task is None:
        return fail({"error": "任务不存在"})
    since_seq = int(request.GET.get("since_seq", 0))
    steps = task.steps.filter(seq__gt=since_seq)
    return ok({"steps": [s.to_dict() for s in steps]})


@authenticate_user
@require_http_methods(["GET"])
def user_task_report(request, user: User, task_id: str):
    """
    GET /api/deep-research/tasks/<task_id>/report
    获取终态报告。
    """
    task = DeepResearchTask.objects.filter(task_id=task_id, user=user).first()
    if task is None:
        return fail({"error": "任务不存在"})

    if task.output_suppressed:
        return fail({"error": "该报告因合规原因暂时不可访问，如有疑问请联系管理员"})

    if task.status != DeepResearchTask.STATUS_COMPLETED:
        return fail({"error": f"任务尚未完成，当前状态：{task.status}"})

    return ok(
        {
            "task_id": str(task.task_id),
            "report": task.report,
            "citation_coverage": task.citation_coverage,
            "token_used_total": task.token_used_total,
        }
    )


@authenticate_user
@require_http_methods(["POST"])
def user_abort_task(request, user: User, task_id: str):
    """
    POST /api/deep-research/tasks/<task_id>/abort
    用户主动中止任务。
    TODO: 由 DR 主模块开发者补充编排器协作逻辑。
    """
    task = DeepResearchTask.objects.filter(task_id=task_id, user=user).first()
    if task is None:
        return fail({"error": "任务不存在"})
    if task.status not in DeepResearchTask.ACTIVE_STATUSES:
        return fail({"error": f"任务当前状态（{task.status}）不可中止"})

    task.status = DeepResearchTask.STATUS_ABORTED
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "finished_at"])
    return ok({"message": "中止请求已提交"})


@authenticate_user
@require_http_methods(["POST"])
def user_follow_up(request, user: User, task_id: str):
    """
    POST /api/deep-research/tasks/<task_id>/follow-up
    追问或局部重生成。
    TODO: 由 DR 主模块开发者实现。
    """
    return fail({"error": "Deep Research 主模块尚未实现，敬请期待"})


@authenticate_user
@require_http_methods(["POST"])
def user_export_tasks(request, user: User):
    """
    POST /api/deep-research/tasks/export
    批量导出报告（MD/PDF/ZIP）。
    TODO: 由 DR 主模块开发者实现。
    """
    return fail({"error": "Deep Research 主模块尚未实现，敬请期待"})


# ══════════════════════════════════════════════════════════════════════
# 管理端接口（已完整实现）
# ══════════════════════════════════════════════════════════════════════


@authenticate_admin
@require_http_methods(["GET"])
def admin_stats(request, _: Admin):
    """
    GET /api/manage/deep-research/stats
    返回全局统计摘要：运行中/排队任务数、今日各状态数量、Token 消耗总量、屏蔽数。
    """
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_qs = DeepResearchTask.objects.filter(created_at__gte=today_start)

    running_count = DeepResearchTask.objects.filter(
        status=DeepResearchTask.STATUS_RUNNING
    ).count()
    queued_count = DeepResearchTask.objects.filter(
        status=DeepResearchTask.STATUS_QUEUED
    ).count()

    today_token_agg = today_qs.aggregate(total=Sum("token_used_total"))
    today_token_total = today_token_agg["total"] or 0

    return ok(
        {
            "running_count": running_count,
            "queued_count": queued_count,
            "today_total": today_qs.count(),
            "today_completed": today_qs.filter(
                status=DeepResearchTask.STATUS_COMPLETED
            ).count(),
            "today_failed": today_qs.filter(
                status=DeepResearchTask.STATUS_FAILED
            ).count(),
            "today_aborted": today_qs.filter(
                status=DeepResearchTask.STATUS_ABORTED
            ).count(),
            "today_admin_stopped": today_qs.filter(
                status=DeepResearchTask.STATUS_ADMIN_STOPPED
            ).count(),
            "today_token_total": today_token_total,
            "suppressed_count": DeepResearchTask.objects.filter(
                output_suppressed=True
            ).count(),
        }
    )


@authenticate_admin
@require_http_methods(["GET"])
def admin_task_list(request, _: Admin):
    """
    GET /api/manage/deep-research/tasks
    分页查询所有任务，支持多条件筛选。

    查询参数：
      status      任务状态，逗号分隔多值，如 running,queued
      user_id     用户 UUID
      date_from   创建时间起始 YYYY-MM-DD
      date_to     创建时间截止 YYYY-MM-DD
      keyword     按研究问题关键词搜索（query 字段模糊匹配）
      page_num    页码，默认 1
      page_size   每页数量，默认 20
    """
    qs = DeepResearchTask.objects.select_related("user").all()

    # ── 过滤条件 ──────────────────────────────────────────────────────
    status_raw = request.GET.get("status", "").strip()
    if status_raw:
        statuses = [s.strip() for s in status_raw.split(",") if s.strip()]
        qs = qs.filter(status__in=statuses)

    user_id = request.GET.get("user_id", "").strip()
    if user_id:
        qs = qs.filter(user__user_id=user_id)

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    if date_from:
        try:
            from django.utils.dateparse import parse_date

            d = parse_date(date_from)
            qs = qs.filter(created_at__date__gte=d)
        except (ValueError, TypeError):
            return fail({"error": "date_from 格式无效"})
    if date_to:
        try:
            from django.utils.dateparse import parse_date

            d = parse_date(date_to)
            qs = qs.filter(created_at__date__lte=d)
        except (ValueError, TypeError):
            return fail({"error": "date_to 格式无效"})

    keyword = request.GET.get("keyword", "").strip()
    if keyword:
        qs = qs.filter(query__icontains=keyword)

    qs = qs.order_by("-created_at")

    # ── 分页 ──────────────────────────────────────────────────────────
    page_num = int(request.GET.get("page_num", 1))
    page_size = int(request.GET.get("page_size", 20))
    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_num)
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    return ok(
        {
            "total": paginator.count,
            "page_num": page_num,
            "page_size": page_size,
            "items": [t.to_list_dict() for t in page.object_list],
        }
    )


@authenticate_admin
@require_http_methods(["GET"])
def admin_task_detail(request, _: Admin, task_id: str):
    """GET /api/manage/deep-research/tasks/<task_id>"""
    task = DeepResearchTask.objects.select_related("user").filter(task_id=task_id).first()
    if task is None:
        return fail({"error": "任务不存在"})
    return ok({"task": task.to_detail_dict()})


@authenticate_admin
@require_http_methods(["GET"])
def admin_task_trace(request, admin: Admin, task_id: str):
    """
    GET /api/manage/deep-research/tasks/<task_id>/trace
    查看任务执行轨迹（全部步骤）。同时写入 view_trace 审计日志。
    """
    task = DeepResearchTask.objects.filter(task_id=task_id).first()
    if task is None:
        return fail({"error": "任务不存在"})

    steps = task.steps.all()

    # 记录查看轨迹行为（仅在开启审计时写入；可按需关闭）
    DeepResearchAuditLog.objects.create(
        task=task,
        admin=admin,
        action=DeepResearchAuditLog.ACTION_VIEW_TRACE,
        reason="",
    )

    return ok(
        {
            "task_id": str(task.task_id),
            "status": task.status,
            "steps": [s.to_dict() for s in steps],
        }
    )


@authenticate_admin
@require_http_methods(["POST"])
def admin_force_stop(request, admin: Admin, task_id: str):
    """
    POST /api/manage/deep-research/tasks/<task_id>/force-stop
    强制中断任务。

    原理：置 admin_stop_flag=True，编排器下轮检查时安全退出并将 status 改为 admin_stopped。
    本接口立即返回，任务状态由编排器异步更新。
    """
    task = DeepResearchTask.objects.filter(task_id=task_id).first()
    if task is None:
        return fail({"error": "任务不存在"})
    if task.status not in DeepResearchTask.ACTIVE_STATUSES:
        return fail({"error": f"任务当前状态（{task.status}）不支持强制中断"})

    try:
        body = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        body = {}
    reason = str(body.get("reason", ""))

    task.admin_stop_flag = True
    task.save(update_fields=["admin_stop_flag"])

    DeepResearchAuditLog.objects.create(
        task=task,
        admin=admin,
        action=DeepResearchAuditLog.ACTION_FORCE_STOP,
        reason=reason,
        extra={"task_status_at_action": task.status},
    )

    return ok(
        {
            "message": "强制中断指令已发送，任务将在下一个执行间隙安全停止",
            "task_id": str(task.task_id),
        }
    )


@authenticate_admin
@require_http_methods(["POST"])
def admin_suppress_output(request, admin: Admin, task_id: str):
    """
    POST /api/manage/deep-research/tasks/<task_id>/suppress-output
    屏蔽任务报告输出。屏蔽后用户端获取报告接口返回 403。
    """
    task = DeepResearchTask.objects.filter(task_id=task_id).first()
    if task is None:
        return fail({"error": "任务不存在"})
    if task.output_suppressed:
        return fail({"error": "该任务报告已处于屏蔽状态"})

    try:
        body = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        body = {}
    reason = str(body.get("reason", ""))

    task.output_suppressed = True
    task.save(update_fields=["output_suppressed"])

    DeepResearchAuditLog.objects.create(
        task=task,
        admin=admin,
        action=DeepResearchAuditLog.ACTION_SUPPRESS,
        reason=reason,
    )

    return ok({"message": "报告已屏蔽，用户端将无法获取该报告内容"})


@authenticate_admin
@require_http_methods(["POST"])
def admin_unsuppress_output(request, admin: Admin, task_id: str):
    """
    POST /api/manage/deep-research/tasks/<task_id>/unsuppress-output
    恢复任务报告输出。
    """
    task = DeepResearchTask.objects.filter(task_id=task_id).first()
    if task is None:
        return fail({"error": "任务不存在"})
    if not task.output_suppressed:
        return fail({"error": "该任务报告未处于屏蔽状态"})

    try:
        body = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        body = {}
    reason = str(body.get("reason", ""))

    task.output_suppressed = False
    task.save(update_fields=["output_suppressed"])

    DeepResearchAuditLog.objects.create(
        task=task,
        admin=admin,
        action=DeepResearchAuditLog.ACTION_UNSUPPRESS,
        reason=reason,
    )

    return ok({"message": "报告屏蔽已解除，用户端可正常访问"})


@authenticate_admin
@require_http_methods(["GET"])
def admin_task_audit_logs(request, _: Admin, task_id: str):
    """GET /api/manage/deep-research/tasks/<task_id>/audit-logs"""
    task = DeepResearchTask.objects.filter(task_id=task_id).first()
    if task is None:
        return fail({"error": "任务不存在"})

    logs = task.audit_logs.select_related("admin").order_by("-created_at")
    return ok({"logs": [log.to_dict() for log in logs]})


@authenticate_admin
@require_http_methods(["GET"])
def admin_global_audit_logs(request, _: Admin):
    """
    GET /api/manage/deep-research/audit-logs
    全局审计日志，支持按 admin_id、action、日期筛选，分页返回。
    """
    qs = DeepResearchAuditLog.objects.select_related("admin", "task").all()

    admin_id = request.GET.get("admin_id", "").strip()
    if admin_id:
        qs = qs.filter(admin__admin_id=admin_id)

    action = request.GET.get("action", "").strip()
    if action:
        qs = qs.filter(action=action)

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    if date_from:
        try:
            from django.utils.dateparse import parse_date

            qs = qs.filter(created_at__date__gte=parse_date(date_from))
        except (ValueError, TypeError):
            return fail({"error": "date_from 格式无效"})
    if date_to:
        try:
            from django.utils.dateparse import parse_date

            qs = qs.filter(created_at__date__lte=parse_date(date_to))
        except (ValueError, TypeError):
            return fail({"error": "date_to 格式无效"})

    qs = qs.order_by("-created_at")

    page_num = int(request.GET.get("page_num", 1))
    page_size = int(request.GET.get("page_size", 30))
    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        page = paginator.page(1)

    return ok(
        {
            "total": paginator.count,
            "page_num": page_num,
            "page_size": page_size,
            "logs": [log.to_dict() for log in page.object_list],
        }
    )
