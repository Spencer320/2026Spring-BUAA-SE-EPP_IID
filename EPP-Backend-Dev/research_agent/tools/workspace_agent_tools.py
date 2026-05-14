"""
工作区 Agent 的工具目录与 LLM 工具调用适配。

动作名采用 Unix 式短名；参数经 ``coalesce_workspace_args`` 与执行器对齐。
开发阶段不实现逐工具风险确认，批次内顺序执行；执行记录供会话/任务结果展示。
"""

from __future__ import annotations

import json
from typing import Any

from .base import truncate_text
from .workspace_executor import (
    SUPPORTED_ACTIONS,
    WorkspaceActionResult,
    coalesce_workspace_args,
    execute_workspace_action,
)


def format_tools_catalog_markdown() -> str:
    """供工作区 Agent 系统/用户提示拼接的静态工具表（action 须与下表「名称」一致）。"""
    return (
        "## 可调用的工作区动作（action 字段须与下表「名称」完全一致）\n\n"
        "路径均为相对工作区根的 POSIX 路径；已存在文件默认覆盖（开发阶段无单独确认）。\n"
        "行号均为 **1-based** 闭区间；行以 ``\\n`` 分割（与常见编辑器一致）。\n\n"
        "| 名称 | args（对象字段） |\n"
        "| --- | --- |\n"
        "| ls | ``paths``: string[] — 要列出的目录，常用 ``[\".\"]`` |\n"
        "| read | ``path``；可选 ``start``/``end`` 按行切片（缺省则读全文）。"
        "整文件读入体积上限由系统配置（``RA_WORKSPACE_MAX_TEXT_BYTES``），**勿传 limit**；大文本请分段 read 或 grep。 |\n"
        "| write | ``path``, ``content``；可选 ``append``；"
        "若提供 ``start``/``end`` 之一则为**按行替换**（``content`` 按 ``\\n`` 拆成多行插入）；"
        "在文件末尾追加行时须 ``start=end=总行数+1``；可选 ``limit`` 读入原文件时的字节上限 |\n"
        "| mkdir | ``path`` |\n"
        "| rm | ``paths``: string[] |\n"
        "| cp | ``src``, ``dst`` |\n"
        "| mv | ``src``, ``dst`` |\n"
        "| download | ``url``, ``into``（目标目录）；可选 ``name`` 保存文件名 |\n"
        "| find | ``path`` 搜索根（可 ``\"\"``）, ``pattern`` glob；可选 ``limit`` 最多条数 |\n"
        "| grep | ``regex``（Python ``re``，按行匹配）；``path`` 文件或目录；"
        "可选 ``glob`` 文件名过滤（如 ``*.py``）；可选 ``limit`` 最多匹配条数；"
        "可选 ``max_file_bytes`` 单文件读入上限 |\n"
        "| tar | ``paths``: string[]；``out`` 生成的 zip 相对路径 |\n"
        "| untar | ``path`` zip 文件；可选 ``into`` 解压目录（缺省为 zip 所在目录） |\n"
        "| extract_pdf | ``path``；可选 ``out`` 写出文本文件路径；可选 ``limit`` 最大字符数 |\n"
    )


def _coalesced_args_valid(action: str, c: dict[str, object]) -> bool:
    if action == "read":
        return bool(str(c.get("path") or "").strip())
    if action == "write":
        return bool(str(c.get("path") or "").strip())
    if action == "mkdir":
        return bool(str(c.get("path") or "").strip())
    if action == "ls":
        paths = c.get("paths")
        return isinstance(paths, list) and len(paths) > 0
    if action == "rm":
        paths = c.get("paths")
        return isinstance(paths, list) and len(paths) > 0
    if action in {"cp", "mv"}:
        return bool(str(c.get("src") or "").strip()) and bool(str(c.get("dst") or "").strip())
    if action == "download":
        return bool(str(c.get("url") or "").strip())
    if action == "find":
        return bool(str(c.get("pattern") or "").strip())
    if action == "grep":
        return bool(str(c.get("regex") or "").strip())
    if action == "tar":
        paths = c.get("paths")
        if not isinstance(paths, list) or not paths:
            return False
        return bool(str(c.get("out") or "").strip())
    if action == "untar":
        return bool(str(c.get("path") or "").strip())
    if action == "extract_pdf":
        return bool(str(c.get("path") or "").strip())
    return False


def adapt_llm_workspace_call(
    llm_action: str, args: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    """
    将 LLM 的 action + args 规整为执行器输入；非法或缺字段时返回 None。
    """
    a = (llm_action or "").strip()
    if not a or a not in SUPPORTED_ACTIONS:
        return None
    merged = coalesce_workspace_args(a, dict(args))
    if not _coalesced_args_valid(a, merged):
        return None
    return a, dict(merged)


def _args_path_only_for_log(action: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    用户可见执行记录：只保留路径/定位类字段；write 绝不包含 content。
    """
    a = (action or "").strip()
    keys: tuple[str, ...]
    if a == "write":
        keys = ("path", "append", "start", "end", "limit")
    elif a == "read":
        keys = ("path", "start", "end", "limit")
    elif a == "ls":
        keys = ("paths",)
    elif a == "mkdir":
        keys = ("path",)
    elif a == "rm":
        keys = ("paths",)
    elif a in ("cp", "mv"):
        keys = ("src", "dst")
    elif a == "download":
        keys = ("into", "name")
    elif a == "find":
        keys = ("path", "limit")
    elif a == "grep":
        keys = ("path", "glob", "limit", "max_file_bytes")
    elif a == "tar":
        keys = ("paths", "out")
    elif a == "untar":
        keys = ("path", "into")
    elif a == "extract_pdf":
        keys = ("path", "out", "limit")
    else:
        keys = ()

    out: dict[str, Any] = {}
    for k in keys:
        if k not in args:
            continue
        v = args[k]
        if k == "paths" and isinstance(v, list):
            out[k] = [str(p) for p in v[:500]]
        elif isinstance(v, str) and k in ("path", "src", "dst", "into", "out", "name"):
            out[k] = v[:2048]
        else:
            out[k] = v
    return out


def _llm_args_for_skipped_log(llm_action: str, args: dict[str, Any]) -> dict[str, Any]:
    """模型输出未通过适配时：尽量只记路径类字段（不记 content / 正文）。"""
    name = (llm_action or "").strip()
    if name in SUPPORTED_ACTIONS:
        return _args_path_only_for_log(name, dict(args))
    safe = frozenset(
        {
            "path",
            "paths",
            "src",
            "dst",
            "into",
            "out",
            "name",
            "append",
            "start",
            "end",
            "limit",
            "glob",
            "max_file_bytes",
        }
    )
    return {k: v for k, v in args.items() if k in safe}


def _compact_json(data: object, limit: int = 800) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False)
    except TypeError:
        text = repr(data)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


# 写入 transcript 给下一轮规划 LLM：避免对含巨型正文字段的 dict 做整体 _compact_json（800 字）
# 截断后既像「坏 JSON」又看不到成功信号，易诱发重复 extract_pdf/read。
_PREVIEW_CHARS = 8000


def _format_tool_success_line(action: str, res: WorkspaceActionResult) -> str:
    out = res.output if isinstance(res.output, dict) else {}
    if action == "extract_pdf":
        text = str(out.get("text") or "")
        path = str(out.get("path") or "")
        written = (str(out.get("out") or "").strip())
        preview = truncate_text(text, _PREVIEW_CHARS)
        extra = f"; written_to={written}" if written else ""
        return (
            f"{action}: 成功; path={path}; extracted_chars={len(text)}{extra}; "
            f"text_preview=\n<<<\n{preview}\n>>>"
        )
    if action == "read":
        content = str(out.get("content") or "")
        path = str(out.get("path") or "")
        preview = truncate_text(content, _PREVIEW_CHARS)
        start, end, tl = out.get("start"), out.get("end"), out.get("total_lines")
        line_note = ""
        if start is not None and end is not None and tl is not None:
            line_note = f"; lines={start}-{end}; total_lines={tl}"
        return f"{action}: 成功; path={path}{line_note}; content_preview=\n<<<\n{preview}\n>>>"
    return f"{action}: 成功; output={_compact_json(res.output)}"


def run_llm_workspace_tool_batch(
    *,
    user_id: str,
    tool_calls: list[dict[str, Any]],
    risk_confirmation_strategy: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """
    顺序执行一轮 ``tool_calls``。

    返回 (观测行, 结构化执行记录)；后者写入 ``workspace_tool_execution_log``（仅路径类参数，不含 write 正文）。
    """
    lines: list[str] = []
    executed: list[dict[str, Any]] = []
    for raw in tool_calls:
        if not isinstance(raw, dict):
            lines.append(f"(跳过非法 tool_call: {raw!r})")
            executed.append({"status": "skipped", "reason": "not_a_dict", "raw_preview": _compact_json(raw, 400)})
            continue
        name = str(raw.get("action") or raw.get("tool") or "").strip()
        raw_args = raw.get("args")
        args = dict(raw_args) if isinstance(raw_args, dict) else {}
        adapted = adapt_llm_workspace_call(name, args)
        if adapted is None:
            lines.append(f"{name}: 未知动作或参数不完整，args={_compact_json(args)}")
            executed.append(
                {
                    "status": "skipped_invalid",
                    "llm_action": name,
                    "llm_args": _llm_args_for_skipped_log(name, args),
                }
            )
            continue
        ex_action, ex_args = adapted
        log_args = _args_path_only_for_log(ex_action, dict(ex_args))
        res = execute_workspace_action(
            user_id=str(user_id),
            action=ex_action,
            args=ex_args,
            risk_confirmation_strategy=risk_confirmation_strategy,
        )
        if res.ok:
            lines.append(_format_tool_success_line(ex_action, res))
            executed.append({"status": "ok", "action": ex_action, "args": log_args})
        else:
            lines.append(f"{ex_action}: 失败 code={res.error_code} msg={res.error_message}")
            executed.append(
                {
                    "status": "error",
                    "action": ex_action,
                    "args": log_args,
                    "error_code": res.error_code,
                    "error_message": res.error_message,
                }
            )
    return lines, executed
