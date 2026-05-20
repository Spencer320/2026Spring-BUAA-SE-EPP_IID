"""Research Agent LLM client (OpenAI-compatible HTTP)."""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from dataclasses import dataclass
import json
import re
import time

import httpx
from django.conf import settings


_usage_accumulator: contextvars.ContextVar[Callable[[dict], None] | None] = contextvars.ContextVar(
    "ra_llm_usage_accumulator",
    default=None,
)


def usage_total_tokens(usage: dict | None) -> int:
    """
    从供应商 usage 对象提取总 Token 数。
    ModelArts / OpenAI 兼容：优先 total_tokens，否则 prompt+completion（或 input/output）。
    """
    if not usage or not isinstance(usage, dict):
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, (int, float)) and total >= 0:
        return int(total)
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    try:
        return max(0, int(prompt) + int(completion))
    except (TypeError, ValueError):
        return 0


def bind_usage_accumulator(callback: Callable[[dict], None]):
    """在科研助手 basic 编排线程内注册 Token 累加器；返回 reset token。"""
    return _usage_accumulator.set(callback)


def reset_usage_accumulator(token) -> None:
    _usage_accumulator.reset(token)


def _report_usage_to_accumulator(usage: dict | None) -> None:
    if not usage:
        return
    sink = _usage_accumulator.get()
    if sink is None:
        return
    try:
        sink(usage)
    except Exception:
        pass


@dataclass(frozen=True)
class LLMCallResult:
    ok: bool
    content: str = ""
    error_code: str = ""
    error_message: str = ""
    model: str = ""
    latency_ms: int = 0
    usage: dict[str, int] | None = None


def _extract_balanced_json_object(text: str, *, start_at: int = 0) -> str:
    start = text.find("{", max(0, start_at))
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return ""


def _json_text_candidates(raw: str) -> list[str]:
    """整段文本 + 首个 ```json … ``` 代码块（若有）。"""
    text = (raw or "").strip()
    if not text:
        return []
    out = [text]
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if m:
        inner = (m.group(1) or "").strip()
        if inner and inner not in out:
            out.append(inner)
    return out


def normalize_supplier_json_response(raw_text: str) -> tuple[dict[str, object] | None, str]:
    """
    将模型输出解析为单个 JSON 对象：先 ``json.loads``，失败则对候选文本做平衡括号截取后再解析。
    解析失败返回 ``(None, 简短原因)``，不再包装伪对象。
    """
    for cand in _json_text_candidates(raw_text or ""):
        try:
            payload = json.loads(cand)
            if isinstance(payload, dict):
                return payload, ""
        except json.JSONDecodeError:
            pass
        blob = _extract_balanced_json_object(cand)
        if not blob:
            continue
        try:
            payload = json.loads(blob)
            if isinstance(payload, dict):
                return payload, ""
        except json.JSONDecodeError:
            continue
    return None, "invalid or non-object JSON"


def iter_json_objects_in_text(raw_text: str) -> Iterator[dict[str, object]]:
    """从文本中每个 ``{`` 起点尝试截取并 ``json.loads`` 出 dict（供编排器片段恢复）。"""
    text = raw_text or ""
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        extracted = _extract_balanced_json_object(text, start_at=i)
        if not extracted:
            continue
        try:
            obj = json.loads(extracted)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def pick_searcher_json_payload(raw_text: str) -> dict[str, object] | None:
    """在输出中选取最像 searcher 的 JSON（须含非空 ``info_groups`` 子结构）。"""
    best: dict[str, object] | None = None
    best_score = -1
    for obj in iter_json_objects_in_text(raw_text):
        groups = obj.get("info_groups")
        if not isinstance(groups, list):
            continue
        has_notes = isinstance(obj.get("search_notes"), str)
        nonempty = sum(
            1
            for g in groups
            if isinstance(g, dict)
            and isinstance(g.get("raw_findings"), list)
            and any(isinstance(x, str) and x.strip() for x in g.get("raw_findings", []))
        )
        if len(groups) == 0:
            score = -2
        elif nonempty == 0:
            score = -1
        else:
            score = len(groups) * 10 + nonempty * 5 + (3 if has_notes else 0)
        if score > best_score:
            best_score = score
            best = obj
    return best if best is not None and best_score >= 0 else None


def _finalize_read_candidate(obj: dict[str, object]) -> dict[str, object] | None:
    analysis_raw = obj.get("analysis")
    if isinstance(analysis_raw, str):
        analysis = analysis_raw.strip()
    elif analysis_raw is None or isinstance(analysis_raw, (dict, list)):
        analysis = ""
    else:
        analysis = str(analysis_raw).strip()
    if not analysis:
        return None

    kp_raw = obj.get("key_points")
    if isinstance(kp_raw, str) and kp_raw.strip():
        key_points = [kp_raw.strip()]
    elif isinstance(kp_raw, list):
        key_points = [str(x).strip() for x in kp_raw if str(x).strip()]
    else:
        key_points = []

    lim_raw = obj.get("limitations")
    if isinstance(lim_raw, str) and lim_raw.strip():
        limitations = [lim_raw.strip()]
    elif isinstance(lim_raw, list):
        limitations = [str(x).strip() for x in lim_raw if str(x).strip()]
    else:
        limitations = []

    return {"analysis": analysis, "key_points": key_points, "limitations": limitations}


def pick_reader_json_payload(raw_text: str) -> dict[str, object] | None:
    text = raw_text or ""
    best: dict[str, object] | None = None
    best_score = -1
    for obj in iter_json_objects_in_text(text):
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("info_groups"), list):
            continue
        if "needs_optimization" in obj and "accepted_reader_summary" in obj:
            wrapped = obj.get("accepted_reader_summary")
            if isinstance(wrapped, dict):
                nested = _finalize_read_candidate(wrapped)
                if nested is None:
                    continue
                score = len(nested["analysis"]) + sum(len(str(x)) for x in nested["key_points"])
                score += sum(len(str(x)) for x in nested["limitations"])
                if score > best_score:
                    best_score = score
                    best = nested
            continue
        if set(obj.keys()) <= {"title", "url", "snippet", "raw_content"}:
            continue
        finalized = _finalize_read_candidate(obj)
        if finalized is None:
            continue
        score = len(finalized["analysis"]) + sum(len(str(x)) for x in finalized["key_points"]) * 2
        score += sum(len(str(x)) for x in finalized["limitations"]) * 2
        if score > best_score:
            best_score = score
            best = finalized
    return best


def _reflect_yes_no(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    raw = str(value if value is not None else "").strip().lower()
    if raw in {"yes", "y", "true", "1", "是", "要", "需要"}:
        return "yes"
    if raw in {"no", "n", "false", "0", "否", "不", "不需要", "跳过", "无需", "無需"}:
        return "no"
    return "no"


def _finalize_reflect_outer(obj: dict[str, object]) -> dict[str, object] | None:
    acc = obj.get("accepted_reader_summary")
    if not isinstance(acc, dict):
        return None
    finalized_read = _finalize_read_candidate(acc)
    if finalized_read is None:
        return None
    reason = obj.get("reason")
    reason_s = reason.strip() if isinstance(reason, str) and reason.strip() else "（反思阶段结构化字段由系统补齐。）"
    sug_raw = obj.get("actionable_suggestions")
    if isinstance(sug_raw, str) and sug_raw.strip():
        suggestions = [sug_raw.strip()]
    elif isinstance(sug_raw, list):
        suggestions = [str(x).strip() for x in sug_raw if str(x).strip()]
    else:
        suggestions = []
    need = _reflect_yes_no(obj.get("needs_optimization"))
    if need == "yes" and not suggestions:
        suggestions = ["请在下一轮收窄检索关键词或补充对比维度。"]
    return {
        "needs_optimization": need,
        "reason": reason_s,
        "actionable_suggestions": suggestions,
        "accepted_reader_summary": finalized_read,
    }


def pick_reflector_json_payload(raw_text: str) -> dict[str, object] | None:
    text = raw_text or ""
    best: dict[str, object] | None = None
    best_score = -1
    for obj in iter_json_objects_in_text(text):
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("info_groups"), list):
            continue
        if set(obj.keys()) <= {"title", "url", "snippet", "raw_content"}:
            continue
        if "accepted_reader_summary" not in obj:
            continue
        finalized = _finalize_reflect_outer(obj)
        if finalized is None:
            continue
        ar = finalized["accepted_reader_summary"]
        ana_len = len(str(ar["analysis"])) if isinstance(ar, dict) and isinstance(ar.get("analysis"), str) else 0
        score = len(finalized["reason"]) + ana_len
        if score > best_score:
            best_score = score
            best = finalized
    return best


def pick_write_json_payload(raw_text: str) -> dict[str, object] | None:
    text = raw_text or ""
    best: dict[str, object] | None = None
    best_score = -1
    for obj in iter_json_objects_in_text(text):
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("info_groups"), list):
            continue
        sec = obj.get("sections")
        tr = obj.get("traceability")
        title = obj.get("title")
        ess = obj.get("executive_summary")
        score = 0
        if isinstance(title, str) and title.strip():
            score += 4
        if isinstance(ess, str) and ess.strip():
            score += 4
        if isinstance(sec, list) and sec:
            score += min(len(sec), 20) * 3
        if isinstance(tr, list) and tr:
            score += min(len(tr), 20) * 3
        if score > best_score:
            best_score = score
            best = dict(obj)
    if best is None or best_score < 6:
        return None
    return best


def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    messages: list[dict[str, str]] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    enable_thinking: bool = True,
    stream: bool = False,
) -> LLMCallResult:
    """非流式默认；正文仅使用供应商 ``message.content``，不把思考链拼进结果。"""
    base_url = str(getattr(settings, "RA_LLM_BASE_URL", "") or "").strip()
    api_key = str(getattr(settings, "RA_LLM_API_KEY", "") or "").strip()
    model = str(getattr(settings, "RA_LLM_MODEL", "") or "").strip()
    chat_path = str(getattr(settings, "RA_LLM_CHAT_PATH", "/chat/completions") or "").strip()
    timeout = float(getattr(settings, "RA_LLM_TIMEOUT", 45.0))

    if not base_url or not api_key or not model:
        return LLMCallResult(
            ok=False,
            error_code="LLM_CONFIG_MISSING",
            error_message="RA_LLM_BASE_URL/RA_LLM_API_KEY/RA_LLM_MODEL 未配置",
        )
    if not chat_path.startswith("/"):
        chat_path = f"/{chat_path}"
    url = f"{base_url.rstrip('/')}{chat_path}"

    final_messages: list[dict[str, str]]
    if messages:
        final_messages = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role in {"system", "user", "assistant"} and content:
                final_messages.append({"role": role, "content": content})
        if not final_messages:
            final_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
    else:
        final_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    body: dict[str, object] = {
        "model": model,
        "messages": final_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": bool(stream),
    }
    body["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    start = time.monotonic()
    try:
        if stream:
            return _stream_chat_completion(url, body, headers, timeout=timeout, model=model, start=start)
        return _sync_chat_completion(url, body, headers, timeout=timeout, model=model, start=start)
    except httpx.TimeoutException:
        return LLMCallResult(
            ok=False,
            error_code="LLM_TIMEOUT",
            error_message=f"LLM 请求超时（{timeout}s）",
            model=model,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
    except httpx.RequestError as exc:
        return LLMCallResult(
            ok=False,
            error_code="LLM_UPSTREAM_ERROR",
            error_message=str(exc) or "LLM 网络请求失败",
            model=model,
            latency_ms=int((time.monotonic() - start) * 1000),
        )


def _sync_chat_completion(
    url: str,
    body: dict[str, object],
    headers: dict[str, str],
    *,
    timeout: float,
    model: str,
    start: float,
) -> LLMCallResult:
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body, headers=headers)
    latency = int((time.monotonic() - start) * 1000)
    if resp.status_code >= 400:
        err_text = (resp.text or "")[:300]
        return LLMCallResult(
            ok=False,
            error_code="LLM_HTTP_ERROR",
            error_message=f"HTTP {resp.status_code}: {err_text}",
            model=model,
            latency_ms=latency,
        )
    try:
        payload = resp.json()
    except (json.JSONDecodeError, ValueError):
        return LLMCallResult(
            ok=False,
            error_code="LLM_BAD_RESPONSE",
            error_message=f"LLM 响应不是 JSON: {(resp.text or '')[:200]}",
            model=model,
            latency_ms=latency,
        )
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        return LLMCallResult(
            ok=False,
            error_code="LLM_EMPTY_RESPONSE",
            error_message="LLM 返回 choices 为空",
            model=model,
            latency_ms=latency,
        )
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = ""
    if isinstance(msg, dict):
        raw_content = msg.get("content")
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            parts: list[str] = []
            for item in raw_content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if isinstance(text, str):
                        parts.append(text)
            content = "".join(parts)
    content = (content or "").strip()
    if not content:
        return LLMCallResult(
            ok=False,
            error_code="LLM_EMPTY_RESPONSE",
            error_message="LLM 返回内容为空",
            model=model,
            latency_ms=latency,
        )
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(usage, dict):
        _report_usage_to_accumulator(usage)
    return LLMCallResult(
        ok=True,
        content=content,
        model=model,
        latency_ms=latency,
        usage=usage if isinstance(usage, dict) else None,
    )


def _stream_chat_completion(
    url: str,
    body: dict[str, object],
    headers: dict[str, str],
    *,
    timeout: float,
    model: str,
    start: float,
) -> LLMCallResult:
    content_parts: list[str] = []
    usage: dict[str, int] | None = None
    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", url, json=body, headers=headers) as resp:
            latency = int((time.monotonic() - start) * 1000)
            if resp.status_code >= 400:
                err_text = ""
                try:
                    err_text = resp.read().decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    err_text = ""
                return LLMCallResult(
                    ok=False,
                    error_code="LLM_HTTP_ERROR",
                    error_message=f"HTTP {resp.status_code}: {err_text[:300]}",
                    model=model,
                    latency_ms=latency,
                )

            for line in resp.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
                if not text.startswith("data:"):
                    continue
                data = text[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = payload.get("choices", [])
                if isinstance(choices, list) and choices:
                    delta = choices[0].get("delta", {})
                    piece = delta.get("content", "") if isinstance(delta, dict) else ""
                    if isinstance(piece, str) and piece:
                        content_parts.append(piece)
                    msg = choices[0].get("message", {})
                    whole = msg.get("content", "") if isinstance(msg, dict) else ""
                    if isinstance(whole, str) and whole and not content_parts:
                        content_parts.append(whole)
                u = payload.get("usage")
                if isinstance(u, dict):
                    usage = u

    latency = int((time.monotonic() - start) * 1000)
    content = "".join(content_parts).strip()
    if not content:
        return LLMCallResult(
            ok=False,
            error_code="LLM_EMPTY_RESPONSE",
            error_message="LLM 返回为空",
            model=model,
            latency_ms=latency,
        )
    if isinstance(usage, dict):
        _report_usage_to_accumulator(usage)
    return LLMCallResult(
        ok=True,
        content=content,
        model=model,
        latency_ms=latency,
        usage=usage if isinstance(usage, dict) else None,
    )
