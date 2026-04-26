"""科研助手任务编排引擎：真实 LLM 驱动。"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .llm_client import chat_completion, normalize_supplier_json_response
from .models import AgentTask, ResearchMessage, ResearchSession
from .tool_executor import execute_controlled_local_command, execute_web_search

ACTIVE_STATUSES = frozenset({"pending", "running", "pending_action"})
REPORT_MESSAGE_PREFIX = "[[RA_REPORT]]\n"


PIPELINE_PHASES = ("plan", "search", "read", "reflect", "write")


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


def _render_plan_detail(round_no: int, plan_payload: dict[str, object]) -> str:
    plans = plan_payload.get("plans", [])
    lines = ["正在规划研究任务"]
    if isinstance(plans, list):
        for idx, item in enumerate(plans, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("item", "")).strip()
            if text:
                lines.append(f"检索计划{idx}：{text}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _render_search_detail(
    round_no: int,
    search_payload: dict[str, object],
    search_detail: str,
    search_audit: dict[str, object],
) -> str:
    summary = str(search_payload.get("search_summary", "")).strip()
    query_rewrite = str(search_payload.get("query_rewrite", "")).strip()
    evidence_need = search_payload.get("evidence_need", [])
    lines = ["正在执行检索"]
    if summary:
        lines.append(f"检索策略：{summary}")
    if query_rewrite:
        lines.append(f"检索词：{query_rewrite}")
    if isinstance(evidence_need, list):
        for idx, need in enumerate(evidence_need, start=1):
            text = str(need).strip()
            if text:
                lines.append(f"证据需求{idx}：{text}")
    lines.append(f"检索结果：{search_detail}")
    lines.append(f"工具状态：{str(search_audit.get('status', '')).strip() or 'unknown'}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _render_read_detail(round_no: int, read_payload: dict[str, object]) -> str:
    analysis = str(read_payload.get("analysis", "")).strip()
    key_points = read_payload.get("key_points", [])
    limitations = read_payload.get("limitations", [])
    lines = ["正在阅读与分析证据"]
    if analysis:
        lines.append(f"核心结论：{analysis}")
    if isinstance(key_points, list):
        for idx, point in enumerate(key_points, start=1):
            text = str(point).strip()
            if text:
                lines.append(f"关键要点{idx}：{text}")
    if isinstance(limitations, list):
        for idx, item in enumerate(limitations, start=1):
            text = str(item).strip()
            if text:
                lines.append(f"局限性{idx}：{text}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _render_reflect_detail(round_no: int, reflect_payload: dict[str, object]) -> str:
    needs = str(reflect_payload.get("needs_optimization", "")).strip()
    reason = str(reflect_payload.get("reason", "")).strip()
    suggestions = reflect_payload.get("suggestions", [])
    lines = ["正在反思与校验"]
    lines.append(f"是否继续优化：{'是' if needs == 'yes' else '否'}")
    if reason:
        lines.append(f"裁决原因：{reason}")
    if isinstance(suggestions, list):
        for idx, suggestion in enumerate(suggestions, start=1):
            text = str(suggestion).strip()
            if text:
                lines.append(f"优化建议{idx}：{text}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _render_write_detail(write_payload: dict[str, object], reflect_round: int) -> str:
    title = str(write_payload.get("title", "")).strip() or "研究报告"
    sections = write_payload.get("sections", [])
    lines = ["正在生成研究报告", f"报告标题：{title}"]
    if isinstance(sections, list):
        lines.append(f"章节数量：{len(sections)}")
        for idx, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading", "")).strip()
            if heading:
                lines.append(f"章节{idx}：{heading}")
    lines.append(f"反思轮次：{reflect_round}")
    return "\n".join(lines)


def _render_local_command_detail(round_no: int, audit: dict[str, object]) -> str:
    status = str(audit.get("status", "")).strip() or "unknown"
    detail = str(audit.get("detail", "")).strip()
    meta = audit.get("meta", {})
    lines = ["正在执行本地命令工具", f"执行状态：{status}"]
    if detail:
        lines.append(f"执行说明：{detail}")
    if isinstance(meta, dict):
        template = str(meta.get("template", "")).strip()
        if template:
            lines.append(f"命令模板：{template}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _runtime_config(task: AgentTask) -> dict[str, object]:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        return {}
    return cfg


def _update_runtime_config(task: AgentTask, **updates: object) -> None:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.update(updates)
    payload["runtime_config"] = cfg
    task.result_payload = payload


def _max_reflect_rounds(task: AgentTask) -> int:
    cfg = _runtime_config(task)
    raw = cfg.get("max_reflect_rounds", 2)
    try:
        rounds = int(raw)
    except (TypeError, ValueError):
        rounds = 2
    return max(1, min(5, rounds))


def _latest_user_query(task: AgentTask) -> str:
    msg = (
        ResearchMessage.objects.filter(session=task.session, role="user")
        .order_by("-created_at")
        .first()
    )
    return (msg.content if msg else "").strip() or "未提供研究问题"


def _build_conversation_messages(
    *,
    task: AgentTask,
    system_prompt: str,
    user_prompt: str,
    history_limit: int = 12,
) -> list[dict[str, str]]:
    history = list(
        ResearchMessage.objects.filter(session=task.session)
        .order_by("-created_at")[:history_limit]
    )
    history.reverse()
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = str(msg.role or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(msg.content or "").strip()
        if not content:
            continue
        if content.startswith(REPORT_MESSAGE_PREFIX):
            # 报告正文可能很长，这里保留语义而不回灌整篇。
            content = "上一轮已生成研究报告。"
        messages.append({"role": role, "content": content[:1200]})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _search_context(query: str) -> tuple[str, list[dict[str, str]], dict[str, str] | None, dict[str, object]]:
    url = (getattr(settings, "RA_OUTBOUND_DEMO_URL", "") or "").strip()
    res = execute_web_search(query=query, url=url)
    if not res.ok:
        return (
            f"联网检索失败：{res.error_code} - {res.error_message}",
            [],
            {"code": res.error_code, "message": res.error_message},
            {
                "tool": res.audit.tool,
                "status": res.audit.status,
                "detail": res.audit.detail,
                "meta": res.audit.metadata,
            },
        )
    return (
        res.summary,
        res.citations,
        None,
        {
            "tool": res.audit.tool,
            "status": res.audit.status,
            "detail": res.audit.detail,
            "meta": res.audit.metadata,
        },
    )


def _validate_reflect_json(payload: dict[str, object]) -> tuple[bool, str]:
    needs = payload.get("needs_optimization")
    suggestions = payload.get("suggestions")
    reason = payload.get("reason")
    if needs not in ("yes", "no"):
        return False, "needs_optimization must be yes or no"
    if not isinstance(suggestions, list) or any(
        not isinstance(item, str) for item in suggestions
    ):
        return False, "suggestions must be string list"
    if not isinstance(reason, str) or not reason.strip():
        return False, "reason must be non-empty string"
    if needs == "yes" and not suggestions:
        return False, "suggestions must be non-empty when needs_optimization=yes"
    return True, ""


def _validate_plan_json(payload: dict[str, object]) -> tuple[bool, str]:
    plans = payload.get("plans")
    if not isinstance(plans, list) or not plans:
        return False, "plans must be non-empty list"
    for item in plans:
        if not isinstance(item, dict):
            return False, "plan item must be object"
        if not isinstance(item.get("item"), str) or not str(item.get("item")).strip():
            return False, "plan item.item must be non-empty string"
    return True, ""


def _validate_search_json(payload: dict[str, object]) -> tuple[bool, str]:
    summary = payload.get("search_summary")
    evidence_need = payload.get("evidence_need")
    if not isinstance(summary, str) or not summary.strip():
        return False, "search_summary must be non-empty string"
    if not isinstance(evidence_need, list):
        return False, "evidence_need must be list"
    return True, ""


def _validate_read_json(payload: dict[str, object]) -> tuple[bool, str]:
    analysis = payload.get("analysis")
    key_points = payload.get("key_points")
    limitations = payload.get("limitations")
    if not isinstance(analysis, str) or not analysis.strip():
        return False, "analysis must be non-empty string"
    if not isinstance(key_points, list):
        return False, "key_points must be list"
    if not isinstance(limitations, list):
        return False, "limitations must be list"
    return True, ""


def _validate_write_json(payload: dict[str, object]) -> tuple[bool, str]:
    title = payload.get("title")
    sections = payload.get("sections")
    if not isinstance(title, str) or not title.strip():
        return False, "title must be non-empty string"
    if not isinstance(sections, list) or not sections:
        return False, "sections must be non-empty list"
    for item in sections:
        if not isinstance(item, dict):
            return False, "section must be object"
        if not isinstance(item.get("heading"), str) or not str(item.get("heading")).strip():
            return False, "section heading must be non-empty string"
        if not isinstance(item.get("content"), str) or not str(item.get("content")).strip():
            return False, "section content must be non-empty string"
    return True, ""


def _render_citations(citations: list[dict[str, str]]) -> str:
    if not citations:
        return "- 无可用引用"
    rows: list[str] = []
    for item in citations:
        title = str(item.get("title", "")).strip() or "未命名来源"
        source = str(item.get("source", "")).strip() or "unknown"
        url = str(item.get("url", "")).strip()
        if url:
            rows.append(f"- {title}（来源：{source}，URL：{url}）")
        else:
            rows.append(f"- {title}（来源：{source}）")
    return "\n".join(rows)


def _markdown_from_write_json(payload: dict[str, object]) -> str:
    title = str(payload.get("title", "研究报告")).strip() or "研究报告"
    sections = payload.get("sections", [])
    parts = [f"# {title}"]
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading", "")).strip()
            content = str(section.get("content", "")).strip()
            if not heading or not content:
                continue
            parts.append(f"\n## {heading}\n{content}")
    return "\n".join(parts).strip()


def _llm_call(
    *,
    phase: str,
    task: AgentTask,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1500,
) -> tuple[str | None, dict[str, object] | None]:
    messages = _build_conversation_messages(
        task=task,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    res = chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if not res.ok:
        return None, {
            "code": res.error_code or "LLM_CALL_FAILED",
            "message": res.error_message or "LLM 调用失败",
            "phase": phase,
        }
    usage = res.usage if isinstance(res.usage, dict) else {}
    _update_runtime_config(
        task,
        llm_last_call={
            "phase": phase,
            "model": res.model,
            "latency_ms": res.latency_ms,
            "usage": usage,
        },
    )
    return res.content, None


def _maybe_run_local_command(task: AgentTask, query: str) -> dict[str, object] | None:
    cfg = _runtime_config(task)
    if bool(cfg.get("local_command_executed")):
        return None
    local_cmd = cfg.get("local_command")
    if not isinstance(local_cmd, dict):
        return None
    template = str(local_cmd.get("template", "")).strip()
    if not template:
        return None
    args = local_cmd.get("args", {})
    if not isinstance(args, dict):
        args = {}
    runtime_args = dict(args)
    runtime_args.setdefault("query", query[:200])
    approved_templates_raw = cfg.get("approved_local_command_templates", [])
    approved_templates = (
        set(str(item) for item in approved_templates_raw)
        if isinstance(approved_templates_raw, list)
        else set()
    )
    effective_risk_strategy = str(cfg.get("risk_confirmation_strategy", "on_high_risk"))
    if template in approved_templates:
        effective_risk_strategy = "never"
    result = execute_controlled_local_command(
        template=template,
        args=runtime_args,
        risk_confirmation_strategy=effective_risk_strategy,
    )
    return {
        "ok": result.ok,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "requires_confirmation": result.requires_confirmation,
        "confirmation_payload": result.confirmation_payload,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "audit": {
            "tool": result.audit.tool,
            "status": result.audit.status,
            "detail": result.audit.detail,
            "meta": result.audit.metadata,
        },
    }


def _task_for_update(task_id: uuid.UUID):
    """SQLite 上与后台线程并发时 select_for_update 易锁表，故开发/测试库跳过行锁。"""
    qs = AgentTask.objects.filter(id=task_id)
    if connection.vendor != "sqlite":
        qs = qs.select_for_update()
    return qs.get()


def execute_task_pipeline(task_id: uuid.UUID) -> None:
    """执行真实 LLM 流水线，终态为 completed 或 failed。"""
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status not in ("pending", "running"):
                return
            if task.status == "pending":
                task.status = "running"
                task.save(update_fields=["status", "updated_at"])

        with transaction.atomic():
            task = _task_for_update(task_id)
            query = _latest_user_query(task)
            max_rounds = _max_reflect_rounds(task)

        reflect_round = 1
        optimize_suggestions: list[str] = []
        all_citations: list[dict[str, str]] = []
        plan_text = ""
        analysis_text = ""
        while True:
            with transaction.atomic():
                task = _task_for_update(task_id)
                if task.status != "running":
                    return
                prompt = (
                    f"研究问题：{query}\n"
                    f"当前轮次：{reflect_round}/{max_rounds}\n"
                    f"反思建议：{';'.join(optimize_suggestions) if optimize_suggestions else '无'}\n"
                    "只允许输出 JSON："
                    '{"plans":[{"index":1,"item":"..."}]}。'
                    "禁止问候语、追问提示、解释性前后缀。"
                )
                plan_raw, err = _llm_call(
                    phase="plan",
                    task=task,
                    system_prompt=(
                        "你是科研智能助手。"
                        "必须只输出 JSON 对象，不得输出任何额外自然语言；"
                        "不得包含问候语、客套语、追问提示。"
                    ),
                    user_prompt=prompt,
                    temperature=0.2,
                    max_tokens=600,
                )
                if err:
                    task.status = "failed"
                    task.error_code = str(err["code"])
                    task.error_message = str(err["message"])
                    task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
                    return
                plan_payload, parse_err = normalize_supplier_json_response(plan_raw or "")
                if plan_payload is None:
                    task.status = "failed"
                    task.error_code = "LLM_JSON_INVALID"
                    task.error_message = f"plan阶段JSON无效: {parse_err}"
                    task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
                    return
                ok, err_msg = _validate_plan_json(plan_payload)
                if not ok:
                    task.status = "failed"
                    task.error_code = "LLM_JSON_INVALID"
                    task.error_message = f"plan阶段JSON校验失败: {err_msg}"
                    task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
                    return
                plans = [str(item.get("item", "")).strip() for item in plan_payload.get("plans", []) if isinstance(item, dict)]
                plan_text = "\n".join(f"- {item}" for item in plans if item)
                _append_step(
                    task,
                    "plan",
                    "规划研究任务",
                    _render_plan_detail(reflect_round, plan_payload),
                )
                task.save(update_fields=["step_seq", "steps", "updated_at"])
            search_prompt = (
                f"研究问题：{query}\n"
                f"当前轮次：{reflect_round}/{max_rounds}\n"
                f"计划要点：{plan_text}\n"
                "只允许输出 JSON："
                '{"search_summary":"...","evidence_need":["..."],"query_rewrite":"..."}。'
                "禁止问候语、追问提示、解释性前后缀。"
            )
            search_ai_raw, err = _llm_call(
                phase="search",
                task=task,
                system_prompt=(
                    "你是科研检索规划助手。"
                    "必须只输出 JSON 对象，不得输出额外自然语言；"
                    "禁止问候语、客套语、追问提示。"
                ),
                user_prompt=search_prompt,
                temperature=0.1,
                max_tokens=500,
            )
            if err:
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    task.status = "failed"
                    task.error_code = str(err["code"])
                    task.error_message = str(err["message"])
                    task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
                return
            search_ai_payload, parse_err = normalize_supplier_json_response(search_ai_raw or "")
            if search_ai_payload is None:
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    task.status = "failed"
                    task.error_code = "LLM_JSON_INVALID"
                    task.error_message = f"search阶段JSON无效: {parse_err}"
                    task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
                return
            ok, err_msg = _validate_search_json(search_ai_payload)
            if not ok:
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    task.status = "failed"
                    task.error_code = "LLM_JSON_INVALID"
                    task.error_message = f"search阶段JSON校验失败: {err_msg}"
                    task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
                return
            search_query = str(search_ai_payload.get("query_rewrite", "")).strip() or query
            search_detail, citations, fatal, search_audit = _search_context(search_query)
            with transaction.atomic():
                task = _task_for_update(task_id)
                if task.status != "running":
                    return
                _append_step(
                    task,
                    "search",
                    "执行检索",
                    _render_search_detail(
                        reflect_round,
                        search_ai_payload,
                        search_detail,
                        search_audit,
                    ),
                )
                if fatal:
                    task.status = "failed"
                    task.error_code = fatal["code"]
                    task.error_message = fatal["message"]
                    task.save(
                        update_fields=[
                            "status",
                            "error_code",
                            "error_message",
                            "step_seq",
                            "steps",
                            "updated_at",
                        ]
                    )
                    return
                task.save(update_fields=["step_seq", "steps", "updated_at"])

            local_cmd_result = _maybe_run_local_command(task, query)
            if local_cmd_result:
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    if task.status != "running":
                        return
                    _append_step(
                        task,
                        "search",
                        "执行本地命令工具",
                        _render_local_command_detail(
                            reflect_round,
                            local_cmd_result["audit"],
                        ),
                    )
                    if local_cmd_result["requires_confirmation"]:
                        task.status = "pending_action"
                        task.intervention = local_cmd_result["confirmation_payload"]
                        task.save(
                            update_fields=[
                                "status",
                                "intervention",
                                "step_seq",
                                "steps",
                                "updated_at",
                            ]
                        )
                        return
                    if not local_cmd_result["ok"]:
                        task.status = "failed"
                        task.error_code = local_cmd_result["error_code"]
                        task.error_message = local_cmd_result["error_message"]
                        task.save(
                            update_fields=[
                                "status",
                                "error_code",
                                "error_message",
                                "step_seq",
                                "steps",
                                "updated_at",
                            ]
                        )
                        return
                    _update_runtime_config(task, local_command_executed=True)
                    task.save(
                        update_fields=[
                            "result_payload",
                            "step_seq",
                            "steps",
                            "updated_at",
                        ]
                    )

            all_citations.extend(citations)
            with transaction.atomic():
                task = _task_for_update(task_id)
                if task.status != "running":
                    return
                prompt = (
                    f"研究问题：{query}\n"
                    f"检索摘要：{search_detail}\n"
                    f"引用列表：\n{_render_citations(citations)}\n"
                    "只允许输出 JSON："
                    '{"analysis":"...","key_points":["..."],"limitations":["..."]}。'
                    "禁止问候语、追问提示、解释性前后缀。"
                )
                read_raw, err = _llm_call(
                    phase="read",
                    task=task,
                    system_prompt=(
                        "你是科研阅读分析助手。"
                        "必须只输出 JSON 对象，不得输出额外自然语言；"
                        "禁止问候语、客套语、追问提示。"
                    ),
                    user_prompt=prompt,
                    temperature=0.2,
                    max_tokens=700,
                )
                if err:
                    task.status = "failed"
                    task.error_code = str(err["code"])
                    task.error_message = str(err["message"])
                    task.save(
                        update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                    )
                    return
                read_payload, parse_err = normalize_supplier_json_response(read_raw or "")
                if read_payload is None:
                    task.status = "failed"
                    task.error_code = "LLM_JSON_INVALID"
                    task.error_message = f"read阶段JSON无效: {parse_err}"
                    task.save(
                        update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                    )
                    return
                ok, err_msg = _validate_read_json(read_payload)
                if not ok:
                    task.status = "failed"
                    task.error_code = "LLM_JSON_INVALID"
                    task.error_message = f"read阶段JSON校验失败: {err_msg}"
                    task.save(
                        update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                    )
                    return
                analysis_text = str(read_payload.get("analysis", "")).strip()
                _append_step(
                    task,
                    "read",
                    "阅读证据",
                    _render_read_detail(reflect_round, read_payload),
                )
                task.save(update_fields=["step_seq", "steps", "updated_at"])
            with transaction.atomic():
                task = _task_for_update(task_id)
                if task.status != "running":
                    return
                reflect_prompt = (
                    f"研究问题：{query}\n"
                    f"本轮规划：{plan_text}\n"
                    f"本轮阅读分析：{analysis_text}\n"
                    f"累计引用数量：{len(all_citations)}\n"
                    f"当前轮次：{reflect_round}/{max_rounds}\n"
                    "请仅输出严格 JSON，不要任何额外文本。"
                    '格式: {"needs_optimization":"yes|no","suggestions":["..."],"reason":"..."}。'
                    "当需要继续优化时，suggestions 至少给 1 条可执行建议。"
                    "禁止问候语、追问提示、解释性前后缀。"
                )
                reflect_raw, err = _llm_call(
                    phase="reflect",
                    task=task,
                    system_prompt=(
                        "你是科研反思裁决器。"
                        "输出必须是合法 JSON 对象，禁止任何额外自然语言；"
                        "禁止问候语、客套语、追问提示。"
                    ),
                    user_prompt=reflect_prompt,
                    temperature=0.1,
                    max_tokens=500,
                )
                if err:
                    task.status = "failed"
                    task.error_code = str(err["code"])
                    task.error_message = str(err["message"])
                    task.save(
                        update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                    )
                    return
                try:
                    reflect_payload = json.loads(reflect_raw)
                except json.JSONDecodeError:
                    task.status = "failed"
                    task.error_code = "LLM_JSON_INVALID"
                    task.error_message = f"反思阶段 JSON 解析失败: {reflect_raw[:300]}"
                    task.save(
                        update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                    )
                    return
                ok, err_msg = _validate_reflect_json(reflect_payload)
                _append_step(
                    task,
                    "reflect",
                    "反思与校验",
                    _render_reflect_detail(reflect_round, reflect_payload),
                )
                if not ok:
                    task.status = "failed"
                    task.error_code = "LLM_JSON_INVALID"
                    task.error_message = err_msg
                    task.save(
                        update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                    )
                    return
                task.save(update_fields=["step_seq", "steps", "updated_at"])

            if reflect_payload["needs_optimization"] == "yes" and reflect_round < max_rounds:
                optimize_suggestions = list(reflect_payload["suggestions"])  # 回灌下一轮
                reflect_round += 1
                continue
            break

        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status != "running":
                return
            write_prompt = (
                f"研究问题：{query}\n"
                f"最终研究计划：{plan_text}\n"
                f"最终阅读分析：{analysis_text}\n"
                f"最终引用：\n{_render_citations(all_citations)}\n"
                "只允许输出 JSON："
                '{"title":"...","sections":[{"heading":"...","content":"..."}],"citations":[...]}。'
                "禁止问候语、追问提示、解释性前后缀。"
            )
            write_raw, err = _llm_call(
                phase="write",
                task=task,
                system_prompt=(
                    "你是科研写作助手。"
                    "必须只输出 JSON 对象，不得输出额外自然语言；"
                    "禁止问候语、客套语、追问提示。"
                ),
                user_prompt=write_prompt,
                temperature=0.2,
                max_tokens=2000,
            )
            if err:
                task.status = "failed"
                task.error_code = str(err["code"])
                task.error_message = str(err["message"])
                task.save(
                    update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                )
                return
            write_payload, parse_err = normalize_supplier_json_response(write_raw or "")
            if write_payload is None:
                task.status = "failed"
                task.error_code = "LLM_JSON_INVALID"
                task.error_message = f"write阶段JSON无效: {parse_err}"
                task.save(
                    update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                )
                return
            ok, err_msg = _validate_write_json(write_payload)
            if not ok:
                task.status = "failed"
                task.error_code = "LLM_JSON_INVALID"
                task.error_message = f"write阶段JSON校验失败: {err_msg}"
                task.save(
                    update_fields=["status", "error_code", "error_message", "step_seq", "steps", "updated_at"]
                )
                return
            report_body = _markdown_from_write_json(write_payload)
            _append_step(task, "write", "生成报告", _render_write_detail(write_payload, reflect_round))
            task.status = "completed"
            task.intervention = None
            task.result_payload = {
                "format": "markdown",
                "body": report_body,
                "citations": all_citations,
                "attachments": [],
                "pipeline": list(PIPELINE_PHASES),
                "reflect_rounds": reflect_round,
                "applied_suggestions": optimize_suggestions,
                "runtime_config": _runtime_config(task),
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
            content=f"{REPORT_MESSAGE_PREFIX}{report_body}",
        )
        ResearchSession.objects.filter(pk=session.pk).update(updated_at=timezone.now())
    finally:
        close_old_connections()


def execute_after_approve(task_id: uuid.UUID) -> None:
    """兼容旧接口：approve 后直接执行完整流水线。"""
    close_old_connections()
    try:
        execute_task_pipeline(task_id)
    finally:
        close_old_connections()


def execute_after_revise(task_id: uuid.UUID, message: str) -> None:
    """兼容旧接口：记录修订并继续执行完整流水线。"""
    close_old_connections()
    try:
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
        execute_task_pipeline(task_id)
    finally:
        close_old_connections()


def execute_first_segment(task_id: uuid.UUID) -> None:
    """兼容旧测试入口：直接执行完整流水线。"""
    execute_task_pipeline(task_id)


def start_first_segment_thread(task_id: uuid.UUID) -> None:
    """启动任务主流水线。"""
    if connection.vendor == "sqlite":
        execute_task_pipeline(task_id)
        return

    def _run() -> None:
        execute_task_pipeline(task_id)

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
