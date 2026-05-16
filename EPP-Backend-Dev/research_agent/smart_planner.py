"""
统一智能任务拆解器（Smart Planner）。

服务 **basic 编排器**：将用户输入拆解为有序子任务，步骤类型为 **chat** / **search** / **agent**。

- chat：单次轻量对话。
- search：学术文献检索；首轮可只写 ``intent`` 而将 ``query`` 留空，由步间补全（见 ``step_refill``）。
- agent：工作区相关重任务；首轮可只写 ``intent`` 而将 ``delegate_prompt`` 留空，由步间补全。

输出固定 schema；失败返回 ``None``，由调用方使用 ``fallback_chat_plan``。
"""

from __future__ import annotations

import time
from typing import Any

from .llm_client import chat_completion, normalize_supplier_json_response
from .prompts import SMART_PLANNER_SYSTEM_PROMPT, SMART_PLANNER_USER_PROMPT

_ALLOWED_STEP_TYPES = frozenset({"chat", "search", "agent"})


def _norm_path(raw: object) -> str:
    text = str(raw or "").strip()
    text = text.lstrip("/").lstrip("\\")
    return text.replace("\\", "/")


def _intent_effective(raw: dict[str, Any], title: str) -> str:
    return (
        str(raw.get("intent") or raw.get("action_summary") or "").strip() or (title or "").strip()
    )[:800]


def _validate_step(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    step_type = str(raw.get("type") or "").strip().lower()
    if step_type not in _ALLOWED_STEP_TYPES:
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None

    if step_type == "chat":
        prompt_text = str(raw.get("prompt") or raw.get("instruction") or "").strip()
        intent_text = _intent_effective(raw, title)
        use_history = raw.get("use_history", True)
        return {
            "type": "chat",
            "title": title[:120],
            "prompt": prompt_text[:4000],
            "intent": intent_text[:800],
            "use_history": bool(use_history),
        }

    if step_type == "search":
        query = str(raw.get("query") or raw.get("goal") or "").strip()
        intent_text = _intent_effective(raw, title)
        out: dict[str, Any] = {
            "type": "search",
            "title": title[:120],
            "query": query[:2000],
            "intent": intent_text[:800],
        }
        post_path = _norm_path(raw.get("post_write_path") or raw.get("post_write") or "")
        if post_path:
            out["post_write_path"] = post_path[:512]
        return out

    delegate = str(raw.get("delegate_prompt") or raw.get("prompt") or "").strip()
    intent_text = _intent_effective(raw, title)
    return {
        "type": "agent",
        "title": title[:120],
        "delegate_prompt": delegate[:8000],
        "intent": intent_text[:800],
    }


def _validate_plan(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return None
    cleaned_steps: list[dict[str, Any]] = []
    for raw in raw_steps[:8]:
        validated = _validate_step(raw)
        if validated is None:
            return None
        cleaned_steps.append(validated)
    if not cleaned_steps:
        return None
    summary = str(payload.get("summary") or "").strip()
    return {
        "summary": summary[:300],
        "steps": cleaned_steps,
    }


def _llm_smart_plan(
    query: str,
    *,
    dialog_context: str = "",
    workspace_context: str = "",
) -> dict[str, Any] | None:
    user_prompt = SMART_PLANNER_USER_PROMPT.format(query=query)
    extras: list[str] = []
    if (dialog_context or "").strip():
        extras.append("## 近期对话（不含本轮最新用户句，最多 3 轮）\n" + dialog_context.strip()[:24000])
    if (workspace_context or "").strip():
        extras.append(workspace_context.strip()[:12000])
    if extras:
        user_prompt = user_prompt + "\n\n" + "\n\n".join(extras)
    started = time.monotonic()
    res = chat_completion(
        system_prompt=SMART_PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=1100,
        enable_thinking=False,
        stream=False,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not res.ok:
        print(
            f"[research_agent][smart_planner] LLM 规划失败: "
            f"{res.error_code} {res.error_message} latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    payload, err = normalize_supplier_json_response(res.content)
    if payload is None:
        print(
            f"[research_agent][smart_planner] LLM 响应 JSON 解析失败: {err} "
            f"latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    if payload.get("_fallback_wrapped"):
        print(
            f"[research_agent][smart_planner] LLM 响应非合法 JSON 已放弃 "
            f"latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    plan = _validate_plan(payload)
    if plan is None:
        print(
            f"[research_agent][smart_planner] 规划结果未通过校验 latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    type_summary = ",".join(step["type"] for step in plan["steps"])
    print(
        "[research_agent][smart_planner] 规划成功: "
        f"steps={len(plan['steps'])} types=[{type_summary}] latency_ms={elapsed_ms}",
        flush=True,
    )
    return plan


def detect_smart_plan(
    content: str,
    *,
    dialog_context: str = "",
    workspace_context: str = "",
) -> dict[str, Any] | None:
    """生成 chat / search / agent 子任务拆解。"""
    text = (content or "").strip()
    if not text:
        return None
    return _llm_smart_plan(
        text,
        dialog_context=dialog_context,
        workspace_context=workspace_context,
    )


def fallback_chat_plan(content: str) -> dict[str, Any]:
    """规划失败时的兜底：单步 chat。"""
    text = (content or "").strip() or "请回应用户的请求"
    return {
        "summary": "fallback chat",
        "steps": [
            {
                "type": "chat",
                "title": "直接回复用户",
                "prompt": text[:4000],
                "use_history": True,
            }
        ],
    }
