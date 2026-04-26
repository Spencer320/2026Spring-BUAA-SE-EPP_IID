import hashlib
import json
import logging
import threading
from typing import Any

from django.db import close_old_connections, transaction
from django.utils import timezone

from business.models.deep_research_task import (
    DeepResearchAuditLog,
    DeepResearchStep,
    DeepResearchTask,
)
from business.utils.text_censor import text_censor

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {
    DeepResearchTask.STATUS_FAILED,
    DeepResearchTask.STATUS_ABORTED,
    DeepResearchTask.STATUS_ADMIN_STOPPED,
    DeepResearchTask.STATUS_ARCHIVED,
}
_MAX_SCAN_TEXT_LENGTH = 5000


def _extract_violation_reason(scan_result: dict[str, Any]) -> str:
    reasons: list[str] = []
    for item in scan_result.get("data", []):
        if int(item.get("conclusionType", 1) or 1) == 1:
            continue
        msg = str(item.get("msg", "")).strip()
        if msg and msg not in reasons:
            reasons.append(msg)
    if reasons:
        return "; ".join(reasons)
    return str(scan_result.get("conclusion", "命中合规风险")).strip() or "命中合规风险"


def _scan_text(text: str) -> tuple[bool, str, dict[str, Any]]:
    snippet = (text or "").strip()
    if not snippet:
        return False, "", {}

    try:
        result = text_censor(snippet[:_MAX_SCAN_TEXT_LENGTH])
    except Exception as exc:
        logger.warning("deep research compliance scan failed: %s", exc)
        return False, "", {"error": str(exc)}

    conclusion = str(result.get("conclusion", "")).strip()
    conclusion_type = result.get("conclusionType")
    if conclusion_type is not None:
        is_violation = int(conclusion_type or 0) != 1
    else:
        is_violation = conclusion not in {"合规", "pass", "PASS", "safe", "SAFE"}

    if not is_violation:
        return False, "", result
    return True, _extract_violation_reason(result), result


def _mark_violation(
    task_id: str,
    reason: str,
    phase: str,
    source: str,
    previous_status: str | None,
    raw_result: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> None:
    now = timezone.now()
    with transaction.atomic():
        task = DeepResearchTask.objects.select_for_update().filter(task_id=task_id).first()
        if task is None:
            return

        task.violation_count = (task.violation_count or 0) + 1
        task.latest_violation_reason = reason[:512]
        task.latest_violation_phase = (phase or task.current_phase or "")[:16]
        task.latest_violation_source = (source or "")[:32]
        task.latest_violation_at = now

        update_fields = [
            "violation_count",
            "latest_violation_reason",
            "latest_violation_phase",
            "latest_violation_source",
            "latest_violation_at",
        ]

        if task.status not in _TERMINAL_STATUSES:
            task.status = DeepResearchTask.STATUS_VIOLATION_PENDING
            update_fields.append("status")

        task.save(update_fields=update_fields)

        audit_extra = {
            "source": source,
            "phase": phase,
            "previous_status": previous_status,
            "conclusion": raw_result.get("conclusion") if raw_result else None,
            "conclusion_type": raw_result.get("conclusionType") if raw_result else None,
        }
        if extra:
            audit_extra.update(extra)
        DeepResearchAuditLog.objects.create(
            task=task,
            admin=None,
            action=DeepResearchAuditLog.ACTION_AUTO_VIOLATION,
            reason=reason[:512],
            extra=audit_extra,
        )


def _audit_task_text(
    *,
    task_id: str,
    text: str,
    phase: str,
    source: str,
    extra: dict[str, Any] | None = None,
) -> None:
    close_old_connections()
    try:
        is_violation, reason, raw_result = _scan_text(text)
        if not is_violation:
            return
        previous_status = (
            DeepResearchTask.objects.filter(task_id=task_id)
            .values_list("status", flat=True)
            .first()
        )
        _mark_violation(
            task_id=task_id,
            reason=reason,
            phase=phase,
            source=source,
            previous_status=previous_status,
            raw_result=raw_result,
            extra=extra,
        )
    finally:
        close_old_connections()


def _run_async(target, **kwargs):
    threading.Thread(target=target, kwargs=kwargs, daemon=True).start()


def audit_step_async(step_id: int) -> None:
    def _worker(step_pk: int):
        close_old_connections()
        try:
            step = DeepResearchStep.objects.select_related("task").filter(pk=step_pk).first()
            if step is None:
                return
            text = "\n".join([step.action or "", step.summary or ""]).strip()
            if not text:
                return
            _audit_task_text(
                task_id=str(step.task.task_id),
                text=text,
                phase=step.phase,
                source="step_trace",
                extra={"step_seq": step.seq, "action": step.action},
            )
        finally:
            close_old_connections()

    _run_async(_worker, step_pk=step_id)


def audit_report_async(task_id: str, report: Any) -> None:
    report_text = json.dumps(report, ensure_ascii=False, default=str)
    report_hash = hashlib.sha256(report_text.encode("utf-8")).hexdigest()

    updated = (
        DeepResearchTask.objects.filter(task_id=task_id)
        .exclude(report_compliance_hash=report_hash)
        .update(report_compliance_hash=report_hash)
    )
    if updated == 0:
        return

    _run_async(
        _audit_task_text,
        task_id=task_id,
        text=report_text,
        phase=DeepResearchTask.PHASE_WRITING,
        source="final_report",
        extra={"report_hash": report_hash},
    )
