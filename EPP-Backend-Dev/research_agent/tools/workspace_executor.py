from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
import re
from typing import Any, cast
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from django.conf import settings

from business.utils.user_workspace import (
    get_workspace_root,
    list_workspace_dir,
    safe_resolve,
    sanitize_filename,
    workspace_file_info,
)

from ..site_access_control import evaluate_target_domain, normalize_domain
from .base import ToolAuditEvent, make_audit, truncate_text
from .web_fetch_executor import is_host_allowed


def _workspace_debug(msg: str) -> None:
    """工作区工具诊断输出（runserver 控制台可见，前缀便于 grep）。"""
    print(msg, flush=True)


def _normalize_workspace_download_url(raw: object) -> str:
    """
    将模型/检索返回的「类 URL 字符串」规整为可传给 httpx 的 http(s) URL。

    处理：首尾引号/反引号、Markdown 链接 [](url)、正文中首个 http(s) 片段、
    无 scheme 的 `arxiv.org/...` / `www.example.com/...`、协议相对 `//host/...`。
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    s = s.strip(' "\'"“”‘’`「」')
    md = re.search(r"\]\(\s*(https?://[^)\s]+)\s*\)", s, re.I)
    if md:
        s = md.group(1)
    if not re.match(r"^https?://", s, re.I):
        bare = re.search(r"(https?://[^\s\]>)\]}'\",，。]+)", s, re.I)
        if bare:
            s = bare.group(1).rstrip(".,;，。)]}\"'")
    s = s.split()[0] if s else ""
    s = s.rstrip(".,;，。)]}\"'")
    if s.startswith("//"):
        return "https:" + s
    parsed = urlparse(s)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"http", "https"}:
        return s
    if parsed.netloc or not parsed.path:
        return ""
    first = parsed.path.split("/")[0]
    if "." in first and " " not in first and not first.startswith("."):
        return "https://" + s.lstrip("/")
    return ""


@dataclass(frozen=True)
class WorkspaceActionResult:
    ok: bool
    output: dict[str, object]
    audit: ToolAuditEvent
    requires_confirmation: bool = False
    confirmation_payload: dict[str, object] | None = None
    error_code: str = ""
    error_message: str = ""


LOW_RISK_ACTIONS = {"ls", "read", "find", "grep", "extract_pdf"}
MEDIUM_RISK_ACTIONS = {
    "write",
    "mkdir",
    "download",
    "cp",
    "tar",
    "untar",
}
HIGH_RISK_ACTIONS = {"rm", "mv"}
SUPPORTED_ACTIONS = LOW_RISK_ACTIONS | MEDIUM_RISK_ACTIONS | HIGH_RISK_ACTIONS


def _max_text_bytes() -> int:
    return int(getattr(settings, "RA_WORKSPACE_MAX_TEXT_BYTES", 512 * 1024 * 40))


def _max_matches() -> int:
    return int(getattr(settings, "RA_WORKSPACE_MAX_MATCHES", 200))


def _err(code: str, message: str, *, action: str, **meta: object) -> WorkspaceActionResult:
    return WorkspaceActionResult(
        ok=False,
        output={},
        error_code=code,
        error_message=message,
        audit=make_audit("workspace", "error", message, action=action, **meta),
    )


def _resolve(user_id: str, rel_path: object, *, action: str) -> tuple[Path | None, WorkspaceActionResult | None]:
    path_text = str(rel_path or "").strip().lstrip("/").lstrip("\\")
    target = safe_resolve(str(user_id), path_text)
    if target is None:
        return None, _err("WORKSPACE_PATH_DENIED", "路径越界或非法", action=action, path=path_text)
    return target, None


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _safe_child_name(raw: object) -> str:
    return sanitize_filename(str(raw or "").strip())


def coalesce_workspace_args(action: str, raw: dict[str, Any]) -> dict[str, object]:
    """
    将 LLM / 路由层传入的 args 规整为各 handler 使用的**统一字段名**。

    - 忽略 ``overwrite`` / ``force``：是否覆盖、是否允许删除等由**工具批次执行前**
      用户确认保证；执行阶段一律按「存在则覆盖、可删则删」处理。
    - 接受常见字段别名（如 ``glob``→``pattern``），与路由层入参对齐。
    """
    r = {k: v for k, v in raw.items() if k not in ("overwrite", "force")}

    if action == "ls":
        paths = r.get("paths")
        if paths is None and r.get("path") is not None:
            paths = [r["path"]]
        if not isinstance(paths, list):
            paths = []
        if not paths:
            paths = ["."]
        return {"paths": paths}

    if action == "read":
        out: dict[str, object] = {
            "path": r.get("path") or "",
        }
        # 不再把 LLM 的 limit/max_bytes 传入 read：模型常误填为小整数（如 10000），
        # 被当作「整文件读入前最大字节」会导致大论文永远无法读取。
        start = r.get("start")
        if start is None:
            start = r.get("line_start")
        end = r.get("end")
        if end is None:
            end = r.get("line_end")
        if start is not None:
            out["start"] = start
        if end is not None:
            out["end"] = end
        return out

    if action == "write":
        out_w: dict[str, object] = {
            "path": r.get("path") or "",
            "content": r.get("content") or "",
            "append": r.get("append", False),
        }
        if r.get("limit") is not None:
            out_w["limit"] = r.get("limit")
        ws = r.get("start")
        if ws is None:
            ws = r.get("line_start")
        we = r.get("end")
        if we is None:
            we = r.get("line_end")
        if ws is not None:
            out_w["start"] = ws
        if we is not None:
            out_w["end"] = we
        return out_w

    if action == "mkdir":
        return {"path": r.get("path") or ""}

    if action == "rm":
        paths = r.get("paths")
        if paths is None and r.get("path") is not None:
            paths = [r["path"]]
        if not isinstance(paths, list):
            paths = []
        return {"paths": paths}

    if action in {"cp", "mv"}:
        return {"src": r.get("src") or "", "dst": r.get("dst") or ""}

    if action == "download":
        url = r.get("url") or r.get("link") or r.get("href") or r.get("source_url") or ""
        into = r.get("into")
        if into is None:
            into = r.get("path") or r.get("dir") or ""
        name = r.get("name")
        if name is None:
            name = r.get("filename")
        return {"url": url, "into": into, "name": name}

    if action == "find":
        pattern = r.get("pattern")
        if pattern is None:
            pattern = r.get("glob")
        lim = r.get("limit")
        if lim is None:
            lim = r.get("max_matches")
        return {
            "path": r.get("path") or "",
            "pattern": pattern or "*",
            "limit": lim,
        }

    if action == "tar":
        raw_paths = r.get("paths")
        if raw_paths is None and r.get("path") is not None:
            raw_paths = [r["path"]]
        if isinstance(raw_paths, str):
            paths: list[object] = [raw_paths]
        elif isinstance(raw_paths, (list, tuple)):
            paths = list(raw_paths)
        else:
            paths = []
        out = r.get("out")
        if out is None:
            out = r.get("output")
        return {"paths": paths, "out": out or "archive.zip"}

    if action == "untar":
        into = r.get("into")
        if into is None:
            into = r.get("output")
        return {"path": r.get("path") or "", "into": into}

    if action == "extract_pdf":
        lim = r.get("limit")
        if lim is None:
            lim = r.get("max_chars")
        out = r.get("out")
        if out is None:
            out = r.get("output")
        return {"path": r.get("path") or "", "out": out, "limit": lim}

    if action == "grep":
        rx = r.get("regex")
        if rx is None or str(rx).strip() == "":
            rx = r.get("pattern")
        lim = r.get("limit")
        if lim is None:
            lim = r.get("max_matches")
        return {
            "path": r.get("path") or "",
            "regex": str(rx or "").strip(),
            "glob": str(r.get("glob") or "*").strip() or "*",
            "limit": lim,
            "max_file_bytes": r.get("max_file_bytes"),
        }

    return dict(r)


def execute_workspace_action(
    *,
    user_id: str,
    action: str,
    args: dict[str, object] | None,
    risk_confirmation_strategy: str,  # noqa: ARG001 — 签名保留；确认由上层在批次前完成
) -> WorkspaceActionResult:
    normalized = (action or "").strip()
    runtime_args = args or {}
    if not user_id:
        return _err("WORKSPACE_USER_REQUIRED", "缺少用户身份，无法定位工作区", action=normalized)
    if normalized not in SUPPORTED_ACTIONS:
        return _err("WORKSPACE_ACTION_UNSUPPORTED", f"不支持的工作区动作: {normalized}", action=normalized)

    canonical = coalesce_workspace_args(normalized, cast(dict[str, Any], dict(runtime_args)))

    handlers = {
        "ls": _ls,
        "read": _read,
        "write": _write,
        "mkdir": _mkdir,
        "rm": _rm,
        "cp": _cp,
        "mv": _mv,
        "download": _download_url,
        "find": _find,
        "grep": _grep,
        "tar": _tar,
        "untar": _untar,
        "extract_pdf": _extract_pdf,
    }
    return handlers[normalized](str(user_id), canonical)


def _ls(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    paths: [str]
    """
    paths = list(args.get("paths") or [])
    rel_paths = [str(p).strip().lstrip("/") for p in paths]
    action = f"ls {rel_paths}"
    
    res_items = []
    for rel_path in rel_paths:
        items, error = list_workspace_dir(user_id, rel_path)
        if error:
            code = "WORKSPACE_PATH_DENIED" if "越界" in error else "WORKSPACE_LIST_FAILED"
            return _err(code, error, action=action, path=rel_path)
        res_items.extend(items)
        
    return WorkspaceActionResult(
        ok=True,
        output={"items": res_items},
        audit=make_audit("workspace", "ok", "列出工作区目录", action=action, path=rel_paths, count=len(res_items)),
    )


def _read(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    path: str
    limit: 历史字段，**不再参与**「能否读入」判断（模型常误填为小整数导致反复失败）；
          整文件读入前的体积上限固定为 ``RA_WORKSPACE_MAX_TEXT_BYTES``（缺省见 ``_max_text_bytes``）。
    start, end: int | None — 若任一有值，则按 **1-based 闭区间** 返回行切片；缺省 start=1、end=最后一行

    行以 ``\\n`` 分割（与 write 行模式一致）；整文件读入仍受系统字节上限约束。
    """
    p = str(args.get("path") or "")
    action = f"read {p}"
    target, error = _resolve(user_id, p, action=action)
    if error:
        return error
    assert target is not None
    if not target.exists() or not target.is_file():
        return _err("WORKSPACE_NOT_FOUND", "文本文件不存在", action=action, path=p)
    max_bytes = _max_text_bytes()
    file_size = target.stat().st_size
    if file_size > max_bytes:
        return _err(
            "WORKSPACE_FILE_TOO_LARGE",
            f"文件约 {file_size} 字节，超过系统读入上限 {max_bytes} 字节；"
            f"请用 start/end 按行分段读取、或改用 extract_pdf/grep，勿依赖 read 的 limit 参数扩大整文件读入。",
            action=action,
            path=p,
        )
    encoding = "utf-8"
    try:
        content = target.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return _err("WORKSPACE_DECODE_FAILED", "文件不是指定编码的文本", action=action, path=p)

    start_raw, end_raw = args.get("start"), args.get("end")
    use_lines = start_raw is not None or end_raw is not None
    root = get_workspace_root(user_id)
    rel = _rel(target, root)

    if not use_lines:
        return WorkspaceActionResult(
            True,
            {"path": rel, "content": content},
            make_audit(
                "workspace",
                "ok",
                "读取文本文件",
                action=action,
                path=p,
                bytes=len(content.encode(encoding, errors="ignore")),
            ),
        )

    lines = content.split("\n")
    n = len(lines)
    try:
        start = int(start_raw) if start_raw is not None else 1
        end = int(end_raw) if end_raw is not None else n
    except (TypeError, ValueError):
        return _err("WORKSPACE_LINE_RANGE_INVALID", "start/end 须为整数", action=action, path=p)
    if start < 1 or end < 1 or end < start or start > n:
        return _err(
            "WORKSPACE_LINE_RANGE_INVALID",
            f"行范围无效：文件共 {n} 行，请求 start={start}, end={end}",
            action=action,
            path=p,
        )
    end = min(end, n)
    slice_lines = lines[start - 1 : end]
    body = "\n".join(slice_lines)
    return WorkspaceActionResult(
        True,
        {
            "path": rel,
            "content": body,
            "start": start,
            "end": end,
            "total_lines": n,
        },
        make_audit("workspace", "ok", "按行读取文本文件", action=action, path=p, lines=len(slice_lines)),
    )


def _grep(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    path: str — 搜索根（文件或目录，相对工作区；空串表示根）
    regex: str — Python ``re`` 正则，按**行**匹配（对每行 ``re.search``）
    glob: str — 相对 path 下的路径 glob（如 ``*.py``、``**/*.md``），默认 ``*``
    limit: int | None — 最多返回匹配条数
    max_file_bytes: int | None — 单文件读入上限，缺省同全局文本上限
    """
    action = "grep"
    pattern = str(args.get("regex") or "")
    if not pattern:
        return _err("WORKSPACE_GREP_EMPTY_PATTERN", "grep 须提供非空 regex", action=action, path="")

    try:
        cre = re.compile(pattern)
    except re.error as exc:
        return _err("WORKSPACE_GREP_BAD_REGEX", f"正则无效: {exc}", action=action, path=pattern)

    root_rel = str(args.get("path") or "").strip()
    file_glob = str(args.get("glob") or "*").strip() or "*"
    max_matches = int(args.get("limit") or _max_matches())
    max_file_bytes = int(args.get("max_file_bytes") or _max_text_bytes())
    max_files = int(getattr(settings, "RA_WORKSPACE_GREP_MAX_FILES", 4000))

    target, error = _resolve(user_id, root_rel or ".", action=action)
    if error:
        return error
    assert target is not None
    if not target.exists():
        return _err("WORKSPACE_NOT_FOUND", "搜索路径不存在", action=action, path=root_rel)

    root = get_workspace_root(user_id)
    matches: list[dict[str, object]] = []
    files_scanned = 0

    def scan_file(fp: Path) -> bool:
        nonlocal files_scanned
        if len(matches) >= max_matches:
            return True
        try:
            if not fp.is_file() or fp.stat().st_size > max_file_bytes:
                return False
        except OSError:
            return False
        files_scanned += 1
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        for lineno, line in enumerate(text.split("\n"), start=1):
            if cre.search(line):
                rel_p = _rel(fp, root)
                matches.append(
                    {
                        "path": rel_p,
                        "line": lineno,
                        "text": line if len(line) <= 800 else line[:800] + "…",
                    }
                )
                if len(matches) >= max_matches:
                    return True
        return False

    if target.is_file():
        rel_one = _rel(target, root)
        if not (fnmatch.fnmatch(rel_one, file_glob) or fnmatch.fnmatch(target.name, file_glob)):
            return WorkspaceActionResult(
                True,
                {"matches": [], "count": 0, "truncated": False, "files_scanned": 0},
                make_audit("workspace", "ok", "grep 搜索（路径与 glob 不匹配）", action=action, path=root_rel, count=0),
            )
        scan_file(target)
    else:
        base = target
        for fp in sorted(base.rglob("*")):
            if files_scanned >= max_files:
                break
            if not fp.is_file():
                continue
            try:
                rel_scan = fp.relative_to(base).as_posix()
            except ValueError:
                continue
            if not fnmatch.fnmatch(rel_scan, file_glob):
                continue
            if scan_file(fp):
                break

    return WorkspaceActionResult(
        True,
        {
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= max_matches or files_scanned >= max_files,
            "files_scanned": files_scanned,
        },
        make_audit(
            "workspace",
            "ok",
            "grep 搜索",
            action=action,
            path=root_rel,
            count=len(matches),
        ),
    )


def _write(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    path: str
    append: bool
    content: str

    行替换模式：提供 ``start`` / ``end``（1-based 闭区间）之一或两者时，将文件中该行区间
    替换为 ``content`` 按 ``\\n`` 拆分后的行序列；``append`` 与行模式互斥。

    非 append 且无行参数：整文件写入（已存在普通文件则先删后写）。
    """
    action = f"write {args.get('path')}"
    append = bool(args.get("append", False))
    content = str(args.get("content") or "")
    target, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert target is not None
    if target.exists() and target.is_dir():
        return _err("WORKSPACE_IS_DIRECTORY", "目标路径是目录", action=action, path=args.get("path"))

    root = get_workspace_root(user_id)
    start_raw, end_raw = args.get("start"), args.get("end")
    line_mode = start_raw is not None or end_raw is not None

    if append and line_mode:
        return _err("WORKSPACE_ARGS_CONFLICT", "append 与按行替换不能同时使用", action=action, path=args.get("path"))

    if line_mode:
        if not target.exists() or not target.is_file():
            return _err("WORKSPACE_NOT_FOUND", "按行写入要求文件已存在", action=action, path=args.get("path"))
        max_bytes = int(args.get("limit") or _max_text_bytes())
        if target.stat().st_size > max_bytes:
            return _err("WORKSPACE_FILE_TOO_LARGE", f"文件超过读取上限 {max_bytes} 字节", action=action, path=args.get("path"))
        try:
            old = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return _err("WORKSPACE_DECODE_FAILED", "文件不是 UTF-8 文本，无法按行替换", action=action, path=args.get("path"))
        lines = old.split("\n")
        n = len(lines)
        try:
            start = int(start_raw) if start_raw is not None else 1
            end = int(end_raw) if end_raw is not None else n
        except (TypeError, ValueError):
            return _err("WORKSPACE_LINE_RANGE_INVALID", "start/end 须为整数", action=action, path=args.get("path"))
        if start < 1 or end < 1 or end < start:
            return _err(
                "WORKSPACE_LINE_RANGE_INVALID",
                f"行范围无效：文件共 {n} 行，请求 start={start}, end={end}",
                action=action,
                path=args.get("path"),
            )
        new_middle = content.split("\n")
        end_used: int
        if start == n + 1:
            if end != start:
                return _err(
                    "WORKSPACE_LINE_RANGE_INVALID",
                    f"在文件末尾插入新行时须 start=end={n + 1}（当前 n={n}）",
                    action=action,
                    path=args.get("path"),
                )
            new_lines = lines + new_middle
            end_used = end
        else:
            if start > n:
                return _err(
                    "WORKSPACE_LINE_RANGE_INVALID",
                    f"start 超出文件行数：共 {n} 行",
                    action=action,
                    path=args.get("path"),
                )
            end_clamped = min(end, n)
            if end_clamped < start:
                return _err(
                    "WORKSPACE_LINE_RANGE_INVALID",
                    f"行范围无效：start={start}, end={end}（文件共 {n} 行）",
                    action=action,
                    path=args.get("path"),
                )
            new_lines = lines[: start - 1] + new_middle + lines[end_clamped:]
            end_used = end_clamped
        new_text = "\n".join(new_lines)
        if len(new_text.encode("utf-8")) > _max_text_bytes():
            return _err("WORKSPACE_CONTENT_TOO_LARGE", "替换后内容超过文本大小上限", action=action, path=args.get("path"))
        _ensure_parent(target)
        target.write_text(new_text, encoding="utf-8")
        rel = _rel(target, root)
        return WorkspaceActionResult(
            True,
            {
                "path": rel,
                "bytes": target.stat().st_size,
                "start": start,
                "end": end_used,
                "total_lines": len(new_lines),
            },
            make_audit("workspace", "ok", "按行写入文本文件", action=action, path=rel),
        )

    if target.exists() and target.is_file() and not append:
        target.unlink()

    bytes = len(content.encode("utf-8"))
    if append and target.exists():
        bytes += target.stat().st_size
    if bytes > _max_text_bytes():
        return _err("WORKSPACE_CONTENT_TOO_LARGE", "写入内容超过文本大小上限", action=action, path=args.get("path"))
    _ensure_parent(target)
    with target.open(mode="a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    rel = _rel(target, root)
    return WorkspaceActionResult(True, {"path": rel, "bytes": target.stat().st_size}, make_audit("workspace", "ok", "写入文本文件", action=action, path=rel))


def _mkdir(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    path: str
    """
    action = f"mkdir {args.get('path')}"
    target, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert target is not None
    if target.exists() and not target.is_dir():
        return _err("WORKSPACE_CONFLICT", "目标路径已存在且不是目录", action=action, path=args.get("path"))
    target.mkdir(parents=True, exist_ok=True)
    rel = _rel(target, get_workspace_root(user_id))
    return WorkspaceActionResult(True, {"path": rel}, make_audit("workspace", "ok", "创建目录", action=action, path=rel))


def _rm(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    paths: [str]

    须在**本工具批次执行前**由用户确认；此处不再要求 force 标志。
    """
    paths_arg = list(args.get("paths") or [])
    action = f"rm {paths_arg}"
    if not paths_arg:
        return _err("WORKSPACE_RM_EMPTY", "未指定要删除的路径", action=action, path="")

    for path in paths_arg:
        target, error = _resolve(user_id, path, action=action)
        if error:
            return error
        if target.exists():
            try:
                target.relative_to(get_workspace_root(user_id))
            except ValueError:
                return _err("WORKSPACE_PATH_DENIED", "删除目标越界", action=action, path=str(path or ""))
            if target.is_file():
                target.unlink()
            else:
                shutil.rmtree(target, ignore_errors=True)
    return WorkspaceActionResult(True, {"status": "ok"},
                                 make_audit("workspace", "ok", "删除", action=action, path=paths_arg))


def _cp(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    return _copy_or_move(user_id, args, move=False)


def _mv(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    return _copy_or_move(user_id, args, move=True)


def _copy_or_move(user_id: str, args: dict[str, object], *, move: bool) -> WorkspaceActionResult:
    """
    src: str
    dst: str

    目标已存在时默认覆盖。是否允许覆盖由批次执行前的用户确认保证。
    """
    src_path = args.get("src") or ""
    dst_path = args.get("dst") or ""
    action = "mv" if move else "cp"
    action += f" {src_path} {dst_path}"
    src, error = _resolve(user_id, args.get("src"), action=action)
    if error:
        return error
    dst, error = _resolve(user_id, args.get("dst"), action=action)
    if error:
        return error
    assert src is not None and dst is not None
    if not src.exists():
        return _err("WORKSPACE_NOT_FOUND", "源路径不存在", action=action, path=args.get("src"))
    root = get_workspace_root(user_id)

    # Unix `cp`/`mv` 语义：当 dst 解析为已存在的目录（含工作区根目录）时，
    # 自动把目标改写为 dst/src.name。这能消解 LLM 把"复制到根目录下"输出
    # 为 dst="" / dst="." / dst="/" 之类引发的伪冲突。
    dst_was_directory = False
    if dst.exists() and dst.is_dir():
        dst = dst / src.name
        dst_was_directory = True

    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    _ensure_parent(dst)
    if move:
        shutil.move(str(src), str(dst))
    elif src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    rel = _rel(dst, root)
    detail = "移动路径" if move else "复制路径"
    if dst_was_directory:
        detail = f"{detail}（自动追加源文件名 {src.name}）"
    return WorkspaceActionResult(
        True,
        {"path": rel},
        make_audit("workspace", "ok", detail, action=action, path=rel),
    )


def _download_url(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "download_url"
    raw_src = args.get("url") or args.get("link") or args.get("href") or args.get("source_url") or ""
    raw_in = str(raw_src or "").strip()
    raw_url = _normalize_workspace_download_url(raw_src)
    _workspace_debug(
        f"[research_agent][workspace] download_url 入参 url(raw)={raw_in!r} url(normalized)={raw_url!r}"
    )
    if not raw_url:
        return _err(
            "WORKSPACE_DOWNLOAD_INVALID_URL",
            "仅支持 http/https 下载；请传入完整 URL（含 https://），或 arxiv.org/... 等形式。",
            action=action,
            url=raw_in,
        )
    parsed = urlparse(raw_url)
    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return _err("WORKSPACE_DOWNLOAD_INVALID_URL", "仅支持 http/https 下载", action=action, url=raw_url)
    host = normalize_domain(parsed.hostname or "")
    if not host or not is_host_allowed(host, setting_name="RA_LOCAL_FILE_ALLOWED_HOSTS"):
        return _err("WORKSPACE_DOWNLOAD_HOST_DENIED", f"目标域名不在允许列表: {host}", action=action, url=raw_url, target_domain=host)
    site_decision = evaluate_target_domain(host)
    if not site_decision.allowed:
        return _err("WORKSPACE_DOWNLOAD_SITE_DENIED", site_decision.reason_message, action=action, url=raw_url, target_domain=host)
    filename = _safe_child_name(args.get("name") or Path(parsed.path).name or "download.bin")
    into_rel = str(args.get("into") or "").strip()
    target_dir, error = _resolve(user_id, into_rel, action=action)
    if error:
        return error
    assert target_dir is not None
    if target_dir.exists() and not target_dir.is_dir():
        return _err("WORKSPACE_NOT_DIRECTORY", "下载目标不是目录", action=action, path=into_rel)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / filename
    if dest.exists():
        dest.unlink(missing_ok=True)
    max_bytes = int(getattr(settings, "RA_LOCAL_FILE_MAX_BYTES", 20 * 1024 * 1024))
    timeout = float(getattr(settings, "RA_LOCAL_FILE_DOWNLOAD_TIMEOUT", 30.0))
    written = 0
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", raw_url) as resp:
                if resp.status_code >= 400:
                    return _err("WORKSPACE_DOWNLOAD_HTTP_ERROR", f"HTTP {resp.status_code}", action=action, url=raw_url)
                with open(dest, "wb") as fp:
                    for chunk in resp.iter_bytes():
                        written += len(chunk)
                        if written > max_bytes:
                            fp.close()
                            dest.unlink(missing_ok=True)
                            return _err("WORKSPACE_DOWNLOAD_TOO_LARGE", f"文件超过下载上限 {max_bytes} 字节", action=action, url=raw_url)
                        fp.write(chunk)
    except (httpx.RequestError, OSError) as exc:
        return _err("WORKSPACE_DOWNLOAD_FAILED", str(exc) or "下载失败", action=action, url=raw_url)
    rel = _rel(dest, get_workspace_root(user_id))
    return WorkspaceActionResult(True, {"path": rel, "bytes": written}, make_audit("workspace", "ok", "下载文件到工作区", action=action, path=rel, url=raw_url))


def _find(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    path: str — 搜索根目录（相对工作区，可为空串表示根）
    pattern: str — glob 模式
    limit: int | None — 最多返回条数
    """
    action = "find"
    rel_start = str(args.get("path") or "")
    pattern = str(args.get("pattern") or "*").strip() or "*"
    max_m = int(args.get("limit") or _max_matches())
    root = get_workspace_root(user_id)
    target, error = _resolve(user_id, args.get("path") or "", action=action)
    if error:
        return error
    assert target is not None

    if not target.exists() or not target.is_dir():
        return _err("WORKSPACE_NOT_DIRECTORY", "搜索起点不是目录", action=action, path=args.get("path"))
    
    matches = list(target.rglob(pattern))
    if len(matches) > max_m:
        matches = matches[:max_m]

    items = ['/' + str(m.relative_to(root)) for m in matches]
    _workspace_debug(
        f"[research_agent][workspace] find_files 完成 user_id={user_id!r} count={len(items)} "
        f"{items}"
    )
    return WorkspaceActionResult(
        True,
        {
            "items": items,
            "count": len(items),
            "pattern": pattern,
            "path": rel_start,
        },
        make_audit("workspace", "ok", "查找文件", action=action, glob=pattern, count=len(items)),
    )


def _tar(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    paths: [str]
    out: str — 生成的 zip 相对路径；已存在则默认覆盖
    """
    raw_paths = args.get("paths")
    if isinstance(raw_paths, str):
        paths = [raw_paths]
    elif isinstance(raw_paths, (list, tuple)):
        paths = list(raw_paths)
    else:
        paths = []
    out_path = str(args.get("out") or "archive.zip").strip() or "archive.zip"
    action = f"tar {paths} {out_path}"
    output, error = _resolve(user_id, out_path, action=action)
    if error:
        return error
    assert output is not None

    root = get_workspace_root(user_id)
    if output.exists():
        if output.is_file():
            output.unlink()
        else:
            return _err("WORKSPACE_CONFLICT", "压缩包输出路径已存在且为目录", action=action, path=out_path)
    _ensure_parent(output)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            src, error = _resolve(user_id, p, action = action)
            if error:
                return error
            if not src.exists():
                return _err("WORKSPACE_NOT_FOUND", "待压缩路径不存在", action=action, path=str(p))
            if src.is_dir():
                for current, _, files in os.walk(src):
                    for name in files:
                        file_path = Path(current) / name
                        if file_path == output:
                            continue
                        zf.write(file_path, file_path.relative_to(src.parent).as_posix())
            else:
                zf.write(src, src.name)
    rel = _rel(output, root)
    return WorkspaceActionResult(True, {"path": rel, "bytes": output.stat().st_size}, make_audit("workspace", "ok", "生成 zip 压缩包", action=action, path=rel))


def _untar(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    解压 zip 压缩包到指定目录（默认原地解压：into = zip 所在目录）。

    path: str — zip 文件相对路径
    into: str | None — 解压到的目录（相对工作区）；缺省为 zip 父目录

    已存在的同名文件：**默认覆盖**。是否允许由批次执行前的用户确认保证。

    防护：
    - zip slip：每个 member 解析后必须落在工作区根目录之内；
    - 对绝对路径成员、含 `..` 段的成员一律拒收；
    - 单个 member 体积限制：复用 `RA_WORKSPACE_MAX_TEXT_BYTES * 32` 作为粗略上界。
    """
    action = f"untar {args.get('path')} {args.get('into')}"
    src, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert src is not None
    if not src.exists() or not src.is_file():
        return _err("WORKSPACE_NOT_FOUND", "压缩包不存在", action=action, path=args.get("path"))
    if not zipfile.is_zipfile(src):
        return _err("WORKSPACE_INVALID_ARCHIVE", "目标文件不是有效的 zip 压缩包", action=action, path=args.get("path"))

    dest_arg = args.get("into")
    if dest_arg is not None and str(dest_arg).strip():
        dest, error = _resolve(user_id, dest_arg, action=action)
        if error:
            return error
        assert dest is not None
    else:
        dest = src.parent

    root = get_workspace_root(user_id)
    try:
        dest.relative_to(root)
    except ValueError:
        return _err("WORKSPACE_PATH_DENIED", "解压目标越界", action=action, path=str(dest_arg or ""))
    if dest.exists() and not dest.is_dir():
        return _err("WORKSPACE_NOT_DIRECTORY", "解压目标存在但不是目录", action=action, path=str(dest_arg or ""))
    dest.mkdir(parents=True, exist_ok=True)

    member_size_cap = _max_text_bytes() * 32
    extracted: list[str] = []
    try:
        with zipfile.ZipFile(src, "r") as zf:
            members = zf.infolist()
            for info in members:
                name = info.filename or ""
                if not name:
                    continue
                if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
                    return _err(
                        "WORKSPACE_PATH_DENIED",
                        f"压缩包成员路径不安全: {name}",
                        action=action,
                        path=name,
                    )
                target = (dest / name).resolve()
                try:
                    target.relative_to(root)
                except ValueError:
                    return _err(
                        "WORKSPACE_PATH_DENIED",
                        f"压缩包成员越界工作区: {name}",
                        action=action,
                        path=name,
                    )
                if info.file_size > member_size_cap:
                    return _err(
                        "WORKSPACE_FILE_TOO_LARGE",
                        f"压缩包内成员 {name} 超过 {member_size_cap} 字节解压上限",
                        action=action,
                        path=name,
                    )

            for info in members:
                name = info.filename or ""
                if not name:
                    continue
                target = (dest / name).resolve()
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as zi, open(target, "wb") as out:
                    shutil.copyfileobj(zi, out)
                extracted.append(name)
    except zipfile.BadZipFile as exc:
        return _err("WORKSPACE_INVALID_ARCHIVE", f"压缩包损坏: {exc}", action=action, path=args.get("path"))

    rel_dest = _rel(dest, root) or "."
    return WorkspaceActionResult(
        True,
        {"path": rel_dest, "extracted_count": len(extracted)},
        make_audit(
            "workspace",
            "ok",
            "解压 zip 压缩包",
            action=action,
            path=rel_dest,
            count=len(extracted),
        ),
    )


def _extract_pdf(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    path: str
    out: str | None — 将抽取文本写入该相对路径（UTF-8）；缺省仅返回 JSON 内 text
    limit: int | None — 最大字符数
    """
    action = "extract_pdf_text"
    target, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert target is not None
    if not target.exists() or not target.is_file():
        return _err("WORKSPACE_NOT_FOUND", "PDF 文件不存在", action=action, path=args.get("path"))
    try:
        import fitz
    except ImportError:
        return _err("WORKSPACE_PDF_BACKEND_MISSING", "未安装 PDF 文本提取依赖 pymupdf", action=action)
    max_chars = int(args.get("limit") or 1200000)
    try:
        with fitz.open(str(target)) as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        return _err("WORKSPACE_PDF_EXTRACT_FAILED", str(exc) or "PDF 文本提取失败", action=action, path=args.get("path"))
    text = truncate_text(text, max_chars)
    out_path = str(args.get("out") or "").strip()
    output: dict[str, object] = {"path": _rel(target, get_workspace_root(user_id)), "text": text}
    if out_path:
        out_file, error = _resolve(user_id, out_path, action=action)
        if error:
            return error
        assert out_file is not None
        _ensure_parent(out_file)
        if out_file.exists() and out_file.is_file():
            out_file.unlink()
        out_file.write_text(text, encoding="utf-8")
        output["out"] = _rel(out_file, get_workspace_root(user_id))
    return WorkspaceActionResult(True, output, make_audit("workspace", "ok", "提取 PDF 文本", action=action, path=output["path"], chars=len(text)))
