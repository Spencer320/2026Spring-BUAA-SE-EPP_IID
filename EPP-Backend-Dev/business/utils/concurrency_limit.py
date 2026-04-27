"""
并发阈值工具函数

用于 Deep Research 任务创建时的并发判定与排队提升。
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone


def _get_concurrency_limit(user, feature: str) -> tuple[int, int, bool]:
    """
    返回 (max_global_running, max_user_running, rule_enabled)

    语义：
      - -1 表示不限
      - rule_enabled=False 表示不启用并发规则
    """
    from business.models.access_frequency import (
        AccessConcurrencyRule,
        UserAccessConcurrencyOverride,
    )

    rule = AccessConcurrencyRule.objects.filter(feature=feature).first()
    if rule is None or not rule.is_enabled:
        return -1, -1, False

    user_limit = int(rule.max_user_running or -1)
    override = UserAccessConcurrencyOverride.objects.filter(
        user=user, feature=feature
    ).first()
    if override is not None:
        user_limit = int(override.max_user_running or -1)

    global_limit = int(rule.max_global_running or -1)
    return global_limit, user_limit, True


def evaluate_concurrency_for_new_task(user, feature: str = "deep_research") -> dict:
    """
    评估新任务应直接运行还是进入排队。

    返回：
      {
        "should_queue": bool,
        "reason": str,
        "global_running": int,
        "user_running": int,
        "max_global_running": int,
        "max_user_running": int,
        "rule_enabled": bool
      }
    """
    from business.models.deep_research_task import DeepResearchTask

    max_global_running, max_user_running, rule_enabled = _get_concurrency_limit(
        user, feature
    )

    running_qs = DeepResearchTask.objects.filter(status=DeepResearchTask.STATUS_RUNNING)
    global_running = running_qs.count()
    user_running = running_qs.filter(user=user).count()

    reasons: list[str] = []
    should_queue = False

    if max_global_running >= 0 and global_running >= max_global_running:
        should_queue = True
        reasons.append(
            f"全局并发已达上限（{global_running}/{max_global_running}）"
        )
    if max_user_running >= 0 and user_running >= max_user_running:
        should_queue = True
        reasons.append(
            f"个人并发已达上限（{user_running}/{max_user_running}）"
        )

    reason = "；".join(reasons) if reasons else ""
    return {
        "should_queue": should_queue,
        "reason": reason,
        "global_running": global_running,
        "user_running": user_running,
        "max_global_running": max_global_running,
        "max_user_running": max_user_running,
        "rule_enabled": rule_enabled,
    }


def promote_queued_tasks(feature: str = "deep_research", max_promote: int = 20) -> int:
    """
    当并发槽位释放后，将排队任务提升为 running。

    返回本次提升数量。
    """
    from business.models.access_frequency import AccessConcurrencyRule
    from business.models.deep_research_task import DeepResearchTask

    if max_promote <= 0:
        return 0

    rule = AccessConcurrencyRule.objects.filter(feature=feature, is_enabled=True).first()
    if rule is None:
        return 0

    promoted = 0
    now = timezone.now()

    with transaction.atomic():
        running_qs = DeepResearchTask.objects.select_for_update().filter(
            status=DeepResearchTask.STATUS_RUNNING
        )
        queued_qs = (
            DeepResearchTask.objects.select_for_update()
            .filter(status=DeepResearchTask.STATUS_QUEUED)
            .order_by("created_at")
        )

        global_running = running_qs.count()
        max_global_running = int(rule.max_global_running or -1)
        max_user_running_default = int(rule.max_user_running or -1)

        for task in queued_qs:
            if promoted >= max_promote:
                break

            if max_global_running >= 0 and global_running >= max_global_running:
                break

            # 动态读取用户覆盖并发上限
            from business.models.access_frequency import UserAccessConcurrencyOverride

            override = UserAccessConcurrencyOverride.objects.filter(
                user=task.user, feature=feature
            ).first()
            user_limit = (
                int(override.max_user_running or -1)
                if override is not None
                else max_user_running_default
            )
            user_running = running_qs.filter(user=task.user).count()
            if user_limit >= 0 and user_running >= user_limit:
                continue

            task.status = DeepResearchTask.STATUS_RUNNING
            task.started_at = task.started_at or now
            task.current_phase = (
                task.current_phase or DeepResearchTask.PHASE_PLANNING
            )
            task.progress = max(int(task.progress or 0), 1)
            if not str(task.step_summary or "").strip():
                task.step_summary = "并发槽位已释放，任务开始执行"
            task.save(
                update_fields=[
                    "status",
                    "started_at",
                    "current_phase",
                    "progress",
                    "step_summary",
                ]
            )
            promoted += 1
            global_running += 1

    return promoted
