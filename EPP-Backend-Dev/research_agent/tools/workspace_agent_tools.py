"""
工作区 Agent 的工具目录与 LLM 工具调用适配。

动作名采用 Unix 式短名；参数经 ``coalesce_workspace_args`` 与执行器对齐。
``overwrite`` / ``force`` 等标志已废弃，由批次执行前的用户确认保证安全性。
"""

from __future__ import annotations

import json
from typing import Any

from .workspace_executor import (
    SUPPORTED_ACTIONS,
    coalesce_workspace_args,
    execute_workspace_action,
)


def format_tools_catalog_markdown() -> str:
    """供工作区 Agent 系统/用户提示拼接的静态工具表（action 须与下表「名称」一致）。"""
    return (
        "## 可调用的工作区动作（action 字段须与下表「名称」完全一致）\n\n"
        "路径均为相对工作区根的 POSIX 路径；已存在文件默认覆盖（由执行前确认保证）。\n"
        "行号均为 **1-based** 闭区间；行以 ``\\n`` 分割（与常见编辑器一致）。\n\n"
        "| 名称 | args（对象字段） |\n"
        "| --- | --- |\n"
        "| ls | ``paths``: string[] — 要列出的目录，常用 ``[\".\"]`` |\n"
        "| read | ``path``；可选 ``start``/``end`` 按行切片（缺省则读全文）；"
        "可选 ``limit`` 整文件最大字节数 |\n"
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


def _compact_json(data: object, limit: int = 800) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False)
    except TypeError:
        text = repr(data)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def run_llm_workspace_tool_batch(
    *,
    user_id: str,
    tool_calls: list[dict[str, Any]],
    risk_confirmation_strategy: str,
) -> list[str]:
    """顺序执行一轮 ``tool_calls``，返回人类可读的观测行。"""
    lines: list[str] = []
    for raw in tool_calls:
        if not isinstance(raw, dict):
            lines.append(f"(跳过非法 tool_call: {raw!r})")
            continue
        name = str(raw.get("action") or raw.get("tool") or "").strip()
        raw_args = raw.get("args")
        args = dict(raw_args) if isinstance(raw_args, dict) else {}
        adapted = adapt_llm_workspace_call(name, args)
        if adapted is None:
            lines.append(f"{name}: 未知动作或参数不完整，args={_compact_json(args)}")
            continue
        ex_action, ex_args = adapted
        res = execute_workspace_action(
            user_id=str(user_id),
            action=ex_action,
            args=ex_args,
            risk_confirmation_strategy=risk_confirmation_strategy,
        )
        if res.ok:
            lines.append(f"{ex_action}: 成功; output={_compact_json(res.output)}")
        else:
            lines.append(f"{ex_action}: 失败 code={res.error_code} msg={res.error_message}")
    return lines
