"""Research Agent LLM client (direct vendor, OpenAI-compatible)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time

import httpx
from django.conf import settings


@dataclass(frozen=True)
class LLMCallResult:
    ok: bool
    content: str = ""
    error_code: str = ""
    error_message: str = ""
    model: str = ""
    latency_ms: int = 0
    usage: dict[str, int] | None = None


def _extract_balanced_json_object(text: str) -> str:
    start = text.find("{")
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


def normalize_supplier_json_response(raw_text: str) -> tuple[dict[str, object] | None, str]:
    text = (raw_text or "").strip()
    if not text:
        return None, "empty response"

    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    for block in fenced:
        if block and block.strip():
            candidates.append(block.strip())

    for cand in candidates:
        # 先尝试直接按 JSON 解析
        try:
            payload = json.loads(cand)
            if isinstance(payload, dict):
                return payload, ""
        except json.JSONDecodeError:
            pass

        # 再尝试提取首个平衡 JSON 对象
        extracted = _extract_balanced_json_object(cand)
        if not extracted:
            continue
        try:
            payload = json.loads(extracted)
            if isinstance(payload, dict):
                return payload, ""
        except json.JSONDecodeError:
            continue

    # 最后兜底：按需求“前后加 {} 假装成 JSON 返回”，避免上层拿到 None。
    wrapped = "{" + text + "}"
    return {
        "_fallback_wrapped": True,
        "_fallback_error": "invalid json object",
        "wrapped_text": wrapped,
        "raw_text": text,
    }, ""


def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    messages: list[dict[str, str]] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1500,
) -> LLMCallResult:
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

    body = {
        "model": model,
        "messages": final_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": "enabled"},
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    start = time.monotonic()
    try:
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
                        # 兼容非 delta 返回
                        msg = choices[0].get("message", {})
                        whole = msg.get("content", "") if isinstance(msg, dict) else ""
                        if isinstance(whole, str) and whole and not content_parts:
                            content_parts.append(whole)
                    u = payload.get("usage")
                    if isinstance(u, dict):
                        usage = u
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
    return LLMCallResult(
        ok=True,
        content=content,
        model=model,
        latency_ms=latency,
        usage=usage if isinstance(usage, dict) else None,
    )
