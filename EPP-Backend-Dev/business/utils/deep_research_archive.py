import json
from collections import defaultdict
from typing import Any

from django.db import transaction
from django.utils import timezone

from business.models.deep_research_task import (
    DeepResearchAuditLog,
    DeepResearchStep,
    DeepResearchTask,
    DeepResearchTaskArchive,
)

AUTO_ARCHIVE_TERMINAL_STATUSES = {
    DeepResearchTask.STATUS_COMPLETED,
    DeepResearchTask.STATUS_FAILED,
    DeepResearchTask.STATUS_ABORTED,
    DeepResearchTask.STATUS_ADMIN_STOPPED,
}

_CITATION_KEYS = {
    "citation",
    "citations",
    "reference",
    "references",
    "source",
    "sources",
    "ref",
    "refs",
}
_RETRIEVAL_KEYWORDS = ("检索", "search", "query", "crawl", "爬取")


def _iso_or_none(dt) -> str | None:
    return dt.isoformat() if dt else None


def _append_citation_item(target: list[dict[str, Any]], item: Any) -> None:
    if item is None:
        return
    if isinstance(item, list):
        for sub in item:
            _append_citation_item(target, sub)
        return
    if isinstance(item, dict):
        target.append(item)
        return
    text = str(item).strip()
    if text:
        target.append({"text": text})


def _extract_citation_traces(report_payload: Any) -> list[dict[str, Any]]:
    if report_payload is None:
        return []

    collected: list[dict[str, Any]] = []

    def walk(node: Any):
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).strip().lower() in _CITATION_KEYS:
                    _append_citation_item(collected, value)
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(report_payload)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in collected:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)
    return deduped


def _build_resource_audit_report(
    task: DeepResearchTask, steps: list[DeepResearchStep], terminal_status: str
) -> dict[str, Any]:
    token_by_phase: dict[str, int] = defaultdict(int)
    retrieval_count = 0
    token_from_steps = 0
    for step in steps:
        token = int(step.token_used or 0)
        token_from_steps += token
        token_by_phase[step.phase] += token

        combined_text = f"{step.action} {step.summary}".lower()
        if step.phase == DeepResearchTask.PHASE_SEARCHING or any(
            keyword in combined_text for keyword in _RETRIEVAL_KEYWORDS
        ):
            retrieval_count += 1

    duration_seconds = None
    if task.started_at and task.finished_at:
        duration_seconds = max(
            0, int((task.finished_at - task.started_at).total_seconds())
        )

    return {
        "task_id": str(task.task_id),
        "terminal_status": terminal_status,
        "token_used_total": int(task.token_used_total or 0),
        "token_used_from_steps": token_from_steps,
        "token_by_phase": dict(token_by_phase),
        "retrieval_count": retrieval_count,
        "step_count": len(steps),
        "duration_seconds": duration_seconds,
        "max_rounds": task.max_rounds,
        "generated_at": timezone.now().isoformat(),
    }


def _build_lifecycle_snapshot(
    task: DeepResearchTask, steps: list[DeepResearchStep], logs: list[DeepResearchAuditLog]
) -> dict[str, Any]:
    return {
        "task_id": str(task.task_id),
        "user_id": str(task.user.user_id),
        "username": task.user.username,
        "query": task.query,
        "max_rounds": task.max_rounds,
        "status_before_archive": task.status,
        "current_phase": task.current_phase,
        "progress": task.progress,
        "step_summary": task.step_summary,
        "token_used_total": int(task.token_used_total or 0),
        "citation_coverage": task.citation_coverage,
        "output_suppressed": bool(task.output_suppressed),
        "violation_count": int(task.violation_count or 0),
        "latest_violation_reason": task.latest_violation_reason,
        "latest_violation_phase": task.latest_violation_phase,
        "latest_violation_source": task.latest_violation_source,
        "latest_violation_at": _iso_or_none(task.latest_violation_at),
        "error_message": task.error_message,
        "created_at": _iso_or_none(task.created_at),
        "started_at": _iso_or_none(task.started_at),
        "finished_at": _iso_or_none(task.finished_at),
        "steps": [step.to_dict() for step in steps],
        "audit_logs": [log.to_dict() for log in logs],
    }


def archive_task(task_id: str) -> bool:
    """
    对终态任务执行归档。

    返回：
      True  -> 本次执行了归档（含更新）
      False -> 未归档（任务不存在、非终态、已归档、已完成但无报告）
    """
    with transaction.atomic():
        task = (
            DeepResearchTask.objects.select_for_update()
            .select_related("user")
            .filter(task_id=task_id)
            .first()
        )
        if task is None:
            return False
        if task.status == DeepResearchTask.STATUS_ARCHIVED:
            return False
        if task.status not in AUTO_ARCHIVE_TERMINAL_STATUSES:
            return False
        if task.status == DeepResearchTask.STATUS_COMPLETED and task.report is None:
            return False

        terminal_status = task.status
        steps = list(task.steps.all().order_by("seq"))
        logs = list(task.audit_logs.select_related("admin").order_by("created_at"))

        report_payload = task.report
        citation_traces = _extract_citation_traces(report_payload)
        resource_audit_report = _build_resource_audit_report(
            task, steps, terminal_status
        )
        lifecycle_snapshot = _build_lifecycle_snapshot(task, steps, logs)

        DeepResearchTaskArchive.objects.update_or_create(
            task=task,
            defaults={
                "terminal_status": terminal_status,
                "report_payload": report_payload,
                "citation_traces": citation_traces,
                "resource_audit_report": resource_audit_report,
                "lifecycle_snapshot": lifecycle_snapshot,
            },
        )

        update_fields = ["status"]
        task.status = DeepResearchTask.STATUS_ARCHIVED
        if task.finished_at is None:
            task.finished_at = timezone.now()
            update_fields.append("finished_at")
        task.save(update_fields=update_fields)
        return True
