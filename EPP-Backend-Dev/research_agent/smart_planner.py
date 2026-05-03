"""
统一智能任务拆解器（Smart Planner）。

设计目标：
- 把用户的整段自然语言请求拆解为有序、可独立执行的『步骤』，每个 step 标记 type，
  目前支持三种类型：

    * ``chat``      —— LLM 直接对话/创作，不调用任何外部工具；
    * ``workspace`` —— 工作区文件 / 目录操作；
    * ``research``  —— 需要联网检索 + 多轮反思的深度研究子任务。

- 与旧的 :pyfile:`workspace_intent.py` 不同：旧路由把请求分为
  「纯研究 / 纯工作区 / 研究后写入」三种『模式』，本规划器允许同一请求中混合
  多个不同 type 的步骤，由编排器按数组顺序串行执行。

- 输出固定 schema，由 :pyfunc:`detect_smart_plan` 调用 LLM 后做结构校验，
  失败则返回 ``None`` 让编排器降级到简单 chat。
"""

from __future__ import annotations

import time
from typing import Any

from .llm_client import chat_completion, normalize_supplier_json_response
from .prompts import SMART_PLANNER_SYSTEM_PROMPT, SMART_PLANNER_USER_PROMPT


_ALLOWED_STEP_TYPES = {"chat", "workspace", "research"}

_SUPPORTED_WORKSPACE_ACTIONS = {
    "list_files",
    "file_info",
    "read_text",
    "write_text",
    "append_text",
    "mkdir",
    "delete_path",
    "clear_dir",
    "copy_path",
    "move_path",
    "download_url",
    "find_files",
    "replace_text",
    "archive_zip",
    "extract_zip",
    "extract_pdf_text",
}


def _norm_path(raw: object) -> str:
    text = str(raw or "").strip()
    text = text.lstrip("/").lstrip("\\")
    return text.replace("\\", "/")


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
        if not prompt_text:
            return None
        use_history = raw.get("use_history", True)
        return {
            "type": "chat",
            "title": title[:120],
            "prompt": prompt_text[:4000],
            "use_history": bool(use_history),
        }

    if step_type == "workspace":
        action = str(raw.get("action") or "").strip()
        if action not in _SUPPORTED_WORKSPACE_ACTIONS:
            return None
        args = raw.get("args")
        if not isinstance(args, dict):
            return None
        cleaned: dict[str, Any] = {
            "type": "workspace",
            "title": title[:120],
            "action": action,
            "args": dict(args),
        }
        if action in {"write_text", "append_text"}:
            content_text = str(args.get("content") or "")
            content_brief = str(raw.get("content_brief") or "").strip()
            if not content_text.strip() and not content_brief:
                return None
            cleaned["args"].setdefault("content", "")
            if content_brief:
                cleaned["content_brief"] = content_brief[:4000]
        return cleaned

    # type == "research"
    goal = str(raw.get("goal") or "").strip()
    if not goal:
        return None
    cleaned_research: dict[str, Any] = {
        "type": "research",
        "title": title[:120],
        "goal": goal[:1000],
    }
    post_path = _norm_path(raw.get("post_write_path") or raw.get("post_write") or "")
    if post_path:
        cleaned_research["post_write_path"] = post_path[:512]
    return cleaned_research


def _validate_plan(payload: object, *, allow_research: bool) -> dict[str, Any] | None:
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
        if validated["type"] == "research" and not allow_research:
            # 把不允许的 research 步骤静默降级为 chat，避免规划失效。
            cleaned_steps.append(
                {
                    "type": "chat",
                    "title": validated["title"],
                    "prompt": (
                        "请基于通用知识对下面的研究问题给出尽可能完整、准确的回答；"
                        "若信息不足请明确说明：\n"
                        f"{validated.get('goal', '')}"
                    ),
                    "use_history": True,
                }
            )
        else:
            cleaned_steps.append(validated)
    if not cleaned_steps:
        return None
    summary = str(payload.get("summary") or "").strip()
    needs_deep = bool(payload.get("needs_deep_research"))
    if not allow_research:
        needs_deep = False
    return {
        "summary": summary[:300],
        "needs_deep_research": needs_deep,
        "steps": cleaned_steps,
    }


def _llm_smart_plan(query: str, *, allow_research: bool) -> dict[str, Any] | None:
    user_prompt = SMART_PLANNER_USER_PROMPT.format(
        query=query,
        allow_research="true" if allow_research else "false",
    )
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
    plan = _validate_plan(payload, allow_research=allow_research)
    if plan is None:
        print(
            f"[research_agent][smart_planner] 规划结果未通过校验 latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    type_summary = ",".join(step["type"] for step in plan["steps"])
    print(
        "[research_agent][smart_planner] 规划成功: "
        f"steps={len(plan['steps'])} types=[{type_summary}] "
        f"needs_deep={plan['needs_deep_research']} latency_ms={elapsed_ms}",
        flush=True,
    )
    return plan


def detect_smart_plan(content: str, *, allow_research: bool) -> dict[str, Any] | None:
    """
    生成统一智能任务拆解。

    参数：
    - ``content``：用户最新一条原始请求；
    - ``allow_research``：当前是否允许 research 步骤（深度思考开关）。

    返回：
    - 成功：``{"summary": str, "needs_deep_research": bool, "steps": list[dict]}``；
    - 失败：``None``，由调用方降级为单步 chat。
    """
    text = (content or "").strip()
    if not text:
        return None
    return _llm_smart_plan(text, allow_research=allow_research)


def fallback_chat_plan(content: str) -> dict[str, Any]:
    """规划失败时的兜底：直接把用户原话当作 chat 指令交给 LLM。"""
    text = (content or "").strip() or "请回应用户的请求"
    return {
        "summary": "fallback chat",
        "needs_deep_research": False,
        "steps": [
            {
                "type": "chat",
                "title": "直接回复用户",
                "prompt": text[:4000],
                "use_history": True,
            }
        ],
    }
