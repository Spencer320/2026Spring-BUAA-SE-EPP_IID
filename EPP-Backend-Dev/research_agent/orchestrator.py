"""科研助手任务编排引擎：深度研究四阶段流水线（独立 API）及共享工具。"""

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

from .dr_config import resolve_dr_max_reflect_rounds, resolve_dr_phase_llm_config
from .llm_client import (
    chat_completion,
    iter_json_objects_in_text,
    normalize_supplier_json_response,
    pick_reader_json_payload,
    pick_reflector_json_payload,
    pick_searcher_json_payload,
    pick_write_json_payload,
)
from .models import (
    AgentBehaviorAuditLog,
    AgentTask,
    BasicOrchestratorRun,
    ResearchMessage,
    ResearchSession,
    WorkspaceAgentRun,
)
from .prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_ANALYZE,
    USER_PROMPT_PLAN_DECIDE,
    USER_PROMPT_REFLECT,
    USER_PROMPT_WRITE,
)
from .basic_orchestrator import execute_basic_pipeline
from .tools.router import route_tool_call

ACTIVE_STATUSES = frozenset({"pending", "running", "pending_action"})
REPORT_MESSAGE_PREFIX = "[[RA_REPORT]]\n"
PIPELINE_PHASES = ("plan_decide", "analyze", "reflect", "write")
logger = logging.getLogger(__name__)


def _progress_log(task: AgentTask, message: str) -> None:
    text = f"[research_agent][task={task.id}][session={task.session_id}] {message}"
    print(text, flush=True)
    logger.info(text)


_STRUCT_JSON_DIAG_PHASES = frozenset({"plan_decide", "analyze", "reflect", "write"})


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


def _package_sources(raw_sources: list[object]) -> list[dict[str, str]]:
    """将工具检索来源统一包装为稳定结构，供分析/写作/渲染复用。"""
    packed: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip() or "未命名来源"
        url = str(item.get("url", "")).strip()
        domain = str(item.get("domain", "")).strip().lower() or _extract_domain(url)
        snippet = str(item.get("snippet", "")).strip()
        source_type = str(item.get("source_type", "")).strip().lower() or str(
            item.get("source", "")
        ).strip().lower() or "unknown"
        dedupe_key = url or f"{title}|{domain}|{snippet[:80]}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        packed.append(
            {
                "title": title,
                "url": url,
                "domain": domain,
                "snippet": snippet,
                "source_type": source_type,
            }
        )
    packed.sort(key=lambda x: (x.get("domain", ""), x.get("title", ""), x.get("url", "")))
    return packed


def _render_source_references(source_packages: list[dict[str, str]]) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for idx, src in enumerate(source_packages, 1):
        refs.append(
            {
                "id": idx,
                "title": str(src.get("title", "")).strip() or "未命名来源",
                "url": str(src.get("url", "")).strip(),
                "domain": str(src.get("domain", "")).strip(),
                "snippet": str(src.get("snippet", "")).strip(),
                "source_type": str(src.get("source_type", "")).strip() or "unknown",
            }
        )
    return refs


def _with_source_references(
    read_payload: dict[str, object], source_packages: list[dict[str, str]]
) -> dict[str, object]:
    out = _coerce_read_payload_for_pipeline(dict(read_payload))
    out["references"] = _render_source_references(source_packages)
    return out


def _strip_link_payload_for_llm(value: object) -> object:
    """
    发送给 LLM 前去掉链接包装字段，降低 token 并避免要求模型重复输出来源结构。
    链接由后处理代码统一注入。
    """
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, val in value.items():
            if str(key) in {"references", "sources"}:
                continue
            out[str(key)] = _strip_link_payload_for_llm(val)
        return out
    if isinstance(value, list):
        return [_strip_link_payload_for_llm(x) for x in value]
    return value


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
    task: AgentTask | BasicOrchestratorRun | WorkspaceAgentRun,
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
        if phase in {"plan_decide", "analyze", "reflect", "write"}:
            tool_type = "llm"
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

    log_session = task.session
    deep_task: AgentTask | None = None
    basic_run: BasicOrchestratorRun | None = None
    workspace_run: WorkspaceAgentRun | None = None
    if isinstance(task, AgentTask):
        deep_task = task
    elif isinstance(task, BasicOrchestratorRun):
        basic_run = task
    elif isinstance(task, WorkspaceAgentRun):
        workspace_run = task
    else:
        return

    AgentBehaviorAuditLog.objects.create(
        session=log_session,
        deep_task=deep_task,
        basic_run=basic_run,
        workspace_run=workspace_run,
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
    return resolve_dr_max_reflect_rounds(_runtime_config(task))


def _deep_research_augment_user_query(task: AgentTask, query: str) -> str:
    """将独立深度研究 API 传入的 ``selected_papers`` 拼入规划用用户文本（后续阶段可再结构化消费）。"""
    cfg = _runtime_config(task)
    papers = cfg.get("selected_papers")
    if not isinstance(papers, list) or not papers:
        return query
    try:
        blob = json.dumps(papers, ensure_ascii=False)[:8000]
    except (TypeError, ValueError):
        blob = str(papers)[:8000]
    appendix = (
        "\n\n【独立深度研究 · 用户选定文献（标识列表；管线内各阶段 TODO 精细消费）】\n" + blob
    )
    return (query + appendix)[:50000]


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
) -> tuple[str | None, dict[str, object] | None]:
    messages = _build_conversation_messages(
        task=task,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        history_limit=history_limit,
    )
    base_kwargs: dict[str, Any] = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    attempts: list[dict[str, Any]] = [
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
            if "messages" in msg or "enable_thinking" in msg or "unexpected keyword argument" in msg:
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


def _llm_call_for_phase(
    *,
    phase: str,
    task: AgentTask,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str | None, dict[str, object] | None]:
    phase_cfg = resolve_dr_phase_llm_config(_runtime_config(task), phase=phase)
    return _llm_call(
        phase=phase,
        task=task,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=phase_cfg.temperature,
        max_tokens=phase_cfg.max_tokens,
        enable_thinking=phase_cfg.enable_thinking,
        history_limit=phase_cfg.history_limit,
    )


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
    if task is not None and phase in {"analyze", "reflect", "write"}:
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
    if isinstance(payload, dict):
        top_keys_list = [str(k) for k in list(payload.keys())[:32]]
    _struct_json_diag(
        task,
        phase,
        step="after_supplier_normalize",
        payload_is_none=payload is None,
        parse_err_short=str(parse_err or "")[:500],
        top_level_keys=top_keys_list,
    )

    if payload is None:
        picked: dict[str, object] | None = None
        if phase == "analyze":
            picked_search = pick_searcher_json_payload(raw_s)
            picked_read = pick_reader_json_payload(raw_s)
            if picked_search is not None or picked_read is not None:
                merged_analyze: dict[str, object] = {}
                if isinstance(picked_search, dict):
                    merged_analyze.update(picked_search)
                if isinstance(picked_read, dict):
                    merged_analyze.update(picked_read)
                picked = merged_analyze
        elif phase == "reflect":
            picked = pick_reflector_json_payload(raw_s)
        elif phase == "write":
            picked = pick_write_json_payload(raw_s)
        if picked is not None:
            payload = picked
            parse_err = None
        elif phase in {"analyze", "reflect", "write"}:
            if phase == "analyze":
                _log_search_json_parse_diag(
                    task,
                    raw,
                    reason="normalize_supplier_json_response 返回 None 且片段恢复无果",
                    parse_detail=parse_err or "",
                )
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

    assert isinstance(payload, dict)

    if payload.get("_fallback_wrapped"):
        # 供应商/解析层写入的占位对象：尝试从 raw 片段恢复结构化 JSON。
        legacy_detail = str(payload.get("_fallback_error", "") or "")[:200]
        hist_raw = payload.get("raw_text")
        pick_src = raw_s if not (isinstance(hist_raw, str) and hist_raw.strip()) else str(hist_raw)
        picked_fb: dict[str, object] | None = None
        if phase == "analyze":
            picked_search_fb = pick_searcher_json_payload(pick_src)
            picked_read_fb = pick_reader_json_payload(pick_src)
            if picked_search_fb is not None or picked_read_fb is not None:
                picked_fb = {}
                if isinstance(picked_search_fb, dict):
                    picked_fb.update(picked_search_fb)
                if isinstance(picked_read_fb, dict):
                    picked_fb.update(picked_read_fb)
        elif phase == "reflect":
            picked_fb = pick_reflector_json_payload(pick_src)
        elif phase == "write":
            picked_fb = pick_write_json_payload(pick_src)
        elif phase not in {"analyze", "reflect", "write"}:
            return None, f"{phase}阶段JSON无效: 无法解析合法 JSON"
        payload = picked_fb if picked_fb is not None else {}
        if phase == "analyze" and not payload:
            _log_search_json_parse_diag(
                task,
                raw,
                reason="_fallback_wrapped 且片段恢复无果",
                parse_detail=legacy_detail,
            )
    elif phase == "analyze":
        groups = payload.get("info_groups")
        if not isinstance(groups, list) or not groups:
            picked = pick_searcher_json_payload(raw or "")
            if picked is not None:
                payload = {**payload, **picked}
        ana_chk = payload.get("analysis")
        if not isinstance(ana_chk, str) or not ana_chk.strip():
            _struct_json_diag(
                task,
                "analyze",
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
                        "[pipeline_coerce] analyze 首段对象缺少 analysis，已改用片段扫描结果",
                    )
                _struct_json_diag(
                    task,
                    "analyze",
                    step="adopt_fragment_pick_reader",
                    picked_keys=[str(k) for k in list(alt_rd.keys())[:24]],
                    picked_analysis_len=len(str(alt_rd.get("analysis", ""))),
                )
                payload = {**payload, **alt_rd}
            else:
                _struct_json_diag(
                    task,
                    "analyze",
                    step="fragment_pick_failed_will_use_empty_then_coerce",
                )
    elif phase == "reflect" and isinstance(payload, dict):
        no = payload.get("needs_optimization")
        reason_text = payload.get("reason")
        frag = False
        frag_reason = ""
        if no is None:
            frag = True
            frag_reason = "needs_optimization 缺失"
        elif not isinstance(reason_text, str) or not reason_text.strip():
            frag = True
            frag_reason = "reason 缺失或为空"
        if frag:
            _struct_json_diag(
                task,
                "reflect",
                step="first_pass_incomplete",
                reason=frag_reason,
                first_pass_keys=[str(k) for k in list(payload.keys())[:28]],
                needs_optimization_type=type(no).__name__,
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
    elif phase == "write" and isinstance(payload, dict):
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
        still_fallback_wrapped=False,
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


def _coerce_plan_decide_payload(payload: dict[str, object]) -> dict[str, object]:
    out = dict(payload)
    out = _coerce_decider_payload(out)
    alternatives = out.get("alternatives")
    if not isinstance(alternatives, list):
        out["alternatives"] = []
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
    
    refs = out.get("references")
    if isinstance(refs, list):
        out["references"] = [r for r in refs if isinstance(r, dict)]
    else:
        out["references"] = []
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
        "references": [],
    }


def _coerce_reflect_payload(
    payload: dict[str, object],
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
    return out


def _fallback_reflect_payload_from_read() -> dict[str, object]:
    return {
        "needs_optimization": "no",
        "reason": "反思阶段结构化输出未通过校验：系统已终止优化回路并直接使用阅读摘要推进后续流水线。",
        "actionable_suggestions": [],
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
    all_refs: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for item in final_subtask_summaries:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("subtask_id", "")).strip()
        if not sid:
            continue
        acc = item.get("reader_summary")
        ana = ""
        if isinstance(acc, dict):
            ana = str(acc.get("analysis", "")).strip()
            refs = acc.get("references")
            if isinstance(refs, list):
                for r in refs:
                    if isinstance(r, dict):
                        u = str(r.get("url", "")).strip()
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            all_refs.append(r)
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
        "references": all_refs,
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
                "rationale": "plan_decide 阶段模型结构化输出不可用，系统自动注入占位方案（A）。",
            },
            {
                "plan_id": "plan-hard-b",
                "title": "两步深化路线",
                "steps": ["梳理背景与时间线／术语边界", "按关键主题补充对比与方法论局限"],
                "rationale": "plan_decide 阶段模型结构化输出不可用，系统自动注入占位方案（B）。",
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
        "decision_reason": "plan_decide 阶段模型输出不可用或校验失败：系统降级为单步子任务，避免中断深度研究流水线。",
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


def _hard_fallback_plan_decide_payload(query: str) -> dict[str, object]:
    alternatives = list(_hard_fallback_plan_payload(query).get("alternatives", []))
    decision = _hard_fallback_decision_payload(alternatives, query)
    return {
        "alternatives": alternatives,
        "selected_plan_id": decision.get("selected_plan_id", ""),
        "decision_reason": decision.get("decision_reason", ""),
        "complexity": decision.get("complexity", "simple"),
        "merge_attempt_note": decision.get("merge_attempt_note", ""),
        "subtasks": decision.get("subtasks", []),
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
    all_refs: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for item in summaries:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("subtask_id", "") or "").strip()
        if not sid:
            continue
        acc = item.get("reader_summary")
        txt = ""
        if isinstance(acc, dict):
            txt = str(acc.get("analysis", "") or "").strip()
            refs = acc.get("references")
            if isinstance(refs, list):
                for r in refs:
                    if isinstance(r, dict):
                        u = str(r.get("url", "")).strip()
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            all_refs.append(r)
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
        "references": all_refs,
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


def _validate_plan_decide_json(payload: dict[str, object]) -> tuple[bool, str]:
    ok, err = _validate_planner_json(payload)
    if not ok:
        return ok, err
    alternatives = payload.get("alternatives")
    assert isinstance(alternatives, list)
    return _validate_decider_json(payload, [x for x in alternatives if isinstance(x, dict)])


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


def _validate_analyze_json(payload: dict[str, object]) -> tuple[bool, str]:
    ok, err = _validate_searcher_json(payload)
    if not ok:
        return ok, err
    return _validate_read_json(payload)


def _validate_read_json(payload: dict[str, object]) -> tuple[bool, str]:
    if not isinstance(payload.get("analysis"), str) or not str(payload.get("analysis")).strip():
        return False, "analysis must be non-empty string"
    if not isinstance(payload.get("key_points"), list) or any(not isinstance(x, str) for x in payload.get("key_points", [])):
        return False, "key_points must be string list"
    if not isinstance(payload.get("limitations"), list) or any(not isinstance(x, str) for x in payload.get("limitations", [])):
        return False, "limitations must be string list"
    refs = payload.get("references")
    if refs is not None and not isinstance(refs, list):
        return False, "references must be a list"
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
    refs = payload.get("references")
    if refs is not None and not isinstance(refs, list):
        return False, "references must be a list"
    return True, ""


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
    
    references = payload.get("references", [])
    if isinstance(references, list) and references:
        parts.append("\n## 参考来源")
        for idx, ref in enumerate(references, 1):
            if not isinstance(ref, dict):
                continue
            rid_raw = ref.get("id")
            rid = int(rid_raw) if isinstance(rid_raw, int) and rid_raw > 0 else idx
            rtitle = str(ref.get("title", "")).strip()
            rurl = str(ref.get("url", "")).strip()
            domain = str(ref.get("domain", "")).strip() or _extract_domain(rurl)
            source_type = str(ref.get("source_type", "")).strip() or "unknown"
            snippet = str(ref.get("snippet", "")).strip()
            note = f"（{source_type} · {domain or 'unknown'}）"
            if rtitle and rurl:
                parts.append(f"[{rid}] [{rtitle}]({rurl}) {note}")
            elif rtitle:
                parts.append(f"[{rid}] {rtitle} {note}")
            if snippet:
                parts.append(f"  - 摘要：{snippet[:160]}")

    return "\n".join(parts).strip()


def _search_context(query: str) -> tuple[str, list[dict[str, str]], dict[str, str] | None, dict[str, object]]:
    url = (getattr(settings, "RA_OUTBOUND_DEMO_URL", "") or "").strip()
    routed = route_tool_call(tool_name="web_search", args={"query": query, "url": url})
    if not routed.ok:
        code = str(routed.error_code or "")
        if code.startswith("WEB_SEARCH_") or code.startswith("ACADEMIC_") or code.startswith(
            "WEB_OPERATOR_"
        ):
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


def _maybe_run_local_command(task: AgentTask, query: str) -> dict[str, object] | None:
    _ = query
    cfg = _runtime_config(task)
    if bool(cfg.get("local_command_executed")):
        return None
    local_cmd = cfg.get("local_command")
    if not isinstance(local_cmd, dict):
        return None
    # FR-KYZS-0007 is deprecated: do not execute or pause for legacy local tools.
    return None


def _maybe_run_local_file_action(task: AgentTask) -> dict[str, object] | None:
    cfg = _runtime_config(task)
    if bool(cfg.get("local_file_action_executed")):
        return None
    action_cfg = cfg.get("local_file_action")
    if not isinstance(action_cfg, dict):
        return None
    # FR-KYZS-0007 is deprecated: do not execute or pause for legacy local tools.
    return None


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


def execute_deep_research_pipeline(task_id: uuid.UUID) -> None:
    """独立深度研究四阶段流水线（仅 ``AgentTask`` 深度研究实体）。"""
    close_old_connections()
    try:
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status not in ("pending", "running"):
                return
            if task.status == "pending":
                task.status = "running"
                task.save(update_fields=["status", "updated_at"])
            _progress_log(task, "启动深度研究（独立 API）四阶段流水线")

        with transaction.atomic():
            task = _task_for_update(task_id)
            query = _latest_user_query(task)
            max_rounds = _max_reflect_rounds(task)

        query = _deep_research_augment_user_query(task, query)

        all_citations: list[dict[str, str]] = []
        all_source_packages: list[dict[str, str]] = []
        reflect_decisions: list[dict[str, object]] = []
        final_subtask_summaries: list[dict[str, object]] = []
        analyze_phase_outputs: list[dict[str, object]] = []
        reflect_phase_outputs: list[dict[str, object]] = []
        reflector_history_suggestions: list[str] = []
        total_reflect_rounds = 0

        with transaction.atomic():
            task = _task_for_update(task_id)
            raw, err = _llm_call_for_phase(
                phase="plan_decide",
                task=task,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_PLAN_DECIDE.format(
                    query=query,
                    suggestions=json.dumps(reflector_history_suggestions, ensure_ascii=False),
                ),
            )
            if err:
                _fail_task(task, str(err["code"]), str(err["message"]))
                return
            plan_decide_payload, parse_err = _normalize_json(raw or "", "plan_decide", task=task)
            if plan_decide_payload is None:
                _progress_log(task, f"[pipeline_coerce] plan_decide 解析失败→硬兜底: {parse_err}")
                plan_decide_payload = _hard_fallback_plan_decide_payload(query)
            plan_decide_payload = _coerce_plan_decide_payload(plan_decide_payload)
            ok, err_msg = _validate_plan_decide_json(plan_decide_payload)
            if not ok:
                _progress_log(task, f"[pipeline_coerce] plan_decide 校验失败→硬兜底: {err_msg}")
                plan_decide_payload = _hard_fallback_plan_decide_payload(query)
            plan_decide_payload = _coerce_plan_decide_payload(plan_decide_payload)
            _append_step(task, "plan_decide", "规划与决策", "已输出备选方案与子任务拆解")
            task.save(update_fields=["step_seq", "steps", "updated_at"])

        alternatives_raw = plan_decide_payload.get("alternatives", [])
        assert isinstance(alternatives_raw, list)
        alternatives = [
            dict(x)
            for x in alternatives_raw
            if isinstance(x, dict) and str(x.get("plan_id", "")).strip()
        ]
        if len(alternatives) < 2:
            alternatives = list(_hard_fallback_plan_payload(query)["alternatives"])
        decision_payload = {
            "selected_plan_id": plan_decide_payload.get("selected_plan_id"),
            "decision_reason": plan_decide_payload.get("decision_reason"),
            "complexity": plan_decide_payload.get("complexity"),
            "merge_attempt_note": plan_decide_payload.get("merge_attempt_note"),
            "subtasks": plan_decide_payload.get("subtasks", []),
        }
        decision_payload = _coerce_decider_payload(decision_payload)

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
                search_detail, citations, fatal, search_audit = _search_context(subtask_goal)
                if fatal:
                    fatal_audit = search_audit if isinstance(search_audit, dict) else {}
                    fatal_meta = fatal_audit.get("meta") if isinstance(fatal_audit.get("meta"), dict) else {}
                    with transaction.atomic():
                        task = _task_for_update(task_id)
                        _append_step(
                            task,
                            "analyze",
                            f"分析失败：{subtask_title}",
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
                source_packages = _package_sources(citations)
                all_source_packages.extend(source_packages)

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    analyze_prompt = USER_PROMPT_ANALYZE.format(
                        query=query,
                        plan_text=subtask_title,
                        reflect_round=round_no,
                        max_rounds=max_rounds,
                        search_results=(
                            json.dumps(source_packages, ensure_ascii=False) if source_packages else "无检索结果"
                        ),
                    )
                    if feedback:
                        analyze_prompt += f"\nprevious_reflector_feedback: {feedback}"
                    raw, err = _llm_call_for_phase(
                        phase="analyze",
                        task=task,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=analyze_prompt,
                    )
                    if err:
                        _fail_task(task, str(err["code"]), str(err["message"]))
                        return
                    analyze_payload, parse_err = _normalize_json(raw or "", "analyze", task=task)
                    if analyze_payload is None:
                        _progress_log(task, f"[pipeline_coerce] analyze 解析失败→空壳后强制补齐: {parse_err}")
                        analyze_payload = {}
                    analyze_payload = _ensure_searcher_minimal_groups(
                        analyze_payload, subtask_goal=subtask_goal
                    )
                    analyze_payload = _coerce_searcher_payload(analyze_payload)
                    analyze_payload = _coerce_read_payload_for_pipeline(analyze_payload)
                    ok, err_msg = _validate_analyze_json(analyze_payload)
                    if not ok:
                        _progress_log(
                            task,
                            f"[pipeline_coerce] analyze 一次校验未通过，尝试字段级修复: {err_msg}",
                        )
                        analyze_payload = _repair_search_payload_for_validator(
                            analyze_payload, subtask_goal=subtask_goal
                        )
                        analyze_payload = _coerce_read_payload_for_pipeline(analyze_payload)
                        ok, err_msg = _validate_analyze_json(analyze_payload)
                    if not ok:
                        _progress_log(
                            task,
                            f"[pipeline_coerce] analyze 仍失败，再次强制 repair: {err_msg}",
                        )
                        analyze_payload = _repair_search_payload_for_validator(
                            {}, subtask_goal=subtask_goal
                        )
                        analyze_payload = _coerce_read_payload_for_pipeline(analyze_payload)
                        ok, err_msg = _validate_analyze_json(analyze_payload)
                    if not ok:
                        analyze_payload = _ensure_searcher_minimal_groups({}, subtask_goal=subtask_goal)
                        analyze_payload = _coerce_read_payload_for_pipeline(analyze_payload)

                info_groups = analyze_payload.get("info_groups")
                assert isinstance(info_groups, list)

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    search_step_audit = search_audit if isinstance(search_audit, dict) else {}
                    analyze_detail = "\n\n".join(
                        [
                            _render_search_detail(subtask, round_no, analyze_payload, search_detail, search_audit),
                            _render_read_detail(subtask, round_no, analyze_payload),
                        ]
                    )
                    _append_step(
                        task,
                        "analyze",
                        f"分析子任务：{subtask_title}",
                        analyze_detail,
                        audit={
                            **search_step_audit,
                            "operation_type": "web_search",
                            "tool_type": "web_search",
                            "status": search_step_audit.get("status") or "succeeded",
                            "actor_type": "system",
                        },
                    )
                    task.save(update_fields=["step_seq", "steps", "updated_at"])

                analyze_phase_outputs.append(
                    {
                        "subtask_id": subtask_id,
                        "subtask_title": subtask_title,
                        "subtask_goal": subtask_goal,
                        "round": round_no,
                        "analyze_payload": analyze_payload,
                        "source_packages": source_packages,
                        "search_detail": search_detail,
                        "citations_count": len(citations),
                    }
                )

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
                                local_cmd_status = "pending_action"
                            elif local_cmd_result.get("ok"):
                                local_cmd_status = "succeeded"
                            else:
                                local_cmd_status = "failed"
                        _append_step(
                            task,
                            "analyze",
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
                            task.status = "pending_action"
                            task.intervention = local_cmd_result["confirmation_payload"]
                            task.save(update_fields=["status", "intervention", "step_seq", "steps", "updated_at"])
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
                                local_file_status = "pending_action"
                            elif local_file_result.get("ok"):
                                local_file_status = "succeeded"
                            else:
                                local_file_status = "failed"
                        _append_step(
                            task,
                            "analyze",
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
                            task.status = "pending_action"
                            task.intervention = local_file_result["confirmation_payload"]
                            task.save(update_fields=["status", "intervention", "step_seq", "steps", "updated_at"])
                            return
                        if not local_file_result["ok"]:
                            _fail_task(task, str(local_file_result.get("error_code") or "LOCAL_FILE_FAILED"), str(local_file_result.get("error_message") or "本地文件执行失败"))
                            return
                        _update_runtime_config(task, local_file_action_executed=True)
                        task.save(update_fields=["result_payload", "step_seq", "steps", "updated_at"])

                read_payload = _coerce_read_payload_for_pipeline(dict(analyze_payload))
                ok, err_msg = _validate_read_json(read_payload)
                if not ok:
                    _progress_log(task, f"[pipeline_coerce] analyze/read_summary 改用 info_groups 降级: {err_msg}")
                    read_payload = _read_fallback_from_info_groups(info_groups, err_msg)
                read_payload = _with_source_references(read_payload, source_packages)

                with transaction.atomic():
                    task = _task_for_update(task_id)
                    raw, err = _llm_call_for_phase(
                        phase="reflect",
                        task=task,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=USER_PROMPT_REFLECT.format(
                            plan_text=json.dumps(subtask, ensure_ascii=False),
                            analysis_text=json.dumps(
                                _strip_link_payload_for_llm(read_payload), ensure_ascii=False
                            ),
                            reflect_round=round_no,
                            max_rounds=max_rounds,
                        ),
                    )
                    if err:
                        _fail_task(task, str(err["code"]), str(err["message"]))
                        return
                    reflect_payload, parse_err = _normalize_json(raw or "", "reflect", task=task)
                    if reflect_payload is None:
                        reflect_payload = {}
                    reflect_payload = _coerce_reflect_payload(reflect_payload)
                    ok, err_msg = _validate_reflector_json(reflect_payload)
                    if not ok:
                        _progress_log(task, f"[pipeline_coerce] reflect 沿用阅读摘要兜底: {err_msg}")
                        reflect_payload = _fallback_reflect_payload_from_read()
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
                reflect_decisions.append(
                    {
                        "subtask_id": subtask_id,
                        "subtask_title": subtask_title,
                        "round": round_no,
                        "needs_optimization": reflect_payload.get("needs_optimization"),
                        "reason": reflect_payload.get("reason"),
                        "actionable_suggestions": suggestions,
                    }
                )
                reflect_phase_outputs.append(
                    {
                        "subtask_id": subtask_id,
                        "subtask_title": subtask_title,
                        "subtask_goal": subtask_goal,
                        "round": round_no,
                        "needs_optimization": reflect_payload.get("needs_optimization"),
                        "reason": reflect_payload.get("reason"),
                        "actionable_suggestions": suggestions,
                    }
                )
                if reflect_payload.get("needs_optimization") == "yes" and round_no < max_rounds:
                    feedback = "; ".join(suggestions)
                    round_no += 1
                    continue
                final_subtask_summaries.append(
                    {
                        "subtask_id": subtask_id,
                        "subtask_title": subtask_title,
                        "subtask_goal": subtask_goal,
                        "reader_summary": read_payload,
                        "final_round": round_no,
                    }
                )
                break

        with transaction.atomic():
            task = _task_for_update(task_id)
            raw, err = _llm_call_for_phase(
                phase="write",
                task=task,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=USER_PROMPT_WRITE.format(
                    query=query,
                    plan_text=json.dumps(decision_payload, ensure_ascii=False),
                    analysis_text=json.dumps(
                        _strip_link_payload_for_llm(final_subtask_summaries), ensure_ascii=False
                    ),
                    citations=json.dumps(reflect_decisions, ensure_ascii=False),
                ),
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
            all_source_packages = _package_sources(all_source_packages)
            write_payload["references"] = _render_source_references(all_source_packages)
            report_body = _markdown_from_write_json(write_payload)
            _append_step(task, "write", "生成报告", _render_write_detail(write_payload, total_reflect_rounds))

            task.status = "completed"
            task.intervention = None
            task.result_payload = {
                "format": "markdown",
                "body": report_body,
                "citations": all_source_packages,
                "attachments": [],
                "pipeline": list(PIPELINE_PHASES),
                "reflect_rounds": total_reflect_rounds,
                "applied_suggestions": reflector_history_suggestions,
                "phase_outputs": {
                    "plan_decide": plan_decide_payload,
                    "analyze": analyze_phase_outputs,
                    "reflect": reflect_phase_outputs,
                    "write": write_payload,
                },
                "reflect_decisions": reflect_decisions,
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
        if BasicOrchestratorRun.objects.filter(id=task_id).exists():
            execute_basic_pipeline(task_id)
            return
        if AgentTask.objects.filter(id=task_id).exists():
            execute_deep_research_pipeline(task_id)
    finally:
        close_old_connections()


def execute_after_revise(task_id: uuid.UUID, message: str) -> None:
    """仅深度研究 ``AgentTask`` 支持「修订后继续」语义。"""
    close_old_connections()
    try:
        if not AgentTask.objects.filter(id=task_id).exists():
            return
        with transaction.atomic():
            task = _task_for_update(task_id)
            if task.status != "running":
                return
            _append_step(task, "plan_decide", "按修订指令调整", f"已记录修订：{message[:200]}")
            task.save(update_fields=["step_seq", "steps", "updated_at"])
        execute_deep_research_pipeline(task_id)
    finally:
        close_old_connections()


def start_first_segment_thread(task_id: uuid.UUID) -> None:
    """会话类用户请求：仅启动 basic 编排器（与深度研究独立 API 分离）。"""
    if connection.vendor == "sqlite":
        execute_basic_pipeline(task_id)
        return

    def _run() -> None:
        execute_basic_pipeline(task_id)

    threading.Thread(target=_run, name=f"ra-basic-{task_id}", daemon=True).start()


def start_deep_research_thread(task_id: uuid.UUID) -> None:
    """独立深度研究 API 创建任务后调用。"""
    if connection.vendor == "sqlite":
        execute_deep_research_pipeline(task_id)
        return

    def _run() -> None:
        execute_deep_research_pipeline(task_id)

    threading.Thread(target=_run, name=f"ra-deep-{task_id}", daemon=True).start()


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
