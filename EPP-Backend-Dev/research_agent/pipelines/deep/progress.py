"""深度研究任务进度（保守估计：反思轮次按上限计入分母，仅已完成轮次计入分子）。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from research_agent.models import AgentTask
from research_agent.pipelines.common import runtime_config

from .config import resolve_dr_max_reflect_rounds

PLAN_UNITS = 1
WRITE_UNITS = 1
UNITS_PER_ROUND = 2  # analyze + reflect

_SUBTASK_TITLE_PREFIXES = ("分析子任务：", "反思子任务：")


def persist_dr_progress_plan(
    task: AgentTask,
    subtasks: list[dict[str, object]],
    *,
    max_reflect_rounds: int,
) -> None:
    """规划阶段完成后写入子任务规模，供进度分母使用。"""
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    ids: list[str] = []
    for st in subtasks:
        if not isinstance(st, dict):
            continue
        sid = str(st.get("subtask_id", "")).strip()
        if sid:
            ids.append(sid)
    count = len(ids) if ids else len([st for st in subtasks if isinstance(st, dict)])
    count = max(1, count)
    payload["dr_progress"] = {
        "subtask_count": count,
        "subtask_ids": ids,
        "max_reflect_rounds": max(1, int(max_reflect_rounds)),
    }
    task.result_payload = payload


def _subtask_key_from_step(step: Mapping[str, Any]) -> str:
    title = str(step.get("title") or "")
    for prefix in _SUBTASK_TITLE_PREFIXES:
        if title.startswith(prefix):
            key = title[len(prefix) :].strip()
            if key:
                return key
    detail = str(step.get("detail") or "")
    for line in detail.splitlines():
        line = line.strip()
        if line.startswith("子任务："):
            key = line.replace("子任务：", "", 1).strip()
            if key:
                return key
    return ""


def _distinct_subtask_keys(steps: list[Mapping[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        key = _subtask_key_from_step(step)
        if key:
            keys.add(key)
    return keys


def _completed_reflect_rounds(steps: list[Mapping[str, Any]]) -> dict[str, int]:
    """每个子任务已完整结束的 analyze+reflect 轮次数（以 reflect 步计数）。"""
    counts: dict[str, int] = defaultdict(int)
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("phase") or "").strip() != "reflect":
            continue
        key = _subtask_key_from_step(step)
        if key:
            counts[key] += 1
    return counts


def _has_phase(steps: list[Mapping[str, Any]], phase: str) -> bool:
    token = phase.strip()
    return any(isinstance(s, dict) and str(s.get("phase") or "").strip() == token for s in steps)


def _subtask_count(task: AgentTask, steps: list[Mapping[str, Any]]) -> int:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    drp = payload.get("dr_progress")
    if isinstance(drp, dict):
        try:
            n = int(drp.get("subtask_count") or 0)
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
        ids = drp.get("subtask_ids")
        if isinstance(ids, list) and ids:
            return len(ids)
    keys = _distinct_subtask_keys(steps)
    return max(len(keys), 1)


def _max_reflect_rounds(task: AgentTask) -> int:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    drp = payload.get("dr_progress")
    if isinstance(drp, dict):
        try:
            n = int(drp.get("max_reflect_rounds") or 0)
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
    return resolve_dr_max_reflect_rounds(runtime_config(task))


def deep_research_progress_percent(task: AgentTask) -> int:
    """
    进度 = 已完成工作单元 / 预估最大工作单元。

    分母（偏保守）：plan + write + 子任务数 × 最大反思轮次 × 每轮(analyze+reflect)。
    分子（偏保守）：仅 plan 完成、已结束的 reflect 轮（不含进行中的 analyze）、write 完成。
    """
    steps = [s for s in (task.steps or []) if isinstance(s, dict)]

    if task.status == "completed":
        return 100

    max_rounds = _max_reflect_rounds(task)
    n_subtasks = _subtask_count(task, steps)
    total_units = PLAN_UNITS + n_subtasks * max_rounds * UNITS_PER_ROUND + WRITE_UNITS
    if total_units <= 0:
        return 0

    completed_units = 0
    if _has_phase(steps, "plan_decide"):
        completed_units += PLAN_UNITS

    round_counts = _completed_reflect_rounds(steps)
    for count in round_counts.values():
        completed_units += min(count, max_rounds) * UNITS_PER_ROUND

    if _has_phase(steps, "write"):
        completed_units += WRITE_UNITS

    pct = int(min(99, max(0, (completed_units / total_units) * 100)))

    if task.status in ("failed", "cancelled"):
        return max(1, pct)
    if task.status in ("pending", "running", "pending_action") and completed_units > 0:
        return max(1, pct)
    return pct
