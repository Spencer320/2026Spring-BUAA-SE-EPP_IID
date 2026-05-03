"""
工作区任务意图识别。

设计目标：
- 单一动作、字面清晰的请求由规则秒级返回，避免无谓的 LLM 调用；
- 多步、组合或语义复杂的请求直接交给 LLM 规划，由 LLM 输出严格的 plan.steps；
- 写正文（教程、说明、笔记等）通过 ``content_brief`` 暂记意图，由后续的内容生成阶段
  单独调用 LLM 写作，避免在路由阶段被迫一次性生成长内容。
"""

from __future__ import annotations

import re
import time
from typing import Any

from .llm_client import chat_completion, normalize_supplier_json_response
from .prompts import WORKSPACE_ROUTE_SYSTEM_PROMPT, WORKSPACE_ROUTE_USER_PROMPT


_QUOTED_RE = re.compile(r"[\"'“”‘’`《》]+([^\"'“”‘’`《》]+)[\"'“”‘’`《》]+")
_SUPPORTED_ACTIONS = {
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

# 命中其中任何一个，都视为"多步意图"，直接交给 LLM 规划，避免规则误判
_MULTI_STEP_HINTS = (
    "；",
    ";",
    "然后",
    "接着",
    "再",
    "并且",
    "并在",
    "之后",
    "随后",
    "第一步",
    "第二步",
    "首先",
    "其次",
    "最后",
    "最终",
    "里面",
    "其中",
    "下面",
    "底下",
    "在该",
    "在其",
)

# 写作意图：一旦命中，本质上是"创作正文 + 写文件"，规则无法生成高质量内容，统一交给 LLM
_WRITING_HINTS = (
    "教程",
    "介绍",
    "说明",
    "笔记",
    "总结",
    "概述",
    "综述",
    "讲解",
    "提纲",
    "简介",
    "报告",
    "文档",
    "解释",
    "示例",
)


def _quoted(text: str) -> list[str]:
    return [m.group(1).strip() for m in _QUOTED_RE.finditer(text) if m.group(1).strip()]


def _normalize_path(raw: str) -> str:
    text = (raw or "").strip().strip("。.,，；;：:")
    text = re.sub(r"(下的)?(所有)?文件$", "", text).strip()
    text = re.sub(r"(目录|文件夹|工作区)$", "", text).strip()
    text = re.sub(r"下$", "", text).strip()
    text = text.replace("\\", "/")
    return text.lstrip("/")


def _path_after(text: str, keywords: tuple[str, ...]) -> str:
    for keyword in keywords:
        idx = text.find(keyword)
        if idx >= 0:
            return _normalize_path(text[idx + len(keyword) :])
    return ""


def _first_quoted_or_after(text: str, keywords: tuple[str, ...], default: str = "") -> str:
    quoted = _quoted(text)
    if quoted:
        return _normalize_path(quoted[0])
    return _path_after(text, keywords) or default


def _delete_bulk_hint(text: str) -> bool:
    """批量/通配删除语义交给 LLM 规划，避免单路径规则误伤。"""
    t = (text or "").strip()
    if not t:
        return False
    if any(x in t for x in ("所有", "全部", "几个", "多个", "批量", "凡是", "*.md", "*.txt")):
        if "删除" in t or "删掉" in t:
            return True
    if re.search(r"[一二两三三四五六七八九十两\d]+\s*个", t) and (
        "删除" in t or "删掉" in t
    ):
        if any(x in t.lower() for x in ("md", "markdown", "txt", "pdf", "文件")):
            return True
    return False


def _path_for_delete_command(text: str) -> str:
    """
    从「删除/删掉」类自然语言里抽取**单一**相对路径。

    中文常把路径放在「把 … 删掉」中间，若用「删掉」做后缀去截 remainder 会得到空串，
    进而误触发 delete_path(path=工作区根)。
    """
    quoted = _quoted(text)
    if quoted:
        return _normalize_path(quoted[0])
    t = text.strip().rstrip("。.;；")
    for pat in (
        r"(?:把|将)\s*(.+?)\s*删掉",
        r"(?:把|将)\s*(.+?)\s*删除(?:掉)?",
        r"(?:删除|删掉)\s*(?:了)?\s*(?:目录|文件夹|文件)\s*[：:]\s*(.+?)(?:[。.;；]|$)",
    ):
        m = re.search(pat, t)
        if m:
            cand = _normalize_path(m.group(1))
            if cand:
                return cand
    return _path_after(
        t,
        ("递归删除", "删除目录", "删除文件夹", "删除文件", "删除"),
    )


def _replace_pair(text: str) -> tuple[str, str] | None:
    quoted = _quoted(text)
    if len(quoted) >= 2:
        return quoted[0], quoted[1]
    match = re.search(r"(?:把|将)(.+?)替换(?:为|成)(.+?)(?:，|,|。|$)", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None


def _validate_plan(plan: object) -> dict[str, Any] | None:
    """
    校验 LLM/规则产出的 plan。

    - args 必须是 dict；
    - write_text/append_text 必须给出 args.content（非空字符串）或 step.content_brief（非空字符串）二者之一；
      允许 args.content="" 配合非空 content_brief，由后续步骤生成正文；
    - 其它字段透传。
    """
    if not isinstance(plan, dict):
        return None
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return None
    cleaned: list[dict[str, Any]] = []
    for step in steps[:8]:
        if not isinstance(step, dict):
            return None
        tool = str(step.get("tool") or "workspace").strip()
        action = str(step.get("action") or "").strip()
        args = step.get("args", {})
        if tool != "workspace" or action not in _SUPPORTED_ACTIONS or not isinstance(args, dict):
            return None
        if action in {"write_text", "append_text"}:
            content_text = str(args.get("content") or "")
            content_brief = str(step.get("content_brief") or "").strip()
            if not content_text.strip() and not content_brief:
                return None
            # 标准化：保证 args.content 字段存在（即便为空字符串），便于下游统一处理
            args.setdefault("content", "")
        cleaned_step: dict[str, Any] = {"tool": "workspace", "action": action, "args": args}
        brief = str(step.get("content_brief") or "").strip()
        if brief:
            cleaned_step["content_brief"] = brief
        cleaned.append(cleaned_step)
    return {"steps": cleaned}


def _validate_post_write(raw: object) -> dict[str, Any] | None:
    """
    校验 research_then_write 模式下的 post_write 字段。

    必须给出 path（写入的工作区相对路径），content_brief 可选。
    """
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path") or "").strip().lstrip("/").lstrip("\\")
    if not path:
        return None
    content_brief = str(raw.get("content_brief") or "").strip()
    return {"path": path, "content_brief": content_brief}


def _llm_detect_workspace_plan(content: str) -> dict[str, Any] | None:
    """
    用 LLM 进行意图识别 + 多步规划。

    路由阶段不做长内容生成，只输出 schema 严格的 plan，因此关闭 thinking、关闭流式，
    单次延迟控制在数秒级。需要写入正文的步骤通过 content_brief 描述写作目标。

    返回结构：
    - 纯工作区任务：``{"mode": "workspace", "steps": [...]}``；
    - 研究后写入：``{"mode": "research_then_write", "post_write": {"path": "...", "content_brief": "..."}}``；
    - 不属于工作区任务：``None``（由调用方降级到深度研究流水线）。
    """
    user_prompt = WORKSPACE_ROUTE_USER_PROMPT.format(query=content)
    started = time.monotonic()
    res = chat_completion(
        system_prompt=WORKSPACE_ROUTE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=900,
        enable_thinking=False,
        stream=False,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not res.ok:
        print(
            f"[research_agent][workspace_intent] LLM 路由失败: {res.error_code} {res.error_message} "
            f"latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    payload, err = normalize_supplier_json_response(res.content)
    if payload is None:
        print(
            f"[research_agent][workspace_intent] LLM 路由 JSON 解析失败: {err} latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    if payload.get("_fallback_wrapped"):
        # 兜底返回的伪 JSON 没有有效结构，直接放弃
        print(
            f"[research_agent][workspace_intent] LLM 路由响应非合法 JSON，已放弃 latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    if not bool(payload.get("is_workspace")):
        print(
            f"[research_agent][workspace_intent] LLM 路由结果: 非工作区任务 latency_ms={elapsed_ms}",
            flush=True,
        )
        return None
    try:
        confidence = float(payload.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    if confidence < 0.55:
        print(
            f"[research_agent][workspace_intent] LLM 路由置信度过低: {confidence} latency_ms={elapsed_ms}",
            flush=True,
        )
        return None

    mode = str(payload.get("mode") or "").strip().lower() or "workspace"

    if mode == "research_then_write":
        post_write = _validate_post_write(payload.get("post_write"))
        if not post_write:
            print(
                f"[research_agent][workspace_intent] research_then_write 缺少合法 post_write latency_ms={elapsed_ms}",
                flush=True,
            )
            return None
        print(
            "[research_agent][workspace_intent] LLM 路由命中: "
            f"mode=research_then_write confidence={confidence} target={post_write['path']} "
            f"latency_ms={elapsed_ms}",
            flush=True,
        )
        return {"mode": "research_then_write", "post_write": post_write}

    # 默认按 workspace 模式校验 plan.steps
    plan = _validate_plan(payload.get("plan"))
    if plan:
        briefs = sum(1 for step in plan["steps"] if step.get("content_brief"))
        print(
            "[research_agent][workspace_intent] LLM 路由命中: "
            f"mode=workspace confidence={confidence}, steps={len(plan['steps'])}, content_briefs={briefs}, "
            f"latency_ms={elapsed_ms}",
            flush=True,
        )
        return {"mode": "workspace", **plan}
    print(
        f"[research_agent][workspace_intent] LLM 路由 plan 校验失败 latency_ms={elapsed_ms}",
        flush=True,
    )
    return None


def _looks_multi_step(text: str) -> bool:
    """命中任一多步线索就视为多步意图，直接交给 LLM 规划，不做规则匹配。"""
    return any(hint in text for hint in _MULTI_STEP_HINTS)


def _looks_writing(text: str) -> bool:
    """命中"教程/介绍/说明..."这类写作意图就交给 LLM，规则没法生成高质量正文。"""
    return any(hint in text for hint in _WRITING_HINTS)


def _rule_based_workspace_plan(text: str) -> dict[str, Any] | None:
    """
    高置信度规则匹配。仅识别**单步、字面清晰**的请求。

    - 多步意图（包含分号、并、然后、再、第一步等）一律跳过，交给 LLM。
    - 涉及"教程/介绍/说明/笔记/总结..."等写作类关键词的也跳过，交给 LLM 规划 + 后续内容生成。
    """
    if not text:
        return None
    if _looks_multi_step(text) or _looks_writing(text):
        return None

    lower = text.lower()
    workspace_hint = any(
        word in text
        for word in (
            "文件",
            "目录",
            "文件夹",
            "工作区",
            "压缩",
            "压成",
            "替换",
            "PDF",
            "论文",
            "删除",
            "删掉",
            "移动",
            "复制",
            "下载",
        )
    ) or "pdf" in lower
    if not workspace_hint:
        return None

    if any(word in text for word in ("列出", "查看", "显示", "浏览")) and any(
        word in text for word in ("文件", "目录", "文件夹", "工作区")
    ):
        path = _first_quoted_or_after(text, ("目录", "文件夹", "工作区"), "")
        return {"steps": [{"tool": "workspace", "action": "list_files", "args": {"path": path}}]}

    if any(word in text for word in ("创建目录", "新建目录", "创建文件夹", "新建文件夹")) and "文件" not in text:
        # 单纯创建目录；如果同时还提到"文件"则视为多步，交给 LLM
        path = _first_quoted_or_after(
            text,
            ("创建目录", "新建目录", "创建文件夹", "新建文件夹"),
            "",
        )
        if path:
            return {"steps": [{"tool": "workspace", "action": "mkdir", "args": {"path": path}}]}

    # "递归删除目录 foo" / "删除 foo (递归)" / "把 foo 删掉" 等单步删除请求
    if any(
        word in text
        for word in ("删除目录", "删除文件夹", "递归删除", "删除文件", "删掉")
    ) or (
        "删除" in text
        and any(word in text for word in ("目录", "文件夹", "文件", "工作区"))
    ):
        if _delete_bulk_hint(text):
            return None
        path = _path_for_delete_command(text)
        if path:
            recursive = ("递归" in text) or ("文件夹" in text) or ("目录" in text)
            return {
                "steps": [
                    {
                        "tool": "workspace",
                        "action": "delete_path",
                        "args": {"path": path, "recursive": recursive},
                    }
                ]
            }

    if "压缩" in text or "压成" in text:
        quoted = _quoted(text)
        pair_match = re.search(
            r"(?:压缩|压成)\s*(.+?)\s*(?:为|成|到)\s*([^\s，,。]+\.zip)",
            text,
            re.IGNORECASE,
        )
        src = (
            _normalize_path(pair_match.group(1))
            if pair_match
            else (_normalize_path(quoted[0]) if quoted else _path_after(text, ("压缩", "压成")))
        )
        output = _normalize_path(quoted[1]) if len(quoted) >= 2 else ""
        if not output:
            match = pair_match or re.search(
                r"(?:为|成|到)\s*([^\s，,。]+\.zip)",
                text,
                re.IGNORECASE,
            )
            output = (
                _normalize_path(match.group(2) if match is pair_match else match.group(1))
                if match
                else "archive.zip"
            )
        if src:
            return {
                "steps": [
                    {
                        "tool": "workspace",
                        "action": "archive_zip",
                        "args": {"path": src, "output": output},
                    }
                ]
            }

    if "替换" in text:
        pair = _replace_pair(text)
        if pair:
            path = _path_after(text, ("目录", "文件夹", "工作区"))
            glob = "*"
            ext_match = re.search(r"([a-zA-Z0-9]+)\s*(?:类型|格式|文件)", text)
            if ext_match:
                glob = f"*.{ext_match.group(1).lstrip('.')}"
            elif "markdown" in lower or "md文件" in text:
                glob = "*.md"
            elif "txt" in lower:
                glob = "*.txt"
            return {
                "steps": [
                    {"tool": "workspace", "action": "find_files", "args": {"path": path, "glob": glob}},
                    {
                        "tool": "workspace",
                        "action": "replace_text",
                        "args": {
                            "files_from": "previous",
                            "old": pair[0],
                            "new": pair[1],
                            "dry_run": False,
                        },
                    },
                ]
            }

    if ("pdf" in lower or "PDF" in text or "论文" in text) and any(
        word in text for word in ("解读", "读取", "提取", "解析")
    ):
        path = _first_quoted_or_after(text, ("解读", "读取", "提取", "解析"), "")
        if path:
            output = re.sub(r"\.pdf$", ".txt", path, flags=re.IGNORECASE)
            if output == path:
                output = f"{path}.txt"
            return {
                "steps": [
                    {
                        "tool": "workspace",
                        "action": "extract_pdf_text",
                        "args": {"path": path, "output": output},
                    }
                ]
            }

    return None


def detect_workspace_plan(content: str, *, use_llm: bool = False) -> dict[str, Any] | None:
    """
    识别工作区文件操作请求。

    1. 仅在请求是**单步、字面清晰**时使用规则；多步、组合或写作类一律走 LLM。
    2. 规则不识别时如果允许（``use_llm=True``）则调用 LLM 进行结构化规划。

    返回结构（统一带 ``mode`` 字段）：
    - ``{"mode": "workspace", "steps": [...]}`` —— 纯工作区操作；
    - ``{"mode": "research_then_write", "post_write": {"path": ..., "content_brief": ...}}``
      —— 先深度研究再把报告写入工作区文件；
    - ``None`` —— 不属于工作区任务，调用方应走深度研究流水线。
    """
    text = (content or "").strip()
    if not text:
        return None

    rule_plan = _rule_based_workspace_plan(text)
    if rule_plan is not None:
        print(
            f"[research_agent][workspace_intent] 规则命中工作区任务: steps={len(rule_plan['steps'])}",
            flush=True,
        )
        # 规则路径只识别字面清晰的纯工作区动作，统一打成 workspace mode
        return {"mode": "workspace", **rule_plan}

    if use_llm:
        return _llm_detect_workspace_plan(text)
    return None
