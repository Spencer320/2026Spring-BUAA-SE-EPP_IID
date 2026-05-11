"""Playwright 无头浏览器 + LLM 动作循环（Web Operator 雏形）。"""

from __future__ import annotations

import time
from typing import Any

from django.conf import settings

from ..llm_client import chat_completion, normalize_supplier_json_response
from ..site_access_control import evaluate_target_domain
from .base import WebSearchResult, extract_url_domain, make_audit, truncate_text

_SNAPSHOT_JS = """
() => {
  const sel = 'a, button, input, textarea, select, [role="button"]';
  const nodes = Array.from(document.querySelectorAll(sel)).filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }).slice(0, 72);
  return nodes.map((el, i) => {
    const id = i + 1;
    el.setAttribute('data-ra-op-id', String(id));
    const tag = el.tagName.toLowerCase();
    const t = el.type || '';
    const txt = (
      (el.innerText || el.value || el.getAttribute('placeholder') || el.getAttribute('aria-label') || '')
        .trim()
        .slice(0, 140)
    );
    return { id, tag, type: t, text: txt };
  });
}
"""

_SYSTEM = """你是网页操作代理。根据「页面可操作元素列表」和用户目标，输出**唯一一个** JSON 对象，不要其它文字。
字段：
- action: click | type | scroll | wait | done | navigate
- target_id: 整数，对应列表中的 id（navigate/done/scroll/wait 可为 0）
- text: type 时填入的文本；scroll 时 up 或 down；navigate 时为完整 URL
- papers: 仅当 action 为 done 时，数组，每项含 title, url, snippet（可为空字符串）

规则：优先点击搜索框再 type 再提交；找不到元素时用 scroll down；收集到足够论文条目后用 done。"""


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _safe_close(name: str, obj: Any | None, method: str) -> None:
    if obj is None:
        return
    closer = getattr(obj, method, None)
    if closer is None:
        return
    try:
        closer()
    except Exception:
        pass


def run_web_operator(goal: str, *, start_url: str) -> WebSearchResult:
    g = (goal or "").strip()
    url = (start_url or "").strip()
    if not g:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_OPERATOR_EMPTY_GOAL",
            error_message="goal is empty",
            audit=make_audit("web_search", "error", "empty goal", provider="web_operator"),
        )
    if not url.startswith("http"):
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_OPERATOR_BAD_URL",
            error_message="start_url must be http(s)",
            audit=make_audit("web_search", "error", "bad url", provider="web_operator"),
        )
    dom = extract_url_domain(url)
    decision = evaluate_target_domain(dom)
    if not decision.allowed:
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="OUTBOUND_SITE_DENIED",
            error_message=decision.reason_message,
            audit=make_audit(
                "web_search",
                "rejected",
                "start_url denied",
                provider="web_operator",
                target_domain=dom,
                rule_hit=decision.rule_hit,
                policy_version=decision.policy_version,
            ),
        )

    if not playwright_available():
        return WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_OPERATOR_PLAYWRIGHT_MISSING",
            error_message="playwright package or browsers not installed",
            audit=make_audit("web_search", "error", "playwright missing", provider="web_operator"),
        )

    from playwright.sync_api import sync_playwright

    max_steps = int(getattr(settings, "RA_WEB_OPERATOR_MAX_STEPS", 12))
    goto_timeout = int(getattr(settings, "RA_WEB_OPERATOR_GOTO_TIMEOUT_MS", 45_000))
    step_timeout = int(getattr(settings, "RA_WEB_OPERATOR_STEP_TIMEOUT_MS", 15_000))

    citations: list[dict[str, str]] = []
    last_err = ""
    step_i = -1
    pw: Any | None = None
    browser: Any | None = None
    page: Any | None = None
    result: WebSearchResult | None = None

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(step_timeout)
        page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout)
        time.sleep(0.4)

        for step_i in range(max_steps):
            snap = page.evaluate(_SNAPSHOT_JS)
            if not isinstance(snap, list):
                last_err = "snapshot failed"
                break
            lines = [f"目标：{g[:800]}", f"当前URL：{page.url}", "可操作元素："]
            for item in snap:
                if isinstance(item, dict):
                    lines.append(
                        f"[{item.get('id')}] <{item.get('tag')}> "
                        f"type={item.get('type')!s} text={str(item.get('text') or '')[:120]}"
                    )
            user_prompt = "\n".join(lines)[:12000]
            res = chat_completion(
                system_prompt=_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=800,
                enable_thinking=False,
                stream=False,
                merge_reasoning_into_content=False,
            )
            if not res.ok:
                last_err = res.error_message or "llm failed"
                break
            payload, _ = normalize_supplier_json_response(res.content)
            if not isinstance(payload, dict) or payload.get("_fallback_wrapped"):
                last_err = "bad llm json"
                break
            action = str(payload.get("action") or "").strip().lower()
            tid = int(payload.get("target_id") or 0)
            text = str(payload.get("text") or "")

            if action == "done":
                papers = payload.get("papers")
                if isinstance(papers, list):
                    for p in papers:
                        if not isinstance(p, dict):
                            continue
                        title = str(p.get("title") or "").strip()
                        purl = str(p.get("url") or "").strip()
                        snip = str(p.get("snippet") or "").strip()
                        if not title and not purl:
                            continue
                        d = extract_url_domain(purl)
                        if purl and not evaluate_target_domain(d).allowed:
                            continue
                        citations.append(
                            {
                                "query": g[:500],
                                "title": title or purl or "item",
                                "source": "web_operator",
                                "url": purl,
                                "published_at": "",
                                "snippet": truncate_text(snip, 300),
                                "raw_content": truncate_text(f"{title}\n{purl}\n{snip}", 2200),
                                "confidence": "0.72",
                                "domain": d,
                            }
                        )
                break

            if action == "navigate" and text.startswith("http"):
                page.goto(text, wait_until="domcontentloaded", timeout=goto_timeout)
                time.sleep(0.35)
                continue

            if action == "scroll":
                delta = 800 if "down" in text.lower() else -800
                page.mouse.wheel(0, delta)
                time.sleep(0.4)
                continue

            if action == "wait":
                time.sleep(min(3.0, max(0.5, float(tid or 1))))
                continue

            if action == "click" and tid > 0:
                page.locator(f'[data-ra-op-id="{tid}"]').click(timeout=step_timeout)
                time.sleep(0.5)
                continue

            if action == "type" and tid > 0:
                loc = page.locator(f'[data-ra-op-id="{tid}"]')
                loc.fill(text[:2000], timeout=step_timeout)
                time.sleep(0.2)
                continue

            last_err = f"unknown action {action}"
            break

        if citations:
            result = WebSearchResult(
                ok=True,
                summary=f"web_operator: {len(citations)} items",
                citations=citations,
                audit=make_audit(
                    "web_search",
                    "ok",
                    "web operator finished",
                    provider="web_operator",
                    start_url=url,
                    steps=step_i + 1,
                ),
            )
        else:
            result = WebSearchResult(
                ok=False,
                summary="",
                citations=[],
                error_code="WEB_OPERATOR_NO_RESULTS",
                error_message=last_err or "no citations extracted",
                audit=make_audit(
                    "web_search",
                    "error",
                    last_err or "no results",
                    provider="web_operator",
                    start_url=url,
                ),
            )
    except Exception as exc:
        msg = str(exc).strip() or repr(exc)
        result = WebSearchResult(
            ok=False,
            summary="",
            citations=[],
            error_code="WEB_OPERATOR_RUNTIME_ERROR",
            error_message=msg[:500],
            audit=make_audit(
                "web_search",
                "error",
                "playwright runtime error",
                provider="web_operator",
                start_url=url,
                step=step_i,
                exception_message=msg[:1200],
            ),
        )
    finally:
        _safe_close("page", page, "close")
        _safe_close("browser", browser, "close")
        _safe_close("playwright", pw, "stop")

    return result or WebSearchResult(
        ok=False,
        summary="",
        citations=[],
        error_code="WEB_OPERATOR_RUNTIME_ERROR",
        error_message="internal: no result",
        audit=make_audit("web_search", "error", "internal", provider="web_operator"),
    )
