"""科研助手任务编排引擎：真实 LLM 驱动。"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .llm_client import (
    chat_completion,
    iter_json_objects_in_text,
    normalize_supplier_json_response,
    pick_reader_json_payload,
    pick_reflector_json_payload,
    pick_searcher_json_payload,
    pick_write_json_payload,
)
from .models import AgentBehaviorAuditLog, AgentTask, ResearchMessage, ResearchSession
from .prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_DECIDE,
    USER_PROMPT_PLAN,
    USER_PROMPT_READ,
    USER_PROMPT_REFLECT,
    USER_PROMPT_SEARCH,
    USER_PROMPT_WRITE,
    WORKSPACE_CONTENT_SYSTEM_PROMPT,
    WORKSPACE_CONTENT_USER_PROMPT,
)
from .lite_orchestrator import execute_lite_pipeline, is_lite_pipeline
from .smart_planner import detect_smart_plan, fallback_chat_plan
from .tools.router import route_tool_call
from .tools.workspace_executor import inject_workspace_step_args

ACTIVE_STATUSES = frozenset({"pending", "running", "pending_action"})
REPORT_MESSAGE_PREFIX = "[[RA_REPORT]]\n"
PIPELINE_PHASES = ("plan", "decide", "search", "read", "reflect", "write")
WORKSPACE_PIPELINE_PHASES = ("route", "workspace", "write")
logger = logging.getLogger(__name__)


def _progress_log(task: AgentTask, message: str) -> None:
    text = f"[research_agent][task={task.id}][session={task.session_id}] {message}"
    print(text, flush=True)
    logger.info(text)


_STRUCT_JSON_DIAG_PHASES = frozenset({"plan", "decide", "search", "read", "reflect", "write"})


def _raw_snippet_repr(text: str | None, limit: int = 360) -> str:
    """用于日志的诊断片段（repr），避免控制台被超长正文淹没。"""
    return repr((text or "")[:limit])


def _struct_json_diag(task: AgentTask | None, phase: str, *, step: str, **fields: object) -> None:
    """
    结构化阶段 JSON 诊断：帮助区分「首轮抽错 {}」「顶层截断」「思考链占位」等情况。
    日志前缀固定为 [struct_json]，便于在服务输出中 grep。
    """
    if task is None or phase not in _STRUCT_JSON_DIAG_PHASES:
        return
    parts: list[str] = [f"[struct_json] phase={phase} step={step}"]
    for key, val in fields.items():
        if val is None:
            chunk = "null"
        elif isinstance(val, bool):
            chunk = "true" if val else "false"
        elif isinstance(val, (int, float)):
            chunk = str(val)
        elif isinstance(val, (dict, list)):
            try:
                chunk = json.dumps(val, ensure_ascii=False)
            except TypeError:
                chunk = repr(val)
            if len(chunk) > 900:
                chunk = chunk[:900] + "…"
        else:
            chunk = str(val)
            if len(chunk) > 900:
                chunk = chunk[:900] + "…"
        parts.append(f"{key}={chunk}")
    _progress_log(task, " ".join(parts))


def _iso_ts(dt: datetime | None = None) -> str:
    if dt is None:
        dt = timezone.now()
    if timezone.is_naive(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _normalize_audit_status(raw: object, *, is_exception: bool, response_status: int | None) -> str:
    status = str(raw or "").strip().lower()
    mapping = {
        "ok": "succeeded",
        "success": "succeeded",
        "succeeded": "succeeded",
        "error": "failed",
        "failed": "failed",
        "pending_action": "pending_action",
        "pending": "pending_action",
        "allowed": "allowed",
        "rejected": "rejected",
        "blocked": "rejected",
    }
    if status in mapping:
        return mapping[status]
    if is_exception:
        return "failed"
    if response_status is not None and response_status >= 400:
        return "failed"
    return "succeeded"


def _sanitize_actor_type(raw: object, default: str = "system") -> str:
    actor = str(raw or "").strip().lower() or default
    if actor not in {"system", "user", "admin"}:
        actor = default
    return actor


def _compact_rule_hit(raw: object) -> str:
    if isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw if str(item).strip()]
        return ",".join(values)[:255]
    if isinstance(raw, dict):
        try:
            return json.dumps(raw, ensure_ascii=False)[:255]
        except TypeError:
            return str(raw)[:255]
    return str(raw or "").strip()[:255]


def _append_behavior_log(
    task: AgentTask,
    phase: str,
    title: str,
    detail: str,
    audit: dict[str, Any] | None = None,
) -> None:
    payload = audit or {}
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}

    target_url = str(payload.get("target_url", "") or "").strip()
    response_status = payload.get("response_status")
    if response_status is not None:
        try:
            response_status = int(response_status)
        except (TypeError, ValueError):
            response_status = None
    is_exception = bool(payload.get("is_exception", False))
    if response_status is not None and response_status >= 400:
        is_exception = True
    step_id_raw = payload.get("step_id")
    if step_id_raw in (None, ""):
        step_id = int(task.step_seq or 0) or None
    else:
        try:
            step_id = int(step_id_raw)
        except (TypeError, ValueError):
            step_id = int(task.step_seq or 0) or None

    trace_id = str(payload.get("trace_id") or meta.get("trace_id") or "").strip()
    if not trace_id:
        trace_id = f"{task.id}:{step_id or task.step_seq or 0}"

    actor_type = _sanitize_actor_type(payload.get("actor_type"), "system")
    tool_type = str(payload.get("tool_type") or payload.get("tool") or meta.get("tool") or "").strip().lower()
    if not tool_type:
        if phase in {"plan", "decide", "read", "reflect", "write"}:
            tool_type = "llm"
        elif phase == "search":
            tool_type = "tool_router"
        else:
            tool_type = "orchestrator"

    risk_level = str(payload.get("risk_level") or meta.get("risk_level") or "").strip().lower()
    if risk_level not in {"", "low", "medium", "high"}:
        risk_level = ""
    rule_hit = _compact_rule_hit(payload.get("rule_hit") or meta.get("rule_hit"))
    policy_version = str(payload.get("policy_version") or meta.get("policy_version") or "").strip()
    audit_status = _normalize_audit_status(
        payload.get("status"),
        is_exception=is_exception,
        response_status=response_status,
    )

    request_payload = payload.get("request_payload")
    if not isinstance(request_payload, dict):
        request_payload = {}
    if not request_payload and meta:
        request_payload = meta

    action_payload = payload.get("action_payload")
    if not isinstance(action_payload, dict):
        action_payload = {"title": title}
    elif "title" not in action_payload:
        action_payload["title"] = title

    AgentBehaviorAuditLog.objects.create(
        task=task,
        operation_type=str(payload.get("operation_type") or phase),
        target_url=target_url,
        target_domain=str(payload.get("target_domain") or _extract_domain(target_url)),
        request_headers=payload.get("request_headers") or {},
        request_payload=request_payload,
        action_payload=action_payload,
        step_id=step_id,
        trace_id=trace_id,
        actor_type=actor_type,
        tool_type=tool_type,
        risk_level=risk_level,
        rule_hit=rule_hit,
        policy_version=policy_version,
        status=audit_status,
        response_status=response_status,
        is_exception=is_exception,
        exception_message=str(payload.get("exception_message") or ""),
        trace_detail=detail or title,
    )


def _append_step(
    task: AgentTask,
    phase: str,
    title: str,
    detail: str,
    audit: dict[str, Any] | None = None,
) -> None:
    task.step_seq += 1
    steps = list(task.steps or [])
    steps.append(
        {
            "seq": task.step_seq,
            "phase": phase,
            "title": title,
            "detail": detail,
            "ts": _iso_ts(),
        }
    )
    task.steps = steps
    audit_payload = dict(audit) if isinstance(audit, dict) else {}
    audit_payload.setdefault("step_id", task.step_seq)
    _append_behavior_log(task, phase, title, detail, audit=audit_payload)
    _progress_log(task, f"step#{task.step_seq} phase={phase} title={title} detail={detail[:200]}")


def _runtime_config(task: AgentTask) -> dict[str, object]:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    return cfg if isinstance(cfg, dict) else {}


def _update_runtime_config(task: AgentTask, **updates: object) -> None:
    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
    cfg = payload.get("runtime_config", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.update(updates)
    payload["runtime_config"] = cfg
    task.result_payload = payload


def _max_reflect_rounds(task: AgentTask) -> int:
    raw = _runtime_config(task).get("max_reflect_rounds", 2)
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
    history = list(ResearchMessage.objects.filter(session=task.session).order_by("-created_at")[:history_limit])
    history.reverse()
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for msg in history:
        role = str(msg.role or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(msg.content or "").strip()
        if not content:
            continue
        if content.startswith(REPORT_MESSAGE_PREFIX):
            content = "上一轮已生成研究报告。"
        messages.append({"role": role, "content": content[:1200]})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _llm_call(
    *,
    phase: str,
    task: AgentTask,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    enable_thinking: bool = True,
    history_limit: int = 12,
    merge_reasoning_into_content: bool | None = None,
) -> tuple[str | None, dict[str, object] | None]:
    messages = _build_conversation_messages(
        task=task,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        history_limit=history_limit,
    )
    if merge_reasoning_into_content is None:
        # read/reflect/write 只解析最终 JSON：不要把 reasoning 链拼进正文，否则首个 `{...}` 常误抓为 reader 子树
        merge_reasoning_into_content = phase not in {"read", "reflect", "write"}
    base_kwargs: dict[str, Any] = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # 兼容旧签名（测试里的 mock 可能不接受 messages / enable_thinking），逐级降级。
    attempts: list[dict[str, Any]] = [
        {
            **base_kwargs,
            "messages": messages,
            "enable_thinking": enable_thinking,
            "merge_reasoning_into_content": merge_reasoning_into_content,
        },
        {**base_kwargs, "messages": messages, "merge_reasoning_into_content": merge_reasoning_into_content},
        {**base_kwargs, "messages": messages, "enable_thinking": enable_thinking},
        {**base_kwargs, "messages": messages},
        {**base_kwargs, "enable_thinking": enable_thinking},
        {**base_kwargs},
    ]
    last_exc: TypeError | None = None
    res = None
    for kwargs in attempts:
        try:
            res = chat_completion(**kwargs)
            break
        except TypeError as exc:
            msg = str(exc)
            if (
                "messages" in msg
                or "enable_thinking" in msg
                or "merge_reasoning" in msg
                or "unexpected keyword argument" in msg
            ):
                last_exc = exc
                continue
            raise
    if res is None:
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("chat_completion 调用失败但未捕获异常")
    if not res.ok:
        _progress_log(
            task,
            f"LLM 调用失败 phase={phase} code={res.error_code} latency_ms={res.latency_ms} "
            f"thinking={'on' if enable_thinking else 'off'}",
        )
        return None, {
            "code": res.error_code or "LLM_CALL_FAILED",
            "message": res.error_message or "LLM 调用失败",
            "phase": phase,
        }
    _progress_log(
        task,
        f"LLM 调用完成 phase={phase} latency_ms={res.latency_ms} "
        f"thinking={'on' if enable_thinking else 'off'} max_tokens={max_tokens} "
        f"content_chars={len(res.content or '')}",
    )
    _update_runtime_config(
        task,
        llm_last_call={
            "phase": phase,
            "model": res.model,
            "latency_ms": res.latency_ms,
            "usage": res.usage if isinstance(res.usage, dict) else {},
        },
    )
    return res.content, None


def _log_search_json_parse_diag(task: AgentTask | None, raw: str | None, *, reason: str, parse_detail: str = "") -> None:
    """search 阶段 JSON 解析失败时输出可读的原始片段与备选扫描摘要，便于对接供应商字段与模型输出。"""
    if task is None:
        logger.warning(
            "search JSON 解析诊断（无 task 上下文）：%s%s raw_len=%s head=%s",
            reason,
            f" ({parse_detail})" if parse_detail else "",
            len(raw or ""),
            repr((raw or "")[:2048]),
        )
        text = raw or ""
        try:
            cands = list(iter_json_objects_in_text(text))
        except Exception as exc:  # noqa: BLE001 — 诊断路径必须吞掉异常以免掩盖原错误
            logger.warning("search JSON 备选扫描异常: %r", exc)
            return
        for idx, obj in enumerate(cands[:8]):
            ig = obj.get("info_groups")
            logger.warning(
                "search JSON candidate[%s] keys=%s info_groups_type=%s info_groups_repr_head=%s",
                idx,
                list(obj.keys())[:32],
                type(ig).__name__,
                repr(ig)[:600],
            )
        return

    text = raw or ""
    suffix = f" {parse_detail}" if parse_detail else ""
    _progress_log(
        task,
        f"[DEBUG/search_json_parse] {reason}{suffix} raw_len={len(text)} repr_head={repr(text[:2048])}",
    )
    try:
        cands = list(iter_json_objects_in_text(text))
    except Exception as exc:  # noqa: BLE001
        _progress_log(task, f"[DEBUG/search_json_parse] 备选片段扫描异常: {exc!r}")
        return
    _progress_log(task, f"[DEBUG/search_json_parse] 平衡括号解析出的 dict 候选数={len(cands)}（最多列出前 8 个）")
    for idx, obj in enumerate(cands[:8]):
        ig = obj.get("info_groups")
        keys = list(obj.keys())[:32]
        _progress_log(
            task,
            f"[DEBUG/search_json_parse] candidate[{idx}] keys={keys} "
            f"info_groups_type={type(ig).__name__} info_groups_head={repr(ig)[:600]}",
        )


def _normalize_json(
    raw: str,
    phase: str,
    *,
    task: AgentTask | None = None,
) -> tuple[dict[str, object] | None, str | None]:
    raw_s = raw or ""
    frag_obj_n: int | None = None
    if task is not None and phase in {"search", "read", "reflect", "write"}:
        frag_obj_n = sum(1 for _ in iter_json_objects_in_text(raw_s))
    ing: dict[str, Any] = {
        "step": "ingress",
        "raw_len": len(raw_s),
        "raw_head": _raw_snippet_repr(raw_s, 320),
        "first_brace_index": raw_s.find("{"),
    }
    if frag_obj_n is not None:
        ing["fragment_object_count"] = frag_obj_n
    _struct_json_diag(task, phase, **ing)

    payload, parse_err = normalize_supplier_json_response(raw_s)
    top_keys_list: list[str] = []
    fb_initial = False
    if isinstance(payload, dict):
        top_keys_list = [str(k) for k in list(payload.keys())[:32]]
        fb_initial = bool(payload.get("_fallback_wrapped"))
    _struct_json_diag(
        task,
        phase,
        step="after_supplier_normalize",
        payload_is_none=payload is None,
        parse_err_short=str(parse_err or "")[:500],
        fallback_wrapped=fb_initial,
        top_level_keys=top_keys_list,
    )

    if payload is None:
        if phase == "search":
            _log_search_json_parse_diag(task, raw, reason="normalize_supplier_json_response 返回 None", parse_detail=parse_err or "")
        if phase in {"search", "read", "reflect", "write"}:
            _struct_json_diag(
                task,
                phase,
                step="exit_supplier_payload_none",
                parse_err=str(parse_err or "")[:500],
                note="将返回空 dict，由上层 coerce / 摘要兜底",
            )
            if task is not None:
                _progress_log(
                    task,
                    f"[pipeline_coerce] {phase} 供应商返回无可解析正文（{parse_err or 'unknown'}）→置空交由上层兜底",
                )
            return {}, parse_err
        return None, f"{phase}阶段JSON无效: {parse_err}"
    if payload.get("_fallback_wrapped"):
        if phase == "search":
            picked = pick_searcher_json_payload(raw or "")
            if picked is None:
                detail = ""
                fallback_err = payload.get("_fallback_error")
                if isinstance(fallback_err, str) and fallback_err:
                    detail = f"_fallback_error={fallback_err}"
                wrapped_raw = payload.get("raw_text")
                if isinstance(wrapped_raw, str) and wrapped_raw:
                    detail = f"{detail} raw_from_fallback_repr_head={repr(wrapped_raw[:1024])}" if detail else f"raw_from_fallback_repr_head={repr(wrapped_raw[:1024])}"
                _log_search_json_parse_diag(
                    task,
                    raw,
                    reason="首段解析失败且 pick_searcher_json_payload 无可用对象（含备选扫描）",
                    parse_detail=detail,
                )
                if task is not None:
                    _progress_log(task, "[pipeline_coerce] search 片段穷尽→置空，由 minimal_groups 兜底")
                payload = {}
            else:
                payload = picked
        elif phase == "read":
            picked_rd = pick_reader_json_payload(raw or "")
            if picked_rd is None:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] read 片段恢复未果，交由上层按 info_groups/coerce 兜底",
                    )
                payload = {}
            else:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] read 已通过片段扫描恢复 JSON（顶层不完整、截断或与思考链混杂）",
                    )
                payload = picked_rd
        elif phase == "reflect":
            picked_rf = pick_reflector_json_payload(raw or "")
            if picked_rf is None:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] reflect 片段恢复未果，交由上层清空后走阅读摘要 coercion",
                    )
                payload = {}
            else:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] reflect 已通过片段扫描恢复 JSON（顶层不完整、截断或与思考链混杂）",
                    )
                payload = picked_rf
        elif phase == "write":
            picked_wr = pick_write_json_payload(raw or "")
            if picked_wr is None:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] write 片段恢复未果，交由后续摘要拼装兜底",
                    )
                payload = {}
            else:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] write 已通过片段扫描恢复 JSON（顶层不完整或被截断）",
                    )
                payload = picked_wr
        else:
            _struct_json_diag(
                task,
                phase,
                step="exit_fallback_wrapped_unhandled_phase",
                note="plan/decide 等阶段仍严格要求可解析顶层 JSON",
            )
            return None, f"{phase}阶段JSON无效: 无法解析合法 JSON"
    elif phase == "search":
        groups = payload.get("info_groups")
        if not isinstance(groups, list) or not groups:
            picked = pick_searcher_json_payload(raw or "")
            if picked is not None:
                payload = picked
    elif phase == "read" and isinstance(payload, dict) and not payload.get("_fallback_wrapped"):
        ana_chk = payload.get("analysis")
        if not isinstance(ana_chk, str) or not ana_chk.strip():
            _struct_json_diag(
                task,
                "read",
                step="first_pass_missing_analysis",
                first_pass_keys=[str(k) for k in list(payload.keys())[:28]],
                analysis_type=type(ana_chk).__name__,
                analysis_preview=_raw_snippet_repr(str(ana_chk), 160) if ana_chk is not None else repr(None),
                hint="supplier  often取到「第一个平衡括号子对象」而非顶层 reader；若fragment_object_count>1多半是这种误抓",
            )
            alt_rd = pick_reader_json_payload(raw_s)
            if alt_rd is not None:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] read 首段对象缺少 analysis，已改用片段扫描结果",
                    )
                _struct_json_diag(
                    task,
                    "read",
                    step="adopt_fragment_pick_reader",
                    picked_keys=[str(k) for k in list(alt_rd.keys())[:24]],
                    picked_analysis_len=len(str(alt_rd.get("analysis", ""))),
                )
                payload = alt_rd
            else:
                _struct_json_diag(
                    task,
                    "read",
                    step="fragment_pick_failed_will_use_empty_then_coerce",
                )
    elif phase == "reflect" and isinstance(payload, dict) and not payload.get("_fallback_wrapped"):
        acc = payload.get("accepted_reader_summary")
        no = payload.get("needs_optimization")
        frag = False
        frag_reason = ""
        if not isinstance(acc, dict) or no is None:
            frag = True
            frag_reason = "accepted_reader_summary 非 dict 或 needs_optimization 缺失"
        elif isinstance(acc, dict) and (
            not isinstance(acc.get("analysis"), str) or not str(acc.get("analysis")).strip()
        ):
            frag = True
            frag_reason = "accepted_reader_summary.analysis 缺失或为空"
        if frag:
            _struct_json_diag(
                task,
                "reflect",
                step="first_pass_incomplete",
                reason=frag_reason,
                first_pass_keys=[str(k) for k in list(payload.keys())[:28]],
                needs_optimization_type=type(no).__name__,
                accepted_summary_keys=list(acc.keys())[:22] if isinstance(acc, dict) else [],
            )
            alt_rf = pick_reflector_json_payload(raw_s)
            if alt_rf is not None:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] reflect 首段不完整，已改用片段扫描合并结果",
                    )
                _struct_json_diag(
                    task,
                    "reflect",
                    step="adopt_fragment_pick_reflect",
                    picked_keys=list(alt_rf.keys())[:24],
                )
                payload = alt_rf
            else:
                _struct_json_diag(task, "reflect", step="fragment_pick_reflect_failed_will_empty_coerce")
    elif phase == "write" and isinstance(payload, dict) and not payload.get("_fallback_wrapped"):
        es = payload.get("executive_summary")
        secs = payload.get("sections")
        tr = payload.get("traceability")
        title_ok = isinstance(payload.get("title"), str) and bool(str(payload.get("title", "")).strip())
        es_ok = isinstance(es, str) and bool(str(es).strip())
        secs_ok = isinstance(secs, list) and bool(secs)
        tr_ok = isinstance(tr, list) and bool(tr)
        if not (title_ok and es_ok and secs_ok and tr_ok):
            _struct_json_diag(
                task,
                "write",
                step="first_pass_incomplete",
                check_title_ok=title_ok,
                check_executive_summary_ok=es_ok,
                check_sections_ok=secs_ok,
                sections_len=len(secs) if isinstance(secs, list) else -1,
                check_traceability_ok=tr_ok,
                trace_len=len(tr) if isinstance(tr, list) else -1,
                first_pass_keys=[str(k) for k in list(payload.keys())[:28]],
            )
            alt_w = pick_write_json_payload(raw_s)
            if alt_w is not None:
                if task is not None:
                    _progress_log(
                        task,
                        "[pipeline_coerce] write 首段不完整，已改用片段扫描结果",
                    )
                _struct_json_diag(
                    task,
                    "write",
                    step="adopt_fragment_pick_write",
                    picked_keys=list(alt_w.keys())[:26],
                    picked_sections=len(alt_w.get("sections")) if isinstance(alt_w.get("sections"), list) else -1,
                )
                payload = alt_w
            else:
                _struct_json_diag(task, "write", step="fragment_pick_write_failed_will_fallback_later")

    egress_keys = [str(k) for k in list(payload.keys())[:28]] if isinstance(payload, dict) else []
    _struct_json_diag(
        task,
        phase,
        step="egress_normalize_json",
        result_top_keys=egress_keys,
        still_fallback_wrapped=bool(isinstance(payload, dict) and payload.get("_fallback_wrapped")),
    )
    return payload, None


def _ensure_searcher_minimal_groups(payload: dict[str, object], *, subtask_goal: str) -> dict[str, object]:
    """模型偶发给出空 info_groups 时兜底，避免研究流水线在此处硬失败。"""
    out = dict(payload)
    if not isinstance(out.get("search_notes"), str):
        out["search_notes"] = ""
    groups_obj = out.get("info_groups")
    if isinstance(groups_obj, list) and groups_obj:
        return out
    goal = (subtask_goal or "").strip() or "本子任务"
    stub_notes = (
        str(out["search_notes"]).strip() or "已由系统补齐占位分组，将进入联网检索与后续阅读阶段。"
    )
    out["info_groups"] = [
        {
            "group_title": "主题要点（系统补齐）",
            "relevance": "medium",
            "raw_findings": [
                f"与子任务相关的待核验要点（模型侧未分组）：{goal}。请结合后续工具检索结果交叉验证。"
            ],
        }
    ]
    out["search_notes"] = stub_notes
    return out


def _coerce_yes_no_literal(value: object, *, default: str = "no") -> str:
    """将模型/供应商的常见布尔写法统一为 yes|no。"""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if int(value) == 1:
                return "yes"
            if int(value) == 0:
                return "no"
        except (TypeError, ValueError):
            pass
    raw = str(value if value is not None else "").strip().lower()
    if raw in {"yes", "y", "true", "1", "need", "needed", "是", "要", "需要", "有必要"}:
        return "yes"
    if raw in {"no", "n", "false", "0", "none", "否", "不", "不需要", "跳过", "无需", "無需", "甭"}:
        return "no"
    if value is not None and isinstance(value, str) and value.strip():
        stripped_full = value.strip()
        if stripped_full in {"是", "否", "要"}:
            return "yes" if stripped_full in {"是", "要"} else "no"
    return default if default in {"yes", "no"} else "no"


def _coerce_search_relevance(value: object, *, default: str = "medium") -> str:
    s = str(value or "").strip().lower()
    zh = str(value or "")
    if "高" in zh or s in {"high", "hi", "h"}:
        return "high"
    if "低" in zh or s in {"low", "lo", "l"}:
        return "low"
    if "中" in zh or s in {"medium", "mid", "m", "med"}:
        return "medium"
    if s in {"high", "medium", "low"}:
        return s
    return default


def _coerce_decider_complexity(value: object, *, default: str | None = None) -> str | None:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return default
    low = raw.lower()
    if "复杂" in raw or "compound" in low or "composite" in low:
        return "complex"
    if "简单" in raw or raw in {"单步", "單步"}:
        return "simple"
    if low in {"simple", "easy", "single"}:
        return "simple"
    if low in {"complex", "multi", "hard"}:
        return "complex"
    if low in {"simple", "complex"}:
        return low
    return default


def _coerce_decider_payload(payload: dict[str, object]) -> dict[str, object]:
    out = dict(payload)
    c = _coerce_decider_complexity(out.get("complexity"))
    if c is not None:
        out["complexity"] = c
    return out


def _coerce_searcher_payload(payload: dict[str, object]) -> dict[str, object]:
    out = dict(payload)
    if not isinstance(out.get("search_notes"), str):
        out["search_notes"] = str(out.get("search_notes", "") or "")
    groups = out.get("info_groups")
    if not isinstance(groups, list):
        return out
    fixed_groups: list[dict[str, object]] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        gg = dict(g)
        title = gg.get("group_title")
        gg["group_title"] = str(title).strip() if title is not None else ""
        gg["relevance"] = _coerce_search_relevance(gg.get("relevance"))
        rf_raw = gg.get("raw_findings")
        rf: list[str]
        if isinstance(rf_raw, str) and rf_raw.strip():
            rf = [rf_raw.strip()]
        elif isinstance(rf_raw, list):
            rf = []
            for x in rf_raw:
                if isinstance(x, (str, int, float)):
                    xs = str(x).strip()
                    if xs:
                        rf.append(xs)
        else:
            rf = []
        gg["raw_findings"] = rf
        sources = gg.get("sources")
        if sources is None:
            gg.pop("sources", None)
            fixed_groups.append(gg)
            continue
        if isinstance(sources, list):
            gg["sources"] = [x for x in sources if isinstance(x, dict)]
        else:
            gg.pop("sources", None)
        fixed_groups.append(gg)
    out["info_groups"] = fixed_groups
    return out


def _repair_search_payload_for_validator(
    payload: dict[str, object],
    *,
    subtask_goal: str,
) -> dict[str, object]:
    """search 校验仍失败时再硬修一档，尽量不中断深度研究流水线。"""
    out = _coerce_searcher_payload(dict(payload))
    goal = (subtask_goal or "").strip() or "本子任务"
    raw_groups = out.get("info_groups")
    if not isinstance(raw_groups, list):
        return _ensure_searcher_minimal_groups(out, subtask_goal=goal)
    repaired: list[dict[str, object]] = []
    for idx, gg in enumerate(raw_groups):
        if not isinstance(gg, dict):
            continue
        g = dict(gg)
        gt = str(g.get("group_title") or "").strip()
        if not gt:
            g["group_title"] = f"信息组 {idx + 1}"
        g["relevance"] = _coerce_search_relevance(g.get("relevance"))
        rf = g.get("raw_findings")
        if (
            not isinstance(rf, list)
            or not rf
            or any(not isinstance(x, str) or not x.strip() for x in rf)
        ):
            g["raw_findings"] = [f"该组要点（与子任务「{goal}」相关）：已从异常输出中占位修复，请参考后续检索与阅读结果。"]
        repaired.append(g)
    if not repaired:
        return _ensure_searcher_minimal_groups(out, subtask_goal=goal)
    out["info_groups"] = repaired
    if not str(out.get("search_notes") or "").strip():
        out["search_notes"] = "search 结构化输出已通过系统容错修复。"
    return out


def _coerce_read_payload_for_pipeline(d: dict[str, object]) -> dict[str, object]:
    out = dict(d)
    ana = out.get("analysis")
    if isinstance(ana, str) and ana.strip():
        out["analysis"] = ana.strip()
    else:
        if ana is None or isinstance(ana, (dict, list)):
            ana_text = ""
        else:
            ana_text = str(ana).strip()
        out["analysis"] = ana_text or "（analysis 字段缺失或由系统占位，请结合上下文谨慎理解。）"

    kp = out.get("key_points")
    if isinstance(kp, str) and kp.strip():
        out["key_points"] = [kp.strip()]
    elif isinstance(kp, list):
        out["key_points"] = [str(x).strip() for x in kp if str(x).strip()]
    else:
        out["key_points"] = []

    lim = out.get("limitations")
    if isinstance(lim, str) and lim.strip():
        out["limitations"] = [lim.strip()]
    elif isinstance(lim, list):
        out["limitations"] = [str(x).strip() for x in lim if str(x).strip()]
    else:
        out["limitations"] = []
    return out


def _read_fallback_from_info_groups(info_groups: list[object], err_msg: str) -> dict[str, object]:
    snippets: list[str] = []
    for g in info_groups:
        if not isinstance(g, dict):
            continue
        rf = g.get("raw_findings")
        if not isinstance(rf, list):
            continue
        for line in rf:
            if isinstance(line, str) and line.strip():
                snippets.append(line.strip()[:480])
                if len(snippets) >= 12:
                    break
        if len(snippets) >= 12:
            break
    joined = "；".join(snippets)
    if not joined:
        joined = "（未从 info_groups 抽取到可用的 raw_findings 文本。）"
    return {
        "analysis": f"阅读阶段模型输出未能通过结构化校验（{err_msg}）。以下为从检索分组中抽取的正文摘录，供写作阶段兜底使用。\n\n{joined[:8000]}",
        "key_points": (snippets[:6] if snippets else ["要点未能由模型结构化输出，请参见 analysis 摘录。"]),
        "limitations": ["阅读 JSON 容错降级：结论可追溯性弱于规范流程。"],
    }


def _coerce_reflect_payload(
    payload: dict[str, object],
    *,
    read_fallback: dict[str, object],
) -> dict[str, object]:
    out = dict(payload)
    out["needs_optimization"] = _coerce_yes_no_literal(out.get("needs_optimization"), default="no")

    reason = out.get("reason")
    out["reason"] = str(reason).strip() if isinstance(reason, str) and str(reason).strip() else "（reason 字段缺失或由系统补齐。）"

    sug_raw = out.get("actionable_suggestions")
    if isinstance(sug_raw, str) and sug_raw.strip():
        out["actionable_suggestions"] = [sug_raw.strip()]
    elif isinstance(sug_raw, list):
        out["actionable_suggestions"] = [str(x).strip() for x in sug_raw if str(x).strip()]
    else:
        out["actionable_suggestions"] = []

    if out["needs_optimization"] == "yes" and not out["actionable_suggestions"]:
        out["actionable_suggestions"] = ["请结合上一轮阅读摘要，收紧检索关键词或拆分子任务后再检索。"]

    base = dict(read_fallback)
    acc_in = out.get("accepted_reader_summary")
    merged: dict[str, object]
    if isinstance(acc_in, dict):
        merged = {**base, **acc_in}
    else:
        merged = dict(base)
    out["accepted_reader_summary"] = _coerce_read_payload_for_pipeline(merged)
    return out


def _fallback_reflect_payload_from_read(read_payload: dict[str, object]) -> dict[str, object]:
    rp = _coerce_read_payload_for_pipeline(dict(read_payload))
    return {
        "needs_optimization": "no",
        "reason": "反思阶段结构化输出未通过校验：系统已终止优化回路并直接使用阅读摘要推进后续流水线。",
        "actionable_suggestions": [],
        "accepted_reader_summary": rp,
    }


def _fallback_write_payload_from_pipeline(
    *,
    query: str,
    err_msg: str,
    subtasks: list[dict[str, object]],
    final_subtask_summaries: list[dict[str, object]],
) -> dict[str, object]:
    """write 校验失败时用子任务摘要拼出可交付的报告结构。"""
    id_analysis: dict[str, str] = {}
    id_title: dict[str, str] = {}
    for item in final_subtask_summaries:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("subtask_id", "")).strip()
        if not sid:
            continue
        acc = item.get("accepted_reader_summary")
        ana = ""
        if isinstance(acc, dict):
            ana = str(acc.get("analysis", "")).strip()
        id_analysis[sid] = ana or "（该子任务未产生可用分析文本。）"
        id_title[sid] = str(item.get("subtask_title", "")).strip() or sid

    sections: list[dict[str, str]] = []
    traceability: list[dict[str, str]] = []

    for st in subtasks:
        if not isinstance(st, dict):
            continue
        sid = str(st.get("subtask_id", "")).strip()
        if not sid:
            continue
        title = str(st.get("title", "")).strip() or id_title.get(sid, sid)
        conclusion = id_analysis.get(sid, "（暂无）")[:2400]
        sections.append({"heading": title, "content": conclusion})
        traceability.append({"subtask_id": sid, "conclusion": conclusion[:1200]})

    q = (query or "").strip() or "用户查询"
    if not sections:
        stub = (
            f"用户对「{q}」的深度研究在进入报告阶段时出现结构化校验问题（{err_msg}）；"
            "未能从子任务列表生成章节，此为系统兜底正文。"
        )
        fake_id = ""
        if subtasks:
            fst = subtasks[0]
            if isinstance(fst, dict):
                fake_id = str(fst.get("subtask_id", "") or "").strip() or "auto-1"
        if not fake_id:
            fake_id = "fallback-1"
        sections.append({"heading": "研究摘录", "content": stub})
        traceability = [{"subtask_id": fake_id, "conclusion": stub[:1200]}]
    overview = sections[0]["content"][:900] if sections else ""
    return {
        "title": f"研究报告（容错生成）：{q[:72]}",
        "executive_summary": f"write 阶段 JSON 容错降级：{err_msg}\n\n{overview}",
        "sections": sections,
        "traceability": traceability or [{"subtask_id": "fallback", "conclusion": overview[:900]}],
    }


def _hard_fallback_plan_payload(query: str) -> dict[str, object]:
    q = (query or "").strip() or "当前研究问题"
    q_cut = q[:280]
    return {
        "alternatives": [
            {
                "plan_id": "plan-hard-a",
                "title": "单线梳理与归纳",
                "steps": [f"围绕「{q_cut}」完成要点检索、阅读与结构化归纳"],
                "rationale": "plan 阶段模型结构化输出不可用，系统自动注入占位方案（A）。",
            },
            {
                "plan_id": "plan-hard-b",
                "title": "两步深化路线",
                "steps": ["梳理背景与时间线／术语边界", "按关键主题补充对比与方法论局限"],
                "rationale": "plan 阶段模型结构化输出不可用，系统自动注入占位方案（B）。",
            },
        ]
    }


def _hard_fallback_decision_payload(alternatives: list[dict[str, object]], query: str) -> dict[str, object]:
    alts_clean = [
        dict(a) for a in alternatives if isinstance(a, dict) and str(a.get("plan_id", "")).strip()
    ]
    pid = str(alts_clean[0].get("plan_id", "")).strip() if alts_clean else "plan-hard-a"
    stem = ""
    if alts_clean:
        stem = str(alts_clean[0].get("title", "") or "").strip() or pid
    q = (query or "").strip() or "用户问题"
    goal = (f"{stem}：{q[:400]}" if stem else q)[:720]
    return {
        "selected_plan_id": pid,
        "decision_reason": "decide 阶段模型输出不可用或校验失败：系统降级为单步子任务，避免中断深度研究流水线。",
        "complexity": "simple",
        "merge_attempt_note": "未执行方案合并，由系统自动降级。",
        "subtasks": [
            {
                "subtask_id": "s1",
                "title": (stem[:200] if stem else "综合研究子任务"),
                "goal": goal,
                "depends_on": [],
            }
        ],
    }


def _guaranteed_valid_write_payload(
    *,
    query: str,
    subtasks_arg: list[dict[str, object]],
    summaries: list[dict[str, object]],
    err_msg: str,
) -> dict[str, object]:
    """最后一层报告拼装：必须满足 `_validate_write_json` 的常见约束。"""
    typed = [
        x
        for x in subtasks_arg
        if isinstance(x, dict) and str(x.get("subtask_id", "") or "").strip()
    ]
    sid_to_body: dict[str, str] = {}
    for item in summaries:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("subtask_id", "") or "").strip()
        if not sid:
            continue
        acc = item.get("accepted_reader_summary")
        txt = ""
        if isinstance(acc, dict):
            txt = str(acc.get("analysis", "") or "").strip()
        sid_to_body[sid] = txt or "（该子任务无可用摘录。）"

    sections: list[dict[str, str]] = []
    traces: list[dict[str, str]] = []
    for st in typed:
        sid = str(st.get("subtask_id", "")).strip()
        ttl = str(st.get("title", "") or "").strip() or sid
        body_raw = sid_to_body.get(sid, "（暂无）")[:12000]
        body = body_raw if body_raw.strip() else "（占位正文）"
        sections.append({"heading": ttl[:200], "content": body[:12000]})
        traces.append({"subtask_id": sid, "conclusion": body[:1180]})

    q = (query or "").strip() or "用户请求"
    if not traces:
        one = (
            f"与研究主题相关的自动摘要（兜底）。用户问题节选：「{q[:360]}」。"
            f"附加说明：{err_msg[:400]}"
        )
        sections = [{"heading": "总览（系统兜底）", "content": one}]
        traces = [{"subtask_id": "s1", "conclusion": one[:1180]}]
    excerpt = traces[0]["conclusion"].replace("\n", " ").strip()
    return {
        "title": f"研究报告（系统兜底）：{q[:72]}",
        "executive_summary": f"{err_msg[:520]}\n\n{excerpt[:900]}",
        "sections": sections,
        "traceability": traces,
    }


def _validate_planner_json(payload: dict[str, object]) -> tuple[bool, str]:
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list) or not (2 <= len(alternatives) <= 4):
        return False, "alternatives must be list with length 2-4"
    for item in alternatives:
        if not isinstance(item, dict):
            return False, "alternative must be object"
        if not isinstance(item.get("plan_id"), str) or not str(item.get("plan_id")).strip():
            return False, "plan_id must be non-empty string"
        if not isinstance(item.get("title"), str) or not str(item.get("title")).strip():
            return False, "title must be non-empty string"
        steps = item.get("steps")
        if not isinstance(steps, list) or not steps or any(not isinstance(s, str) or not s.strip() for s in steps):
            return False, "steps must be non-empty string list"
        if not isinstance(item.get("rationale"), str) or not str(item.get("rationale")).strip():
            return False, "rationale must be non-empty string"
    return True, ""


def _validate_decider_json(payload: dict[str, object], alternatives: list[dict[str, object]]) -> tuple[bool, str]:
    if payload.get("complexity") not in ("simple", "complex"):
        return False, "complexity must be simple or complex"
    if not isinstance(payload.get("selected_plan_id"), str) or not str(payload.get("selected_plan_id")).strip():
        return False, "selected_plan_id must be non-empty string"
    if not isinstance(payload.get("decision_reason"), str) or not str(payload.get("decision_reason")).strip():
        return False, "decision_reason must be non-empty string"
    if not isinstance(payload.get("merge_attempt_note"), str) or not str(payload.get("merge_attempt_note")).strip():
        return False, "merge_attempt_note must be non-empty string"
    valid_plan_ids = {str(item.get("plan_id", "")).strip() for item in alternatives if isinstance(item, dict)}
    if str(payload.get("selected_plan_id", "")).strip() not in valid_plan_ids:
        return False, "selected_plan_id not found in alternatives"
    subtasks = payload.get("subtasks")
    if not isinstance(subtasks, list):
        return False, "subtasks must be list"
    if payload.get("complexity") == "simple" and len(subtasks) != 1:
        return False, "simple complexity requires exactly one subtask"
    if payload.get("complexity") == "complex" and len(subtasks) < 2:
        return False, "complex complexity requires at least two subtasks"
    seen: set[str] = set()
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            return False, "subtask must be object"
        sid = subtask.get("subtask_id")
        if not isinstance(sid, str) or not sid.strip():
            return False, "subtask_id must be non-empty string"
        if sid in seen:
            return False, "subtask_id must be unique"
        seen.add(sid)
        if not isinstance(subtask.get("title"), str) or not str(subtask.get("title")).strip():
            return False, "subtask.title must be non-empty string"
        if not isinstance(subtask.get("goal"), str) or not str(subtask.get("goal")).strip():
            return False, "subtask.goal must be non-empty string"
        deps = subtask.get("depends_on")
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            return False, "subtask.depends_on must be string list"
    prior: set[str] = set()
    for subtask in subtasks:
        sid = str(subtask.get("subtask_id", ""))
        for dep in subtask.get("depends_on", []):
            if dep not in seen:
                return False, f"depends_on unknown id: {dep}"
            if dep not in prior:
                return False, f"depends_on must reference previous subtask: {dep}"
        prior.add(sid)
    return True, ""


def _validate_searcher_json(payload: dict[str, object]) -> tuple[bool, str]:
    groups = payload.get("info_groups")
    if not isinstance(groups, list) or not groups:
        return False, "info_groups must be non-empty list"
    if not isinstance(payload.get("search_notes"), str):
        return False, "search_notes must be string"
    for group in groups:
        if not isinstance(group, dict):
            return False, "info_group must be object"
        if group.get("relevance") not in ("high", "medium", "low"):
            return False, "relevance must be high|medium|low"
        if not isinstance(group.get("group_title"), str) or not str(group.get("group_title")).strip():
            return False, "group_title must be non-empty string"
        findings = group.get("raw_findings")
        if not isinstance(findings, list) or not findings or any(not isinstance(x, str) or not x.strip() for x in findings):
            return False, "raw_findings must be non-empty string list"
    return True, ""


def _validate_read_json(payload: dict[str, object]) -> tuple[bool, str]:
    if not isinstance(payload.get("analysis"), str) or not str(payload.get("analysis")).strip():
        return False, "analysis must be non-empty string"
    if not isinstance(payload.get("key_points"), list) or any(not isinstance(x, str) for x in payload.get("key_points", [])):
        return False, "key_points must be string list"
    if not isinstance(payload.get("limitations"), list) or any(not isinstance(x, str) for x in payload.get("limitations", [])):
        return False, "limitations must be string list"
    return True, ""


def _validate_reflector_json(payload: dict[str, object]) -> tuple[bool, str]:
    if payload.get("needs_optimization") not in ("yes", "no"):
        return False, "needs_optimization must be yes|no"
    if not isinstance(payload.get("reason"), str) or not str(payload.get("reason")).strip():
        return False, "reason must be non-empty string"
    suggestions = payload.get("actionable_suggestions")
    if not isinstance(suggestions, list) or any(not isinstance(item, str) for item in suggestions):
        return False, "actionable_suggestions must be string list"
    if payload.get("needs_optimization") == "yes" and not suggestions:
        return False, "actionable_suggestions must be non-empty when needs_optimization=yes"
    accepted = payload.get("accepted_reader_summary")
    if not isinstance(accepted, dict):
        return False, "accepted_reader_summary must be object"
    ok, msg = _validate_read_json(accepted)
    if not ok:
        return False, f"accepted_reader_summary invalid: {msg}"
    return True, ""


def _validate_write_json(payload: dict[str, object], subtasks: list[dict[str, object]]) -> tuple[bool, str]:
    if not isinstance(payload.get("title"), str) or not str(payload.get("title")).strip():
        return False, "title must be non-empty string"
    if not isinstance(payload.get("executive_summary"), str) or not str(payload.get("executive_summary")).strip():
        return False, "executive_summary must be non-empty string"
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        return False, "sections must be non-empty list"
    for section in sections:
        if not isinstance(section, dict):
            return False, "section must be object"
        if not isinstance(section.get("heading"), str) or not str(section.get("heading")).strip():
            return False, "section heading must be non-empty string"
        if not isinstance(section.get("content"), str) or not str(section.get("content")).strip():
            return False, "section content must be non-empty string"
    traceability = payload.get("traceability")
    if not isinstance(traceability, list) or not traceability:
        return False, "traceability must be non-empty list"
    trace_ids: set[str] = set()
    for item in traceability:
        if not isinstance(item, dict):
            return False, "traceability item must be object"
        if not isinstance(item.get("subtask_id"), str) or not str(item.get("subtask_id")).strip():
            return False, "traceability.subtask_id must be non-empty string"
        if not isinstance(item.get("conclusion"), str) or not str(item.get("conclusion")).strip():
            return False, "traceability.conclusion must be non-empty string"
        trace_ids.add(str(item.get("subtask_id")).strip())
    subtask_ids = {str(item.get("subtask_id", "")).strip() for item in subtasks if isinstance(item, dict)}
    if not subtask_ids.issubset(trace_ids):
        return False, "traceability must cover all subtasks"
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
    executive_summary = str(payload.get("executive_summary", "")).strip()
    sections = payload.get("sections", [])
    parts = [f"# {title}"]
    if executive_summary:
        parts.append(f"\n## 执行摘要\n{executive_summary}")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading", "")).strip()
            content = str(section.get("content", "")).strip()
            if heading and content:
                parts.append(f"\n## {heading}\n{content}")
    return "\n".join(parts).strip()


def _search_context(query: str) -> tuple[str, list[dict[str, str]], dict[str, str] | None, dict[str, object]]:
    url = (getattr(settings, "RA_OUTBOUND_DEMO_URL", "") or "").strip()
    routed = route_tool_call(tool_name="web_search", args={"query": query, "url": url})
    if not routed.ok:
        if str(routed.error_code).startswith("WEB_SEARCH_"):
            detail = f"联网检索降级为本地检索：{query[:120] or '未提供检索词'}"
            audit = routed.payload.get("audit", {})
            return (
                detail,
                [{
                    "query": query,
                    "title": f"{(query or '研究主题')[:40]} 相关综述",
                    "source": "local_rag",
                    "url": "",
                    "published_at": "",
                    "snippet": detail[:200],
                    "confidence": "0.5",
                }],
                None,
                audit if isinstance(audit, dict) else {},
            )
        return (
            f"联网检索失败：{routed.error_code} - {routed.error_message}",
            [],
            {"code": routed.error_code, "message": routed.error_message},
            routed.payload.get("audit", {}),
        )
    summary = str(routed.payload.get("summary", "")).strip()
    citations = routed.payload.get("citations", [])
    return summary, citations if isinstance(citations, list) else [], None, routed.payload.get("audit", {})


def _render_search_detail(
    subtask: dict[str, object],
    round_no: int,
    search_payload: dict[str, object],
    search_detail: str,
    search_audit: dict[str, object],
) -> str:
    lines = ["正在执行检索", f"子任务：{str(subtask.get('title', '')).strip() or '未命名'}"]
    groups = search_payload.get("info_groups", [])
    if isinstance(groups, list):
        lines.append(f"信息分组数：{len(groups)}")
    lines.append(f"工具检索：{search_detail}")
    lines.append(f"工具状态：{str(search_audit.get('status', '')).strip() or 'unknown'}")
    lines.append(f"轮次：{round_no}")
    return "\n".join(lines)


def _render_read_detail(subtask: dict[str, object], round_no: int, read_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            "正在阅读与分析证据",
            f"子任务：{str(subtask.get('title', '')).strip() or '未命名'}",
            f"核心结论：{str(read_payload.get('analysis', '')).strip()}",
            f"轮次：{round_no}",
        ]
    )


def _render_reflect_detail(subtask: dict[str, object], round_no: int, reflect_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            "正在反思与校验",
            f"子任务：{str(subtask.get('title', '')).strip() or '未命名'}",
            f"是否继续优化：{'是' if str(reflect_payload.get('needs_optimization', '')).strip() == 'yes' else '否'}",
            f"裁决原因：{str(reflect_payload.get('reason', '')).strip()}",
            f"轮次：{round_no}",
        ]
    )


def _render_write_detail(write_payload: dict[str, object], total_rounds: int) -> str:
    title = str(write_payload.get("title", "")).strip() or "研究报告"
    sections = write_payload.get("sections", [])
    return "\n".join(
        [
            "正在生成研究报告",
            f"报告标题：{title}",
            f"章节数：{len(sections) if isinstance(sections, list) else 0}",
            f"总反思轮次：{total_rounds}",
        ]
    )


def _render_local_command_detail(round_no: int, audit: dict[str, object]) -> str:
    status = str(audit.get("status", "")).strip() or "unknown"
    detail = str(audit.get("detail", "")).strip()
    lines = ["正在执行本地命令工具", f"执行状态：{status}"]
    if detail:
        lines.append(f"执行说明：{detail}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _render_local_file_detail(round_no: int, audit: dict[str, object], action: str) -> str:
    status = str(audit.get("status", "")).strip() or "unknown"
    detail = str(audit.get("detail", "")).strip()
    lines = ["正在执行本地文件工具", f"执行状态：{status}", f"动作：{action or 'unknown'}"]
    if detail:
        lines.append(f"执行说明：{detail}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


def _render_workspace_detail(round_no: int, audit: dict[str, object], action: str, step_index: int) -> str:
    status = str(audit.get("status", "")).strip() or "unknown"
    detail = str(audit.get("detail", "")).strip()
    lines = [
        "正在执行工作区文件工具",
        f"执行状态：{status}",
        f"步骤序号：{step_index + 1}",
        f"动作：{action or 'unknown'}",
    ]
    if detail:
        lines.append(f"执行说明：{detail}")
    lines.append(f"当前轮次：{round_no}")
    return "\n".join(lines)


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
    runtime_args = dict(args) if isinstance(args, dict) else {}
    runtime_args.setdefault("query", query[:200])
    result = route_tool_call(
        tool_name="local_command",
        args={"template": template, "args": runtime_args},
        risk_confirmation_strategy="never",
    )
    payload = result.payload if isinstance(result.payload, dict) else {}
    return {
        "ok": result.ok,
        "requires_confirmation": bool(payload.get("requires_confirmation", False)),
        "confirmation_payload": payload.get("confirmation_payload"),
        "error_code": result.error_code,
        "error_message": result.error_message,
        "audit": payload.get("audit", {}),
    }


def _maybe_run_local_file_action(task: AgentTask) -> dict[str, object] | None:
    cfg = _runtime_config(task)
    if bool(cfg.get("local_file_action_executed")):
        return None
    action_cfg = cfg.get("local_file_action")
    if not isinstance(action_cfg, dict):
        return None
    action = str(action_cfg.get("action", "")).strip()
    if not action:
        return None
    args = action_cfg.get("args", {})
    safe_args = args if isinstance(args, dict) else {}
    result = route_tool_call(
        tool_name="local_file",
        args={"action": action, "args": safe_args},
        risk_confirmation_strategy="never",
    )
    payload = result.payload if isinstance(result.payload, dict) else {}
    return {
        "ok": result.ok,
        "requires_confirmation": bool(payload.get("requires_confirmation", False)),
        "confirmation_payload": payload.get("confirmation_payload"),
        "error_code": result.error_code,
        "error_message": result.error_message,
        "audit": payload.get("audit", {}),
        "action": action,
    }


def _workspace_steps_from_config(cfg: dict[str, object]) -> list[dict[str, object]]:
    """
    从 runtime_config 中解析 workspace_plan 的步骤列表。

    注意：这里返回的 step 是浅拷贝（args 也单独 dict()），上游对 step.args 的修改
    （例如把 content_brief 物化后写回 args.content）不会再隐式回写到 cfg 中保存的
    plan 对象。需要持久化时由 `_maybe_run_workspace_plan` 显式调用
    `_update_runtime_config(workspace_plan=...)` 来保存。
    """
    plan = cfg.get("workspace_plan")
    if isinstance(plan, dict):
        raw_steps = plan.get("steps")
    else:
        raw_steps = plan
    if not isinstance(raw_steps, list):
        return []
    steps: list[dict[str, object]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "workspace").strip()
        action = str(item.get("action") or "").strip()
        args = item.get("args", {})
        if tool != "workspace" or not action:
            continue
        step: dict[str, object] = {
            "tool": "workspace",
            "action": action,
            "args": dict(args) if isinstance(args, dict) else {},
        }
        brief = str(item.get("content_brief") or "").strip()
        if brief:
            step["content_brief"] = brief
        steps.append(step)
    return steps


def _generate_workspace_step_content(
    *,
    task: AgentTask,
    user_query: str,
    path: str,
    brief: str,
    timeout_tokens: int = 2400,
) -> tuple[str | None, dict[str, object] | None]:
    """
    用 LLM 为 write_text/append_text 步骤生成正文。

    - 关闭 thinking：写教程/笔记/说明等创作任务，reasoning chain 既不带来质量收益，
      又会显著增加 token 与首字延迟，反而拖到 RA_LLM_TIMEOUT 之外；
    - 使用流式：内容生成耗时较长，httpx 的 read timeout 会在每个 SSE chunk 上重置，
      避免一次性 45/90s 硬阻塞超时；
    - max_tokens 收敛到 2400：足以覆盖 1500-2200 字中文 Markdown 教程，再大基本是
      纯粹的尾部冗余。
    """
    started = time.monotonic()
    user_prompt = WORKSPACE_CONTENT_USER_PROMPT.format(
        query=user_query.strip() or "(用户原始请求未记录)",
        path=path or "(未指定路径)",
        brief=brief.strip() or "(未提供写作简述，请合理生成)",
    )
    res = chat_completion(
        system_prompt=WORKSPACE_CONTENT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.4,
        max_tokens=timeout_tokens,
        enable_thinking=False,
        stream=True,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not res.ok:
        _progress_log(
            task,
            f"工作区内容生成失败 path={path} latency_ms={elapsed_ms} "
            f"code={res.error_code} msg={res.error_message}",
        )
        return None, {
            "code": res.error_code or "WORKSPACE_CONTENT_GEN_FAILED",
            "message": res.error_message or "工作区内容生成失败",
        }
    content = (res.content or "").strip()
    if not content:
        _progress_log(task, f"工作区内容生成为空 path={path} latency_ms={elapsed_ms}")
        return None, {"code": "WORKSPACE_CONTENT_EMPTY", "message": "LLM 未生成内容"}
    _progress_log(
        task,
        f"工作区内容生成完成 path={path} latency_ms={elapsed_ms} chars={len(content)}",
    )
    _update_runtime_config(
        task,
        llm_last_call={
            "phase": "workspace_content",
            "model": res.model,
            "latency_ms": res.latency_ms,
            "usage": res.usage if isinstance(res.usage, dict) else {},
        },
    )
    return content, None


def _materialize_step_content(
    *,
    task: AgentTask,
    user_query: str,
    step: dict[str, object],
) -> tuple[bool, dict[str, object] | None]:
    """
    若 step 是 write_text/append_text 且 step.content_brief 非空，
    则调用一次 LLM 用 brief 生成正文，覆盖 args.content。

    设计理由：路由阶段被要求"需要正文时只填 brief、args.content 留空"，但模型不一定听话；
    为了一致性，我们只看 brief：有 brief 就用 brief 生成，没有 brief 就用现有 args.content。
    返回 (ok, err)；ok=True 表示无需生成或生成成功。
    """
    action = str(step.get("action") or "").strip()
    if action not in {"write_text", "append_text"}:
        return True, None
    args = step.get("args")
    if not isinstance(args, dict):
        return True, None
    brief = str(step.get("content_brief") or "").strip()
    if not brief:
        return True, None
    path = str(args.get("path") or "").strip()
    content, err = _generate_workspace_step_content(
        task=task,
        user_query=user_query,
        path=path,
        brief=brief,
    )
    if err is not None:
        return False, err
    args["content"] = content or ""
    return True, None


def _inject_previous_workspace_output(
    args: dict[str, object],
    results: list[dict[str, object]],
    *,
    action: str,
) -> dict[str, object]:
    return inject_workspace_step_args(action, dict(args), list(results))


def _maybe_run_workspace_plan(task: AgentTask, round_no: int) -> dict[str, object] | None:
    cfg = _runtime_config(task)
    if bool(cfg.get("workspace_plan_executed")):
        return None
    steps = _workspace_steps_from_config(cfg)
    if not steps:
        return None

    index_raw = cfg.get("workspace_plan_next_index", 0)
    try:
        index = int(index_raw)
    except (TypeError, ValueError):
        index = 0
    if index >= len(steps):
        _update_runtime_config(task, workspace_plan_executed=True)
        return None

    results = cfg.get("workspace_plan_results", [])
    if not isinstance(results, list):
        results = []
    step = steps[index]
    action = str(step.get("action") or "").strip()
    args = step.get("args", {})

    # 调用工具之前，先把 write_text/append_text 步骤的 content_brief 物化为正文。
    # 这一步是必要的额外 LLM 调用：路由阶段不让模型生成长正文（避免 JSON 截断），
    # 改在执行阶段以"流式 + 关闭 thinking"的方式单独生成，避免 read timeout 的限制。
    content_generated = False
    brief = str(step.get("content_brief") or "").strip()
    if action in {"write_text", "append_text"} and brief:
        user_query = _latest_user_query(task)
        ok_gen, err = _materialize_step_content(
            task=task,
            user_query=user_query,
            step=step,
        )
        if not ok_gen:
            return {
                "ok": False,
                "requires_confirmation": False,
                "confirmation_payload": {},
                "error_code": str((err or {}).get("code") or "WORKSPACE_CONTENT_GEN_FAILED"),
                "error_message": str((err or {}).get("message") or "工作区内容生成失败"),
                "audit": {
                    "tool": "workspace",
                    "status": "failed",
                    "detail": "内容生成失败",
                    "meta": {"action": action, "step_index": index},
                },
                "action": action,
                "output": {},
                "step_index": index,
                "step_total": len(steps),
                "round_no": round_no,
            }
        content_generated = True
        # 同步把生成结果落回 cfg.workspace_plan，并清掉 content_brief，避免后续重跑时重复生成。
        plan_obj = cfg.get("workspace_plan")
        if isinstance(plan_obj, dict):
            raw_steps_obj = plan_obj.get("steps")
            if isinstance(raw_steps_obj, list) and 0 <= index < len(raw_steps_obj):
                plan_step = raw_steps_obj[index]
                if isinstance(plan_step, dict) and isinstance(plan_step.get("args"), dict):
                    plan_step["args"]["content"] = args.get("content", "")
                    if "content_brief" in plan_step:
                        plan_step.pop("content_brief", None)
                    _update_runtime_config(task, workspace_plan=plan_obj)

    safe_args = _inject_previous_workspace_output(
        dict(args) if isinstance(args, dict) else {},
        results,
        action=action,
    )
    result = route_tool_call(
        tool_name="workspace",
        args={"action": action, "args": safe_args},
        risk_confirmation_strategy="never",
        user_id=str(task.session.owner_id),
    )
    payload = result.payload if isinstance(result.payload, dict) else {}
    confirmation = payload.get("confirmation_payload")
    if isinstance(confirmation, dict):
        confirmation = {**confirmation, "step_index": index, "step_total": len(steps)}
    else:
        confirmation = {}
    audit = payload.get("audit", {})
    if not isinstance(audit, dict):
        audit = {}
    output = payload.get("output", {})
    if not isinstance(output, dict):
        output = {}

    return {
        "ok": result.ok,
        "requires_confirmation": bool(payload.get("requires_confirmation", False)),
        "confirmation_payload": confirmation,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "audit": audit,
        "action": action,
        "output": output,
        "step_index": index,
        "step_total": len(steps),
        "round_no": round_no,
        "content_generated": content_generated,
    }


def _fail_task(task: AgentTask, code: str, message: str) -> None:
    _progress_log(task, f"任务失败 code={code} message={message}")
    task.status = "failed"
    task.error_code = code
    task.error_message = message
    task.save(
        update_fields=[
            "status",
            "error_code",
            "error_message",
            "step_seq",
            "steps",
            "result_payload",
            "updated_at",
        ]
    )


def _task_for_update(task_id: uuid.UUID):
    qs = AgentTask.objects.filter(id=task_id)
    if connection.vendor != "sqlite":
        qs = qs.select_for_update()
    return qs.get()


def _markdown_from_workspace_results(task: AgentTask) -> str:
    cfg = _runtime_config(task)
    results = cfg.get("workspace_plan_results", [])
    if not isinstance(results, list):
        results = []
    lines = ["# 工作区文件操作结果", "", f"共执行 {len(results)} 个步骤。"]
    for item in results:
        if not isinstance(item, dict):
            continue
        index = int(item.get("step_index") or 0) + 1
        action = str(item.get("action") or "workspace").strip()
        output = item.get("output")
        lines.extend(["", f"## 步骤 {index}: `{action}`"])
        if isinstance(output, dict):
            if output.get("path"):
                lines.append(f"- 路径：`{output.get('path')}`")
            if output.get("output"):
                lines.append(f"- 输出：`{output.get('output')}`")
            if output.get("count") is not None:
                lines.append(f"- 数量：{output.get('count')}")
            if output.get("changed_count") is not None:
                lines.append(f"- 变更文件数：{output.get('changed_count')}")
            if output.get("bytes") is not None:
                lines.append(f"- 大小：{output.get('bytes')} 字节")
            if output.get("items") and isinstance(output.get("items"), list):
                lines.append("- 文件列表：")
                for entry in output.get("items", [])[:20]:
                    if isinstance(entry, dict):
                        lines.append(f"  - `{entry.get('rel_path') or entry.get('name')}`")
            if output.get("changed") and isinstance(output.get("changed"), list):
                lines.append("- 替换预览/结果：")
                for entry in output.get("changed", [])[:20]:
                    if isinstance(entry, dict):
                        lines.append(f"  - `{entry.get('path')}`：{entry.get('replacements')} 处")
        else:
            lines.append("- 已完成。")
    return "\n".join(lines).strip()


def _is_workspace_pipeline(task: AgentTask) -> bool:
    cfg = _runtime_config(task)
    return bool(cfg.get("workspace_pipeline"))


def execute_workspace_pipeline_task(task_id: uuid.UUID) -> None:
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status not in ("pending", "running"):
                return
            task.status = "running"
            _progress_log(task, "启动工作区任务流水线")
            if int(task.step_seq or 0) == 0:
                _append_step(task, "plan", "识别工作区文件操作", "已进入工作区任务流水线，跳过不需要的深度研究阶段")
            task.save(update_fields=["status", "step_seq", "steps", "updated_at"])

        while True:
            with transaction.atomic():
                task = _task_for_update(task_id)
                workspace_result = _maybe_run_workspace_plan(task, 1)
                if not workspace_result:
                    body = _markdown_from_workspace_results(task)
                    task.status = "completed"
                    task.intervention = None
                    payload = task.result_payload if isinstance(task.result_payload, dict) else {}
                    payload.update(
                        {
                            "format": "markdown",
                            "body": body,
                            "citations": [],
                            "attachments": [],
                            "pipeline": list(WORKSPACE_PIPELINE_PHASES),
                            "runtime_config": _runtime_config(task),
                        }
                    )
                    task.result_payload = payload
                    _append_step(task, "write", "完成工作区文件操作", "工作区任务已完成")
                    _progress_log(task, "工作区任务流水线完成")
                    task.save(update_fields=["status", "intervention", "result_payload", "step_seq", "steps", "updated_at"])
                    session = ResearchSession.objects.get(id=task.session_id)
                    ResearchMessage.objects.create(session=session, role="assistant", content=f"{REPORT_MESSAGE_PREFIX}{body}")
                    ResearchSession.objects.filter(pk=session.pk).update(updated_at=timezone.now())
                    return

                workspace_audit = workspace_result["audit"] if isinstance(workspace_result.get("audit"), dict) else {}
                workspace_confirmation = workspace_result.get("confirmation_payload")
                if not isinstance(workspace_confirmation, dict):
                    workspace_confirmation = {}
                workspace_status = workspace_audit.get("status")
                if not workspace_status:
                    if workspace_result.get("requires_confirmation"):
                        workspace_status = "failed"
                    elif workspace_result.get("ok"):
                        workspace_status = "succeeded"
                    else:
                        workspace_status = "failed"
                action = str(workspace_result.get("action", "")).strip()
                step_index = int(workspace_result.get("step_index") or 0)
                if workspace_result.get("content_generated"):
                    _append_step(
                        task,
                        "read",
                        f"为步骤 {step_index + 1} 生成正文",
                        "已基于用户原始请求与本步骤的写作简述生成 Markdown / 文本内容",
                        audit={
                            "tool": "llm_writer",
                            "status": "succeeded",
                            "operation_type": "content_generation",
                            "tool_type": "llm",
                            "actor_type": "system",
                        },
                    )
                _append_step(
                    task,
                    "search",
                    "执行工作区文件工具",
                    _render_workspace_detail(1, workspace_audit, action, step_index),
                    audit={
                        **workspace_audit,
                        "operation_type": "workspace",
                        "tool_type": "workspace",
                        "status": workspace_status,
                        "risk_level": str(workspace_confirmation.get("risk_level", "")).strip().lower(),
                        "rule_hit": str(workspace_result.get("error_code", "")).strip(),
                        "actor_type": "system",
                    },
                )
                if workspace_result["requires_confirmation"]:
                    _fail_task(
                        task,
                        "FEATURE_REMOVED",
                        "高风险动作人工干预功能已移除，任务不会进入人工确认挂起状态",
                    )
                    return
                if not workspace_result["ok"]:
                    _fail_task(task, str(workspace_result.get("error_code") or "WORKSPACE_FAILED"), str(workspace_result.get("error_message") or "工作区文件工具执行失败"))
                    return
                cfg = _runtime_config(task)
                prior_results = cfg.get("workspace_plan_results", [])
                if not isinstance(prior_results, list):
                    prior_results = []
                prior_results.append(
                    {
                        "step_index": step_index,
                        "action": action,
                        "output": workspace_result.get("output") if isinstance(workspace_result.get("output"), dict) else {},
                    }
                )
                next_index = step_index + 1
                updates: dict[str, object] = {
                    "workspace_plan_results": prior_results,
                    "workspace_plan_next_index": next_index,
                }
                if next_index >= int(workspace_result.get("step_total") or next_index):
                    updates["workspace_plan_executed"] = True
                _update_runtime_config(task, **updates)
                task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])
    finally:
        close_old_connections()


def execute_task_pipeline(task_id: uuid.UUID) -> None:
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status not in ("pending", "running"):
                return
            if task.status == "pending":
                task.status = "running"
                task.save(update_fields=["status", "updated_at"])
            _progress_log(task, "启动深度研究任务流水线")

        with transaction.atomic():
            task = _task_for_update(task_id)
            query = _latest_user_query(task)
            max_rounds = _max_reflect_rounds(task)

        cfg = _runtime_config(task)
        # ── 智能任务拆解 ────────────────────────────────────────────────
        # 旧的「workspace_intent → 三选一模式」入口被替换为统一的 Smart Planner：
        #   1. 任何任务都先经过 smart_planner.detect_smart_plan，得到一组步骤序列；
        #   2. 若用户传 deep_thinking=False（默认），整段任务交给 lite_orchestrator
        #      （chat / workspace 步骤均可执行，research 步骤会在规划阶段降级为 chat）；
        #   3. 若 deep_thinking=True 且规划包含 research，沿用本文件下方的 6 阶段
        #      深度研究流水线，并把规划中的 workspace 步骤、post_write_path 平移到
        #      旧的 cfg.workspace_plan / cfg.post_research_write，复用既有执行机制。
        # 兼容入口：用户在 create_task 中显式传入 workspace_plan / post_research_write
        # 时仍按旧契约执行，不再触发 smart_planner。
        if "smart_plan" not in cfg and "workspace_plan" not in cfg and "post_research_write" not in cfg:
            deep_thinking = bool(cfg.get("deep_thinking", False))
            route_started = time.monotonic()
            plan = detect_smart_plan(query, allow_research=deep_thinking)
            route_elapsed_ms = int((time.monotonic() - route_started) * 1000)
            if plan is None:
                plan = fallback_chat_plan(query)
                _progress_log(
                    task,
                    f"smart_planner 失败，已回退为单步 chat latency_ms={route_elapsed_ms}",
                )
            else:
                type_seq = ",".join(step.get("type", "?") for step in plan.get("steps", []))
                _progress_log(
                    task,
                    f"smart_planner 完成 deep_thinking={deep_thinking} "
                    f"steps={len(plan.get('steps', []))} types=[{type_seq}] "
                    f"needs_deep={plan.get('needs_deep_research')} latency_ms={route_elapsed_ms}",
                )

            steps = plan.get("steps", []) if isinstance(plan, dict) else []
            has_research = any(str(step.get("type", "")).lower() == "research" for step in steps)

            if deep_thinking and has_research:
                # 把 smart_plan 中的 workspace / post_write 平移到旧 cfg 字段，
                # 让深度研究流水线沿用既有执行机制。
                workspace_steps = [
                    {
                        "tool": "workspace",
                        "action": step.get("action"),
                        "args": step.get("args", {}),
                        **(
                            {"content_brief": step["content_brief"]}
                            if step.get("content_brief")
                            else {}
                        ),
                    }
                    for step in steps
                    if str(step.get("type", "")).lower() == "workspace"
                ]
                research_steps = [
                    step for step in steps if str(step.get("type", "")).lower() == "research"
                ]
                post_write: dict[str, Any] | None = None
                for r_step in research_steps:
                    if r_step.get("post_write_path"):
                        post_write = {
                            "path": str(r_step.get("post_write_path") or "").strip(),
                            "content_brief": "",
                        }
                        break
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    updates: dict[str, Any] = {"smart_plan": plan}
                    if workspace_steps:
                        updates["workspace_plan"] = {"steps": workspace_steps}
                    if post_write and post_write["path"]:
                        updates["post_research_write"] = post_write
                    _update_runtime_config(task, **updates)
                    extra = []
                    if workspace_steps:
                        extra.append(f"workspace 步骤 {len(workspace_steps)} 个")
                    if post_write and post_write["path"]:
                        extra.append(f"研究后写入 `{post_write['path']}`")
                    detail = (
                        "已识别为深度研究任务（包含 research 步骤）。"
                        + ("附加：" + "；".join(extra) + "。" if extra else "")
                    )
                    _append_step(task, "plan", "智能任务拆解（深度研究）", detail)
                    task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])
                # 继续往下走深度研究流水线
            else:
                # 走轻量统一执行器
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    _update_runtime_config(
                        task,
                        smart_plan=plan,
                        lite_pipeline=True,
                        smart_plan_next_index=0,
                    )
                    type_seq = ",".join(step.get("type", "?") for step in steps)
                    _append_step(
                        task,
                        "plan",
                        "智能任务拆解（轻量模式）",
                        "\n".join(
                            [
                                f"deep_thinking: {deep_thinking}",
                                f"步骤数：{len(steps)}",
                                f"类型序列：{type_seq}",
                                f"总结：{plan.get('summary', '')}",
                            ]
                        ),
                    )
                    task.save(
                        update_fields=[
                            "result_payload",
                            "step_seq",
                            "steps",
                            "updated_at",
                        ]
                    )
                execute_lite_pipeline(task_id)
                return
        elif isinstance(cfg.get("workspace_plan"), dict) and not cfg.get("smart_plan"):
            # 老接口直传 workspace_plan 时保留旧的工作区流水线行为
            with transaction.atomic():
                task = _task_for_update(task_id)
                _update_runtime_config(task, workspace_pipeline=True)
                task.save(update_fields=["result_payload", "updated_at"])
            execute_workspace_pipeline_task(task_id)
            return

        all_citations: list[dict[str, str]] = []
        all_reflector_conclusions: list[dict[str, object]] = []
        final_subtask_summaries: list[dict[str, object]] = []
        reflector_history_suggestions: list[str] = []
        total_reflect_rounds = 0

        with transaction.atomic():
            task = _task_for_update(task_id)
            raw, err = _llm_call(
                phase="plan",
                task=task,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_PLAN.format(
                    query=query,
                    suggestions=json.dumps(reflector_history_suggestions, ensure_ascii=False),
                ),
                temperature=0.2,
                max_tokens=4096,
                enable_thinking=False,
                history_limit=2,
            )
            if err:
                _fail_task(task, str(err["code"]), str(err["message"]))
                return
            planner_payload, parse_err = _normalize_json(raw or "", "plan", task=task)
            if planner_payload is None:
                _progress_log(task, f"[pipeline_coerce] plan 解析失败→硬兜底: {parse_err}")
                planner_payload = _hard_fallback_plan_payload(query)
            ok, err_msg = _validate_planner_json(planner_payload)
            if not ok:
                _progress_log(task, f"[pipeline_coerce] plan 校验失败→硬兜底: {err_msg}")
                planner_payload = _hard_fallback_plan_payload(query)
            _append_step(task, "plan", "规划研究任务", "已输出多方案规划")
            task.save(update_fields=["step_seq", "steps", "updated_at"])

        alternatives_raw = planner_payload.get("alternatives", [])
        assert isinstance(alternatives_raw, list)
        alternatives = [
            dict(x)
            for x in alternatives_raw
            if isinstance(x, dict) and str(x.get("plan_id", "")).strip()
        ]
        if len(alternatives) < 2:
            alternatives = list(_hard_fallback_plan_payload(query)["alternatives"])

        with transaction.atomic():
            task = _task_for_update(task_id)
            raw, err = _llm_call(
                phase="decide",
                task=task,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_DECIDE.format(
                    query=query,
                    alternatives_json=json.dumps(alternatives, ensure_ascii=False),
                ),
                temperature=0.1,
                max_tokens=4096,
                enable_thinking=False,
                history_limit=2,
            )
            if err:
                _fail_task(task, str(err["code"]), str(err["message"]))
                return
            decision_payload, parse_err = _normalize_json(raw or "", "decide", task=task)
            if decision_payload is None:
                _progress_log(task, f"[pipeline_coerce] decide 解析失败→硬兜底: {parse_err}")
                decision_payload = _hard_fallback_decision_payload(alternatives, query)
            decision_payload = _coerce_decider_payload(decision_payload)
            ok, err_msg = _validate_decider_json(decision_payload, alternatives)
            if not ok:
                _progress_log(task, f"[pipeline_coerce] decide 校验失败→硬兜底: {err_msg}")
                decision_payload = _hard_fallback_decision_payload(alternatives, query)
            decision_payload = _coerce_decider_payload(decision_payload)
            _append_step(task, "decide", "方案决策与拆解", "已输出复杂度与子任务列表")
            task.save(update_fields=["step_seq", "steps", "updated_at"])

        subtasks = decision_payload.get("subtasks", [])
        assert isinstance(subtasks, list)

        for subtask in subtasks:
            if not isinstance(subtask, dict):
                continue
            subtask_id = str(subtask.get("subtask_id", "")).strip() or "unknown"
            subtask_title = str(subtask.get("title", "")).strip() or "未命名子任务"
            subtask_goal = str(subtask.get("goal", "")).strip() or subtask_title
            feedback = ""
            round_no = 1

            while True:
                with transaction.atomic():
                    task = _task_for_update(task_id)
                    search_prompt = USER_PROMPT_SEARCH.format(
                        query=query,
                        plan_text=subtask_title,
                        reflect_round=round_no,
                        max_rounds=max_rounds,
                    )
                    if feedback:
                        search_prompt += f"\nprevious_reflector_feedback: {feedback}"
                    raw, err = _llm_call(
                        phase="search",
                        task=task,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=search_prompt,
                        temperature=0.1,
                        max_tokens=6144,
                        enable_thinking=False,
                        history_limit=2,
                    )
                    if err:
                        _fail_task(task, str(err["code"]), str(err["message"]))
                        return
                    search_payload, parse_err = _normalize_json(raw or "", "search", task=task)
                    if search_payload is None:
                        _progress_log(task, f"[pipeline_coerce] search 解析失败→空壳后强制补齐: {parse_err}")
                        search_payload = {}
                    search_payload = _ensure_searcher_minimal_groups(
                        search_payload, subtask_goal=subtask_goal
                    )
                    search_payload = _coerce_searcher_payload(search_payload)
                    ok, err_msg = _validate_searcher_json(search_payload)
                    if not ok:
                        _progress_log(
                            task,
                            f"[pipeline_coerce] search 一次校验未通过，尝试字段级修复: {err_msg}",
                        )
                        search_payload = _repair_search_payload_for_validator(
                            search_payload, subtask_goal=subtask_goal
                        )
                        ok, err_msg = _validate_searcher_json(search_payload)
                    if not ok:
                        _progress_log(
                            task,
                            f"[pipeline_coerce] search 仍失败，再次强制 repair: {err_msg}",
                        )
                        search_payload = _repair_search_payload_for_validator(
                            {}, subtask_goal=subtask_goal
                        )
                        ok, err_msg = _validate_searcher_json(search_payload)
                    if not ok:
                        search_payload = _ensure_searcher_minimal_groups({}, subtask_goal=subtask_goal)

                search_detail, citations, fatal, search_audit = _search_context(subtask_goal)
                if fatal:
                    fatal_audit = search_audit if isinstance(search_audit, dict) else {}
                    fatal_meta = fatal_audit.get("meta") if isinstance(fatal_audit.get("meta"), dict) else {}
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        _append_step(
                            task,
                            "search",
                            f"检索失败：{subtask_title}",
                            str(fatal.get("message", "")),
                            audit={
                                **fatal_audit,
                                "operation_type": "web_search",
                                "tool_type": "web_search",
                                "status": fatal_audit.get("status") or "failed",
                                "rule_hit": str(fatal_meta.get("rule_hit") or fatal.get("code", "")).strip(),
                                "policy_version": str(fatal_meta.get("policy_version") or "").strip(),
                                "target_domain": str(fatal_meta.get("target_domain") or "").strip(),
                                "is_exception": True,
                                "exception_message": str(fatal.get("message", "")).strip(),
                            },
                        )
                        _fail_task(task, str(fatal["code"]), str(fatal["message"]))
                    return

                all_citations.extend(citations)
                info_groups = search_payload.get("info_groups")
                assert isinstance(info_groups, list)
                if citations:
                    info_groups.append(
                        {
                            "group_title": "工具检索补充",
                            "relevance": "medium",
                            "raw_findings": [search_detail or "无补充"],
                            "sources": [
                                {
                                    "title": str(item.get("title", "")).strip(),
                                    "url": str(item.get("url", "")).strip(),
                                    "snippet": str(item.get("snippet", "")).strip(),
                                    "raw_content": str(item.get("raw_content", "")).strip(),
                                }
                                for item in citations
                                if isinstance(item, dict)
                            ],
                        }
                    )

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    search_step_audit = search_audit if isinstance(search_audit, dict) else {}
                    _append_step(
                        task,
                        "search",
                        f"检索子任务：{subtask_title}",
                        _render_search_detail(subtask, round_no, search_payload, search_detail, search_audit),
                        audit={
                            **search_step_audit,
                            "operation_type": "web_search",
                            "tool_type": "web_search",
                            "status": search_step_audit.get("status") or "succeeded",
                            "actor_type": "system",
                        },
                    )
                    task.save(update_fields=["step_seq", "steps", "updated_at"])

                local_cmd_result = _maybe_run_local_command(task, subtask_goal)
                if local_cmd_result:
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        local_cmd_audit = local_cmd_result["audit"] if isinstance(local_cmd_result.get("audit"), dict) else {}
                        local_cmd_confirmation = local_cmd_result.get("confirmation_payload")
                        if not isinstance(local_cmd_confirmation, dict):
                            local_cmd_confirmation = {}
                        local_cmd_status = local_cmd_audit.get("status")
                        if not local_cmd_status:
                            if local_cmd_result.get("requires_confirmation"):
                                local_cmd_status = "failed"
                            elif local_cmd_result.get("ok"):
                                local_cmd_status = "succeeded"
                            else:
                                local_cmd_status = "failed"
                        _append_step(
                            task,
                            "search",
                            "执行本地命令工具",
                            _render_local_command_detail(round_no, local_cmd_result["audit"]),
                            audit={
                                **local_cmd_audit,
                                "operation_type": "local_command",
                                "tool_type": "local_command",
                                "status": local_cmd_status,
                                "risk_level": str(local_cmd_confirmation.get("risk_level", "")).strip().lower(),
                                "rule_hit": str(local_cmd_result.get("error_code", "")).strip(),
                                "actor_type": "system",
                            },
                        )
                        if local_cmd_result["requires_confirmation"]:
                            _fail_task(
                                task,
                                "FEATURE_REMOVED",
                                "高风险动作人工干预功能已移除，任务不会进入人工确认挂起状态",
                            )
                            return
                        if not local_cmd_result["ok"]:
                            _fail_task(task, str(local_cmd_result.get("error_code") or "LOCAL_CMD_FAILED"), str(local_cmd_result.get("error_message") or "本地命令执行失败"))
                            return
                        _update_runtime_config(task, local_command_executed=True)
                        task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])

                local_file_result = _maybe_run_local_file_action(task)
                if local_file_result:
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        local_file_audit = local_file_result["audit"] if isinstance(local_file_result.get("audit"), dict) else {}
                        local_file_confirmation = local_file_result.get("confirmation_payload")
                        if not isinstance(local_file_confirmation, dict):
                            local_file_confirmation = {}
                        local_file_status = local_file_audit.get("status")
                        if not local_file_status:
                            if local_file_result.get("requires_confirmation"):
                                local_file_status = "failed"
                            elif local_file_result.get("ok"):
                                local_file_status = "succeeded"
                            else:
                                local_file_status = "failed"
                        _append_step(
                            task,
                            "search",
                            "执行本地文件工具",
                            _render_local_file_detail(round_no, local_file_result["audit"], str(local_file_result.get("action", ""))),
                            audit={
                                **local_file_audit,
                                "operation_type": "local_file",
                                "tool_type": "local_file",
                                "status": local_file_status,
                                "risk_level": str(local_file_confirmation.get("risk_level", "")).strip().lower(),
                                "rule_hit": str(local_file_result.get("error_code", "")).strip(),
                                "actor_type": "system",
                            },
                        )
                        if local_file_result["requires_confirmation"]:
                            _fail_task(
                                task,
                                "FEATURE_REMOVED",
                                "高风险动作人工干预功能已移除，任务不会进入人工确认挂起状态",
                            )
                            return
                        if not local_file_result["ok"]:
                            _fail_task(task, str(local_file_result.get("error_code") or "LOCAL_FILE_FAILED"), str(local_file_result.get("error_message") or "本地文件执行失败"))
                            return
                        _update_runtime_config(task, local_file_action_executed=True)
                        task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])

                while True:
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        workspace_result = _maybe_run_workspace_plan(task, round_no)
                        if not workspace_result:
                            task.save(update_fields=["result_payload", "updated_at"])
                            break
                        workspace_audit = workspace_result["audit"] if isinstance(workspace_result.get("audit"), dict) else {}
                        workspace_confirmation = workspace_result.get("confirmation_payload")
                        if not isinstance(workspace_confirmation, dict):
                            workspace_confirmation = {}
                        workspace_status = workspace_audit.get("status")
                        if not workspace_status:
                            if workspace_result.get("requires_confirmation"):
                                workspace_status = "failed"
                            elif workspace_result.get("ok"):
                                workspace_status = "succeeded"
                            else:
                                workspace_status = "failed"
                        action = str(workspace_result.get("action", "")).strip()
                        step_index = int(workspace_result.get("step_index") or 0)
                        _append_step(
                            task,
                            "search",
                            "执行工作区文件工具",
                            _render_workspace_detail(round_no, workspace_audit, action, step_index),
                            audit={
                                **workspace_audit,
                                "operation_type": "workspace",
                                "tool_type": "workspace",
                                "status": workspace_status,
                                "risk_level": str(workspace_confirmation.get("risk_level", "")).strip().lower(),
                                "rule_hit": str(workspace_result.get("error_code", "")).strip(),
                                "actor_type": "system",
                            },
                        )
                        if workspace_result["requires_confirmation"]:
                            _fail_task(
                                task,
                                "FEATURE_REMOVED",
                                "高风险动作人工干预功能已移除，任务不会进入人工确认挂起状态",
                            )
                            return
                        if not workspace_result["ok"]:
                            _fail_task(task, str(workspace_result.get("error_code") or "WORKSPACE_FAILED"), str(workspace_result.get("error_message") or "工作区文件工具执行失败"))
                            return
                        cfg = _runtime_config(task)
                        prior_results = cfg.get("workspace_plan_results", [])
                        if not isinstance(prior_results, list):
                            prior_results = []
                        prior_results.append(
                            {
                                "step_index": step_index,
                                "action": action,
                                "output": workspace_result.get("output") if isinstance(workspace_result.get("output"), dict) else {},
                            }
                        )
                        next_index = step_index + 1
                        updates: dict[str, object] = {
                            "workspace_plan_results": prior_results,
                            "workspace_plan_next_index": next_index,
                        }
                        if next_index >= int(workspace_result.get("step_total") or next_index):
                            updates["workspace_plan_executed"] = True
                        _update_runtime_config(task, **updates)
                        task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])
                    continue

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    raw, err = _llm_call(
                        phase="read",
                        task=task,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=USER_PROMPT_READ.format(
                            query=query,
                            search_detail=json.dumps(info_groups, ensure_ascii=False),
                            citations=_render_citations(citations),
                        ),
                        temperature=0.2,
                        max_tokens=6144,
                        enable_thinking=True,
                        history_limit=2,
                    )
                    if err:
                        _fail_task(task, str(err["code"]), str(err["message"]))
                        return
                    read_payload, parse_err = _normalize_json(raw or "", "read", task=task)
                    if read_payload is None:
                        read_payload = {}
                    read_payload = _coerce_read_payload_for_pipeline(read_payload)
                    ok, err_msg = _validate_read_json(read_payload)
                    if not ok:
                        _progress_log(task, f"[pipeline_coerce] read 改用 info_groups 降级: {err_msg}")
                        read_payload = _read_fallback_from_info_groups(info_groups, err_msg)
                    _append_step(task, "read", f"阅读子任务：{subtask_title}", _render_read_detail(subtask, round_no, read_payload))
                    task.save(update_fields=["step_seq", "steps", "updated_at"])

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    raw, err = _llm_call(
                        phase="reflect",
                        task=task,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=USER_PROMPT_REFLECT.format(
                            plan_text=json.dumps(subtask, ensure_ascii=False),
                            analysis_text=json.dumps(read_payload, ensure_ascii=False),
                            reflect_round=round_no,
                            max_rounds=max_rounds,
                        ),
                        temperature=0.1,
                        max_tokens=6144,
                        enable_thinking=True,
                        history_limit=2,
                    )
                    if err:
                        _fail_task(task, str(err["code"]), str(err["message"]))
                        return
                    reflect_payload, parse_err = _normalize_json(raw or "", "reflect", task=task)
                    if reflect_payload is None:
                        reflect_payload = {}
                    reflect_payload = _coerce_reflect_payload(
                        reflect_payload, read_fallback=read_payload
                    )
                    ok, err_msg = _validate_reflector_json(reflect_payload)
                    if not ok:
                        _progress_log(task, f"[pipeline_coerce] reflect 沿用阅读摘要兜底: {err_msg}")
                        reflect_payload = _fallback_reflect_payload_from_read(read_payload)
                    _append_step(
                        task,
                        "reflect",
                        f"反思子任务：{subtask_title}",
                        _render_reflect_detail(subtask, round_no, reflect_payload),
                    )
                    task.save(update_fields=["step_seq", "steps", "updated_at"])

                total_reflect_rounds += 1
                suggestions = reflect_payload.get("actionable_suggestions", [])
                assert isinstance(suggestions, list)
                reflector_history_suggestions.extend([str(s).strip() for s in suggestions if str(s).strip()])
                all_reflector_conclusions.append(
                    {
                        "subtask_id": subtask_id,
                        "subtask_title": subtask_title,
                        "round": round_no,
                        "needs_optimization": reflect_payload.get("needs_optimization"),
                        "reason": reflect_payload.get("reason"),
                        "actionable_suggestions": suggestions,
                    }
                )
                accepted = reflect_payload.get("accepted_reader_summary")
                assert isinstance(accepted, dict)
                if reflect_payload.get("needs_optimization") == "yes" and round_no < max_rounds:
                    feedback = "; ".join(suggestions)
                    round_no += 1
                    continue
                final_subtask_summaries.append(
                    {
                        "subtask_id": subtask_id,
                        "subtask_title": subtask_title,
                        "subtask_goal": subtask_goal,
                        "accepted_reader_summary": accepted,
                        "final_round": round_no,
                    }
                )
                break

        with transaction.atomic():
            task = _task_for_update(task_id)
            raw, err = _llm_call(
                phase="write",
                task=task,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_WRITE.format(
                    query=query,
                    plan_text=json.dumps(decision_payload, ensure_ascii=False),
                    analysis_text=json.dumps(final_subtask_summaries, ensure_ascii=False),
                    citations=json.dumps(all_reflector_conclusions, ensure_ascii=False),
                ),
                temperature=0.2,
                max_tokens=6144,
                enable_thinking=True,
                history_limit=2,
            )
            if err:
                _fail_task(task, str(err["code"]), str(err["message"]))
                return
            write_payload, parse_err = _normalize_json(raw or "", "write", task=task)
            if write_payload is None:
                write_payload = {}
            ok, err_msg = _validate_write_json(write_payload, subtasks)
            if not ok:
                _progress_log(task, f"[pipeline_coerce] write 改用子任务摘要拼装: {err_msg}")
                typed_subtasks = [st for st in subtasks if isinstance(st, dict)]
                write_payload = _fallback_write_payload_from_pipeline(
                    query=query,
                    err_msg=err_msg,
                    subtasks=typed_subtasks,
                    final_subtask_summaries=final_subtask_summaries,
                )
                ok2, err2 = _validate_write_json(write_payload, subtasks)
                if not ok2:
                    _progress_log(task, f"[pipeline_coerce] write 容错拼装仍未过校验→终极兜底: {err2}")
                    write_payload = _guaranteed_valid_write_payload(
                        query=query,
                        subtasks_arg=subtasks if isinstance(subtasks, list) else [],
                        summaries=final_subtask_summaries,
                        err_msg=err2 or err_msg or parse_err or "write 不可用",
                    )
            report_body = _markdown_from_write_json(write_payload)
            _append_step(task, "write", "生成报告", _render_write_detail(write_payload, total_reflect_rounds))

            # 混合意图收尾：路由阶段若判定为 research_then_write，把报告写入工作区
            # 指定路径。这一步用 risk_confirmation_strategy="never" 直接执行——用户在
            # 原始请求里就已经明示了"写入 xxx.md"，不再二次拦截。
            post_write = _runtime_config(task).get("post_research_write")
            if isinstance(post_write, dict):
                raw_path = str(post_write.get("path") or "").strip().lstrip("/").lstrip("\\")
                if raw_path:
                    write_result = route_tool_call(
                        tool_name="workspace",
                        args={
                            "action": "write_text",
                            "args": {
                                "path": raw_path,
                                "content": report_body,
                                "overwrite": True,
                            },
                        },
                        risk_confirmation_strategy="never",
                        user_id=str(task.session.owner_id),
                    )
                    write_payload_out = (
                        write_result.payload if isinstance(write_result.payload, dict) else {}
                    )
                    write_audit = (
                        write_payload_out.get("audit", {})
                        if isinstance(write_payload_out, dict)
                        else {}
                    )
                    if not isinstance(write_audit, dict):
                        write_audit = {}
                    if write_result.ok:
                        _append_step(
                            task,
                            "write",
                            "把研究报告写入工作区",
                            f"已将 Markdown 报告写入 `{raw_path}`",
                            audit={
                                **write_audit,
                                "operation_type": "workspace",
                                "tool_type": "workspace",
                                "actor_type": "system",
                                "status": "succeeded",
                            },
                        )
                    else:
                        _append_step(
                            task,
                            "write",
                            "把研究报告写入工作区失败",
                            f"路径 `{raw_path}` 写入失败："
                            f"{write_result.error_code} {write_result.error_message}",
                            audit={
                                **write_audit,
                                "operation_type": "workspace",
                                "tool_type": "workspace",
                                "actor_type": "system",
                                "status": "failed",
                                "is_exception": True,
                                "exception_message": str(write_result.error_message or ""),
                            },
                        )

            task.status = "completed"
            task.intervention = None
            task.result_payload = {
                "format": "markdown",
                "body": report_body,
                "citations": all_citations,
                "attachments": [],
                "pipeline": list(PIPELINE_PHASES),
                "reflect_rounds": total_reflect_rounds,
                "applied_suggestions": reflector_history_suggestions,
                "planner_alternatives": alternatives,
                "decider_decision": decision_payload,
                "subtask_summaries": final_subtask_summaries,
                "all_reflector_conclusions": all_reflector_conclusions,
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
    close_old_connections()
    try:
        task = AgentTask.objects.filter(id=task_id).first()
        if task and is_lite_pipeline(task):
            execute_lite_pipeline(task_id)
            return
        if task and _is_workspace_pipeline(task):
            execute_workspace_pipeline_task(task_id)
            return
        execute_task_pipeline(task_id)
    finally:
        close_old_connections()


def execute_after_revise(task_id: uuid.UUID, message: str) -> None:
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status != "running":
                return
            _append_step(task, "decide", "按修订指令调整", f"已记录修订：{message[:200]}")
            task.save(update_fields=["step_seq", "steps", "updated_at"])
        execute_task_pipeline(task_id)
    finally:
        close_old_connections()


def execute_first_segment(task_id: uuid.UUID) -> None:
    task = AgentTask.objects.filter(id=task_id).first()
    if task and is_lite_pipeline(task):
        execute_lite_pipeline(task_id)
        return
    if task and _is_workspace_pipeline(task):
        execute_workspace_pipeline_task(task_id)
        return
    execute_task_pipeline(task_id)


def start_first_segment_thread(task_id: uuid.UUID) -> None:
    if connection.vendor == "sqlite":
        execute_task_pipeline(task_id)
        return

    def _run() -> None:
        execute_task_pipeline(task_id)

    threading.Thread(target=_run, name=f"ra-mock-{task_id}", daemon=True).start()


def start_workspace_pipeline_thread(task_id: uuid.UUID) -> None:
    if connection.vendor == "sqlite":
        execute_workspace_pipeline_task(task_id)
        return

    def _run() -> None:
        execute_workspace_pipeline_task(task_id)

    threading.Thread(target=_run, name=f"ra-workspace-{task_id}", daemon=True).start()


def start_after_approve_thread(task_id: uuid.UUID) -> None:
    if connection.vendor == "sqlite":
        execute_after_approve(task_id)
        return

    def _run() -> None:
        execute_after_approve(task_id)

    threading.Thread(target=_run, name=f"ra-approve-{task_id}", daemon=True).start()


def start_after_revise_thread(task_id: uuid.UUID, message: str) -> None:
    if connection.vendor == "sqlite":
        execute_after_revise(task_id, message)
        return

    def _run() -> None:
        execute_after_revise(task_id, message)

    threading.Thread(target=_run, name=f"ra-revise-{task_id}", daemon=True).start()
