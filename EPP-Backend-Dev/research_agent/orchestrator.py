"""
Mock 编排：推进 perceive → decide → act → observe，进入 waiting_user，经干预后继续至 completed。
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .models import AgentTask, ResearchMessage, ResearchSession
from .tool_executor import allowed_get

ACTIVE_STATUSES = frozenset({"pending", "running", "waiting_user"})


def _mock_sleep() -> None:
    time.sleep(getattr(settings, "RESEARCH_AGENT_MOCK_DELAY", 0.08))

ROUND1_STEPS = [
    ("perceive", "感知环境", "Mock: 配额正常"),
    ("decide", "决策规划", "Mock: 已选择检索策略"),
    ("act", "执行动作", "Mock: 调用检索接口（模拟）"),
    ("observe", "观测结果", "Mock: 获得候选文献列表"),
]

ROUND2_STEPS = [
    ("perceive", "再次感知", "Mock: 确认用户意图"),
    ("decide", "生成摘要", "Mock: 汇总要点"),
    ("act", "撰写报告", None),
    ("observe", "校验输出", "Mock: 格式检查通过"),
]


def _act_step_detail_and_error() -> tuple[str, dict[str, str] | None]:
    """第二段 act：可选真实出站 GET（RA_OUTBOUND_DEMO_URL）；否则保持 Mock 文案。"""
    url = (getattr(settings, "RA_OUTBOUND_DEMO_URL", "") or "").strip()
    if not url:
        return ("Mock: 生成 Markdown 成果", None)
    res = allowed_get(url)
    if res.ok:
        return (
            f"出站 GET {url}\n响应摘要：\n{res.summary}",
            None,
        )
    detail = f"出站 GET 失败：{res.error_code} — {res.error_message}"
    return (
        detail,
        {"code": res.error_code, "message": res.error_message},
    )


def _iso_ts(dt: datetime | None = None) -> str:
    if dt is None:
        dt = timezone.now()
    if timezone.is_naive(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_step(task: AgentTask, phase: str, title: str, detail: str) -> None:
    task.step_seq += 1
    step = {
        "seq": task.step_seq,
        "phase": phase,
        "title": title,
        "detail": detail,
        "ts": _iso_ts(),
    }
    steps = list(task.steps or [])
    steps.append(step)
    task.steps = steps


def _task_for_update(task_id: uuid.UUID):
    """SQLite 上与后台线程并发时 select_for_update 易锁表，故开发/测试库跳过行锁。"""
    qs = AgentTask.objects.filter(id=task_id)
    if connection.vendor != "sqlite":
        qs = qs.select_for_update()
    return qs.get()


def _intervention_payload(task_id: uuid.UUID) -> dict[str, Any]:
    short = str(task_id).split("-")[0]
    return {
        "id": f"intv-{short}",
        "reason_code": "external_link",
        "summary": "即将访问域名 example.org 的路径 /papers 以拉取补充摘要",
        "risk_hint": "非白名单域名需确认",
        "estimated_cost": None,
        "timeout_sec": 300,
    }


def execute_first_segment(task_id: uuid.UUID) -> None:
    """第一轮步骤，结束于 waiting_user + intervention。"""
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status != "pending":
                return
            task.status = "running"
            task.save(update_fields=["status", "updated_at"])

        for phase, title, detail in ROUND1_STEPS:
            _mock_sleep()
            with transaction.atomic():
                task = _task_for_update(task_id)
                if task.status not in ("running", "pending"):
                    return
                _append_step(task, phase, title, detail)
                task.save(update_fields=["step_seq", "steps", "updated_at"])

        _mock_sleep()
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status != "running":
                return
            task.status = "waiting_user"
            task.intervention = _intervention_payload(task.id)
            task.save(
                update_fields=["status", "intervention", "step_seq", "steps", "updated_at"]
            )
    finally:
        close_old_connections()


def execute_after_approve(task_id: uuid.UUID) -> None:
    """用户允许后继续，直至 completed（或出站 GET 失败时 failed）。"""
    close_old_connections()
    try:
        for phase, title, detail_default in ROUND2_STEPS:
            _mock_sleep()
            if phase == "act":
                detail, fatal = _act_step_detail_and_error()
            else:
                detail = detail_default
                fatal = None

            with transaction.atomic():
                task = _task_for_update(task_id)
                if task.status != "running":
                    return
                _append_step(task, phase, title, detail)
                if fatal:
                    task.status = "failed"
                    task.error_code = fatal["code"]
                    task.error_message = fatal["message"]
                    task.intervention = None
                    task.save(
                        update_fields=[
                            "status",
                            "error_code",
                            "error_message",
                            "intervention",
                            "step_seq",
                            "steps",
                            "updated_at",
                        ]
                    )
                    return
                task.save(update_fields=["step_seq", "steps", "updated_at"])

        _mock_sleep()
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status != "running":
                return
            task.status = "completed"
            task.intervention = None
            task.result_payload = {
                "format": "markdown",
                "body": "# 调研摘要\n\n（Mock）已完成文献调研与要点汇总。\n\n- 主题相关度：高\n- 建议后续：精读 Top-3 论文。\n",
            }
            task.save(
                update_fields=[
                    "status",
                    "intervention",
                    "result_payload",
                    "step_seq",
                    "steps",
                    "updated_at",
                ]
            )

        session = ResearchSession.objects.get(id=task.session_id)
        ResearchMessage.objects.create(
            session=session,
            role="assistant",
            content="任务已完成，请在主区查看 Markdown 成果。",
        )
        ResearchSession.objects.filter(pk=session.pk).update(
            updated_at=timezone.now()
        )
    finally:
        close_old_connections()


def execute_after_revise(task_id: uuid.UUID, message: str) -> None:
    """用户修改指令：简化为短步骤后完成。"""
    close_old_connections()
    try:
        _mock_sleep()
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status != "running":
                return
            _append_step(
                task,
                "decide",
                "按修订指令调整",
                f"已记录修订：{message[:200]}",
            )
            task.save(update_fields=["step_seq", "steps", "updated_at"])

        _mock_sleep()
        with transaction.atomic():
            task = _task_for_update(task_id)
            task.status = "completed"
            task.intervention = None
            task.result_payload = {
                "format": "markdown",
                "body": f"# 按修订后的调研摘要\n\n{message[:500]}\n\n（Mock 已根据修订指令生成。）",
            }
            task.save(
                update_fields=[
                    "status",
                    "intervention",
                    "result_payload",
                    "step_seq",
                    "steps",
                    "updated_at",
                ]
            )

        session = ResearchSession.objects.get(id=task.session_id)
        ResearchMessage.objects.create(
            session=session,
            role="assistant",
            content="已按您的修订完成输出。",
        )
        ResearchSession.objects.filter(pk=session.pk).update(
            updated_at=timezone.now()
        )
    finally:
        close_old_connections()


def start_first_segment_thread(task_id: uuid.UUID) -> None:
    """SQLite 上与 Django 测试/单进程并发访问同一连接会锁表，故同步执行；其他引擎用后台线程。"""
    if connection.vendor == "sqlite":
        execute_first_segment(task_id)
        return

    def _run() -> None:
        execute_first_segment(task_id)

    t = threading.Thread(target=_run, name=f"ra-mock-{task_id}", daemon=True)
    t.start()


def start_after_approve_thread(task_id: uuid.UUID) -> None:
    if connection.vendor == "sqlite":
        execute_after_approve(task_id)
        return

    def _run() -> None:
        execute_after_approve(task_id)

    t = threading.Thread(target=_run, name=f"ra-approve-{task_id}", daemon=True)
    t.start()


def start_after_revise_thread(task_id: uuid.UUID, message: str) -> None:
    if connection.vendor == "sqlite":
        execute_after_revise(task_id, message)
        return

    def _run() -> None:
        execute_after_revise(task_id, message)

    t = threading.Thread(target=_run, name=f"ra-revise-{task_id}", daemon=True)
    t.start()
