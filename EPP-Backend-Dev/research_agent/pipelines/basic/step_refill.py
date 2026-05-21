"""
basic 编排器步间「轻量补参」：在第 2 步及以后，根据前置链路与上一步输出，
为 search / agent / chat 填写首轮规划中留空的 query、delegate_prompt、prompt。
"""

from __future__ import annotations

import time
from typing import Any

from research_agent.llm_client import chat_completion, normalize_supplier_json_response
from research_agent.prompts import STEP_REFILL_SYSTEM_PROMPT, STEP_REFILL_USER_PROMPT


def rule_based_fill_step(step: dict[str, Any]) -> dict[str, Any]:
    st = str(step.get("type") or "").lower().strip()
    intent = str(step.get("intent") or step.get("title") or "").strip()
    if not intent:
        return {}
    if st == "search":
        return {"query": intent[:2000]}
    if st == "agent":
        body = f"请结合「前置子任务结果」完成以下意图（可调用工作区工具）：\n{intent}"
        return {"delegate_prompt": body[:8000]}
    if st == "chat":
        return {"prompt": intent[:4000]}
    return {}


def fill_deferred_step_params(
    *,
    step: dict[str, Any],
    user_query: str,
    prior_chain: str,
    last_step_type: str,
    last_step_title: str,
    last_output: str,
    session_context: str = "",
) -> dict[str, Any]:
    """
    返回应合并进 step 的字段子集（仅含非空 query / delegate_prompt / prompt）。

    先尝试 LLM；失败或解析为空时使用 ``intent``/``title`` 的规则兜底。
    """
    step_type = str(step.get("type") or "").strip().lower()
    title = str(step.get("title") or "").strip()
    intent = str(step.get("intent") or "").strip()
    sc = (session_context or "").strip() or "（无）"
    up = STEP_REFILL_USER_PROMPT.format(
        user_query=(user_query or "").strip()[:8000],
        session_context=sc[:24000],
        prior_chain=(prior_chain or "").strip()[:24000],
        last_step_type=last_step_type or "unknown",
        last_step_title=(last_step_title or "").strip()[:500],
        last_output=(last_output or "").strip()[:12000],
        next_step_type=step_type,
        next_step_title=title[:500],
        next_step_intent=intent[:2000],
        next_step_json=_compact_step_for_prompt(step),
    )
    started = time.monotonic()
    res = chat_completion(
        system_prompt=STEP_REFILL_SYSTEM_PROMPT,
        user_prompt=up,
        temperature=0.15,
        max_tokens=900,
        enable_thinking=False,
        stream=False,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    merged: dict[str, Any] = {}
    if res.ok and (res.content or "").strip():
        payload, err = normalize_supplier_json_response(res.content or "")
        if payload is not None and isinstance(payload, dict) and not payload.get("_fallback_wrapped"):
            merged = _pick_refill_keys(step_type, payload)
    if merged:
        print(
            f"[research_agent][step_refill] LLM ok type={step_type} keys={list(merged.keys())} "
            f"latency_ms={elapsed_ms}",
            flush=True,
        )
        return merged
    print(
        f"[research_agent][step_refill] LLM skip/fail type={step_type} "
        f"ok={res.ok} err={getattr(res, 'error_code', '')} latency_ms={elapsed_ms} → rule_based",
        flush=True,
    )
    return rule_based_fill_step(step)


def _compact_step_for_prompt(step: dict[str, Any]) -> str:
    import json

    slim = {k: step.get(k) for k in ("type", "title", "intent", "query", "delegate_prompt", "prompt") if k in step}
    try:
        return json.dumps(slim, ensure_ascii=False)[:1200]
    except TypeError:
        return str(slim)[:1200]


def _pick_refill_keys(step_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if step_type == "search":
        q = str(payload.get("query") or "").strip()
        if q:
            out["query"] = q[:2000]
    elif step_type == "agent":
        d = str(payload.get("delegate_prompt") or payload.get("delegate") or "").strip()
        if d:
            out["delegate_prompt"] = d[:8000]
    elif step_type == "chat":
        p = str(payload.get("prompt") or payload.get("instruction") or "").strip()
        if p:
            out["prompt"] = p[:4000]
    return out


def merge_refill_into_step(step: dict[str, Any], refill: dict[str, Any]) -> dict[str, Any]:
    out = dict(step)
    st = str(out.get("type") or "").lower().strip()
    if st == "search":
        q = str(refill.get("query") or "").strip()
        if q:
            out["query"] = q[:2000]
    elif st == "agent":
        d = str(refill.get("delegate_prompt") or "").strip()
        if d:
            out["delegate_prompt"] = d[:8000]
    elif st == "chat":
        p = str(refill.get("prompt") or "").strip()
        if p:
            out["prompt"] = p[:4000]
    return out


def step_needs_param_refill(step_index: int, step: dict[str, Any]) -> bool:
    """仅第 2 步及以后，且对应参数字段为空时需要补全。"""
    if step_index <= 0:
        return False
    st = str(step.get("type") or "").strip().lower()
    if st == "search":
        return not str(step.get("query") or "").strip()
    if st == "agent":
        return not str(step.get("delegate_prompt") or "").strip()
    if st == "chat":
        return not str(step.get("prompt") or "").strip()
    return False
