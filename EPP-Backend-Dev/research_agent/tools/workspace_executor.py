from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
import re
from typing import Any
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


LOW_RISK_ACTIONS = {"list_files", "file_info", "read_text", "find_files", "extract_pdf_text"}
MEDIUM_RISK_ACTIONS = {
    "write_text",
    "append_text",
    "mkdir",
    "download_url",
    "copy_path",
    "archive_zip",
    "extract_zip",
}
HIGH_RISK_ACTIONS = {"delete_path", "clear_dir", "move_path", "replace_text"}
SUPPORTED_ACTIONS = LOW_RISK_ACTIONS | MEDIUM_RISK_ACTIONS | HIGH_RISK_ACTIONS


def _max_text_bytes() -> int:
    return int(getattr(settings, "RA_WORKSPACE_MAX_TEXT_BYTES", 512 * 1024))


def _max_matches() -> int:
    return int(getattr(settings, "RA_WORKSPACE_MAX_MATCHES", 200))


def _conflict_error(
    action: str,
    args: dict[str, object],
    user_id: str,
    *,
    target_rel: str,
) -> WorkspaceActionResult:
    return _err(
        "WORKSPACE_CONFLICT",
        f"Target already exists: {target_rel}",
        action=action,
        args=args,
        risk_level="high",
        conflict_target=target_rel,
    )


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


def _walk_files(root: Path, start: Path, pattern: str, max_items: int) -> list[Path]:
    """
    在 start 下递归匹配 glob pattern，返回路径列表。

    同时匹配**文件**与**目录**（仅目录节点本身，不含其下文件），以便
    「按前缀找文件夹」「删目录前先搜索」等场景能拿到 rel_path。
    """
    matches: list[Path] = []
    for current, dirs, files in os.walk(start):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for d in dirs:
            p = Path(current) / d
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            if fnmatch.fnmatch(d, pattern) or fnmatch.fnmatch(rel, pattern):
                matches.append(p)
                if len(matches) >= max_items:
                    return matches
        for name in sorted(files):
            rel = (Path(current) / name).relative_to(root).as_posix()
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
                matches.append(Path(current) / name)
                if len(matches) >= max_items:
                    return matches
    return matches


def execute_workspace_action(
    *,
    user_id: str,
    action: str,
    args: dict[str, object] | None,
    risk_confirmation_strategy: str,
) -> WorkspaceActionResult:
    normalized = (action or "").strip()
    runtime_args = args or {}
    if not user_id:
        return _err("WORKSPACE_USER_REQUIRED", "缺少用户身份，无法定位工作区", action=normalized)
    if normalized not in SUPPORTED_ACTIONS:
        return _err("WORKSPACE_ACTION_UNSUPPORTED", f"不支持的工作区动作: {normalized}", action=normalized)

    handlers = {
        "list_files": _list_files,
        "file_info": _file_info,
        "read_text": _read_text,
        "write_text": _write_text,
        "append_text": _append_text,
        "mkdir": _mkdir,
        "delete_path": _delete_path,
        "clear_dir": _clear_dir,
        "copy_path": _copy_path,
        "move_path": _move_path,
        "download_url": _download_url,
        "find_files": _find_files,
        "replace_text": _replace_text,
        "archive_zip": _archive_zip,
        "extract_zip": _extract_zip,
        "extract_pdf_text": _extract_pdf_text,
    }
    return handlers[normalized](str(user_id), runtime_args)


def _list_files(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "list_files"
    rel_path = str(args.get("path") or "").strip().lstrip("/")
    items, error = list_workspace_dir(user_id, rel_path)
    if error:
        code = "WORKSPACE_PATH_DENIED" if "越界" in error else "WORKSPACE_LIST_FAILED"
        return _err(code, error, action=action, path=rel_path)
    return WorkspaceActionResult(
        ok=True,
        output={"path": rel_path, "items": items},
        audit=make_audit("workspace", "ok", "列出工作区目录", action=action, path=rel_path, count=len(items)),
    )


def _file_info(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "file_info"
    target, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert target is not None
    if not target.exists():
        return _err("WORKSPACE_NOT_FOUND", "文件或目录不存在", action=action, path=args.get("path"))
    root = get_workspace_root(user_id)
    info = workspace_file_info(target, root)
    return WorkspaceActionResult(True, {"item": info}, make_audit("workspace", "ok", "读取路径信息", action=action, path=info["rel_path"]))


def _read_text(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "read_text"
    target, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert target is not None
    if not target.exists() or not target.is_file():
        return _err("WORKSPACE_NOT_FOUND", "文本文件不存在", action=action, path=args.get("path"))
    max_bytes = int(args.get("max_bytes") or _max_text_bytes())
    if target.stat().st_size > max_bytes:
        return _err("WORKSPACE_FILE_TOO_LARGE", f"文件超过读取上限 {max_bytes} 字节", action=action, path=args.get("path"))
    encoding = str(args.get("encoding") or "utf-8")
    try:
        content = target.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return _err("WORKSPACE_DECODE_FAILED", "文件不是指定编码的文本", action=action, path=args.get("path"))
    return WorkspaceActionResult(
        True,
        {"path": _rel(target, get_workspace_root(user_id)), "content": content},
        make_audit("workspace", "ok", "读取文本文件", action=action, path=args.get("path"), bytes=len(content.encode(encoding, errors="ignore"))),
    )


def _write_text(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "write_text"
    target, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert target is not None
    if target.exists() and target.is_dir():
        return _err("WORKSPACE_IS_DIRECTORY", "目标路径是目录", action=action, path=args.get("path"))
    overwrite = bool(args.get("overwrite", False))
    root = get_workspace_root(user_id)
    if target.exists() and not overwrite:
        rel_target = _rel(target, root)
        return _conflict_error(action, args, user_id, target_rel=rel_target)
    content = str(args.get("content") or "")
    if len(content.encode("utf-8")) > _max_text_bytes():
        return _err("WORKSPACE_CONTENT_TOO_LARGE", "写入内容超过文本大小上限", action=action, path=args.get("path"))
    _ensure_parent(target)
    target.write_text(content, encoding=str(args.get("encoding") or "utf-8"))
    rel = _rel(target, root)
    return WorkspaceActionResult(True, {"path": rel, "bytes": target.stat().st_size}, make_audit("workspace", "ok", "写入文本文件", action=action, path=rel))


def _append_text(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "append_text"
    target, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert target is not None
    if target.exists() and target.is_dir():
        return _err("WORKSPACE_IS_DIRECTORY", "目标路径是目录", action=action, path=args.get("path"))
    content = str(args.get("content") or "")
    if len(content.encode("utf-8")) > _max_text_bytes():
        return _err("WORKSPACE_CONTENT_TOO_LARGE", "追加内容超过文本大小上限", action=action, path=args.get("path"))
    _ensure_parent(target)
    with open(target, "a", encoding=str(args.get("encoding") or "utf-8")) as fp:
        fp.write(content)
    rel = _rel(target, get_workspace_root(user_id))
    return WorkspaceActionResult(True, {"path": rel, "bytes": target.stat().st_size}, make_audit("workspace", "ok", "追加文本文件", action=action, path=rel))


def collect_file_relpaths_from_find_output(
    prev_output: dict[str, object],
    *,
    paths_glob: str = "",
) -> list[str]:
    """
    从上一步 find_files（或任何含 items 且带 rel_path/type 的输出）中筛出待删除的文件相对路径。

    paths_glob 缺省时使用 prev_output['search_glob']，再缺省为 '*'。
    仅包含 type=file 的项，避免把目录节点误当批量删除目标。
    """
    items = prev_output.get("items")
    if not isinstance(items, list):
        return []
    g = (paths_glob or "").strip() or str(prev_output.get("search_glob") or "").strip() or "*"
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        rp = str(item.get("rel_path") or "").strip().lstrip("/")
        if not rp:
            continue
        base = Path(rp).name
        if fnmatch.fnmatch(rp, g) or fnmatch.fnmatch(base, g):
            out.append(rp)
    return out


def inject_workspace_step_args(
    action: str,
    args: dict[str, Any],
    workspace_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    将上一步工作区工具输出注入当前步 args（lite / 旧编排器共用）。

    - replace_text + files_from=previous → 注入 files 列表；
    - delete_path + paths_from=previous / files_from=previous，
      或 path 为空且上一步为 find_files → 注入 paths，并移除空的 path，避免误删根。
    """
    if not workspace_results:
        return args
    prev = workspace_results[-1]
    prev_output = prev.get("output")
    if not isinstance(prev_output, dict):
        return args
    items = prev_output.get("items")
    if not isinstance(items, list):
        return args

    merged: dict[str, Any] = dict(args)
    files_from = str(merged.get("files_from") or "").strip()
    paths_from = str(merged.get("paths_from") or "").strip()

    if action == "replace_text":
        if files_from != "previous":
            return args
        files: list[str] = []
        for item in items:
            if isinstance(item, dict) and item.get("type") == "file" and item.get("rel_path"):
                files.append(str(item.get("rel_path")))
        merged["files"] = files
        return merged

    if action == "delete_path":
        inject_paths = paths_from == "previous" or files_from == "previous"
        prev_action = str(prev.get("action") or "").strip()
        path_empty = not str(merged.get("path") or "").strip()
        if not inject_paths and path_empty and prev_action == "find_files":
            inject_paths = True
        if not inject_paths:
            return args
        pg = str(merged.get("paths_glob") or "").strip()
        if not pg:
            pg = str(prev_output.get("search_glob") or "").strip() or "*"
        rels = collect_file_relpaths_from_find_output(prev_output, paths_glob=pg)
        merged["paths"] = rels
        merged.pop("path", None)
        _workspace_debug(
            f"[research_agent][workspace] inject 删除列表：由上一步 find_files 注入 "
            f"paths_count={len(rels)} paths_glob={pg!r} paths={rels!r}"
        )
        return merged

    return args


def _mkdir(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "mkdir"
    target, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert target is not None
    if target.exists() and not target.is_dir():
        return _err("WORKSPACE_CONFLICT", "目标路径已存在且不是目录", action=action, path=args.get("path"))
    target.mkdir(parents=True, exist_ok=True)
    rel = _rel(target, get_workspace_root(user_id))
    return WorkspaceActionResult(True, {"path": rel}, make_audit("workspace", "ok", "创建目录", action=action, path=rel))


def _delete_path_one_rel(user_id: str, raw_path: str, recursive: bool) -> WorkspaceActionResult:
    """删除单个相对路径（不含批量 paths 语义）。"""
    action = "delete_path"
    _workspace_debug(
        f"[research_agent][workspace] delete_path 开始 user_id={user_id!r} "
        f"args.path={raw_path!r} args.recursive={recursive}"
    )
    target, error = _resolve(user_id, raw_path, action=action)
    if error:
        _workspace_debug(
            f"[research_agent][workspace] delete_path 失败(解析) user_id={user_id!r} path={raw_path!r} "
            f"error_code={error.error_code!r} error_message={error.error_message!r}"
        )
        return error
    assert target is not None
    root = get_workspace_root(user_id)
    _workspace_debug(
        f"[research_agent][workspace] delete_path 已解析 user_id={user_id!r} workspace_root={root!s} "
        f"target_abs={target!s} is_dir={target.is_dir() if target.exists() else None} exists={target.exists()}"
    )
    if target == root:
        _workspace_debug(
            f"[research_agent][workspace] delete_path 拒绝：目标为工作区根 user_id={user_id!r} path={raw_path!r}"
        )
        return _err(
            "WORKSPACE_DELETE_ROOT_DENIED",
            "禁止删除工作区根目录。若出现本提示，通常是路径为空、为「.」或未解析到具体子路径；"
            "请先 list_files 或 find_files 确认 rel_path（工作区内的相对路径不包含磁盘上的用户 UUID 目录名）。"
            "若只想清空根下文件请用 clear_dir 且 path 为空。",
            action=action,
        )
    if not target.exists():
        _workspace_debug(
            f"[research_agent][workspace] delete_path 失败(不存在) user_id={user_id!r} path={raw_path!r} "
            f"target_abs={target!s}"
        )
        return _err("WORKSPACE_NOT_FOUND", "文件或目录不存在", action=action, path=raw_path)
    rel = _rel(target, root)
    was_dir = target.is_dir()
    if was_dir:
        if recursive:
            shutil.rmtree(target)
        else:
            try:
                target.rmdir()
            except OSError:
                _workspace_debug(
                    f"[research_agent][workspace] delete_path 失败(目录非空) user_id={user_id!r} rel={rel!r} "
                    f"recursive={recursive}"
                )
                return _err("WORKSPACE_DIRECTORY_NOT_EMPTY", "目录非空，请设置 recursive=true 并确认后删除", action=action, path=rel)
    else:
        target.unlink()
    kind = "directory" if was_dir else "file"
    _workspace_debug(
        f"[research_agent][workspace] delete_path 成功 user_id={user_id!r} deleted_rel={rel!r} "
        f"kind={kind} recursive={recursive}"
    )
    return WorkspaceActionResult(True, {"deleted": rel}, make_audit("workspace", "ok", "删除路径", action=action, path=rel))


def _delete_paths_batch(user_id: str, args: dict[str, object], paths: list[str]) -> WorkspaceActionResult:
    """按 paths 顺序批量删除；路径已解析为相对工作区根的字符串列表。"""
    action = "delete_path"
    recursive = bool(args.get("recursive", False))
    seen: set[str] = set()
    uniq: list[str] = []
    for p in paths:
        p = p.strip().lstrip("/")
        if not p or p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    if not uniq:
        return _err("WORKSPACE_INVALID_ARGS", "paths 为空或仅含无效项", action=action)
    _workspace_debug(
        f"[research_agent][workspace] delete_path 批量开始 user_id={user_id!r} count={len(uniq)} "
        f"recursive={recursive} paths={uniq!r}"
    )
    deleted: list[str] = []
    skipped_missing: list[str] = []
    for rel in uniq:
        one = _delete_path_one_rel(user_id, rel, recursive)
        if one.ok:
            dr = one.output.get("deleted")
            deleted.append(str(dr) if dr is not None else rel)
            continue
        if one.error_code == "WORKSPACE_NOT_FOUND":
            skipped_missing.append(rel)
            _workspace_debug(
                f"[research_agent][workspace] delete_path 批量跳过(不存在) rel={rel!r}"
            )
            continue
        _workspace_debug(
            f"[research_agent][workspace] delete_path 批量中止 rel={rel!r} "
            f"error_code={one.error_code!r} error_message={one.error_message!r}"
        )
        return one
    _workspace_debug(
        f"[research_agent][workspace] delete_path 批量完成 user_id={user_id!r} deleted_count={len(deleted)} "
        f"skipped_missing={skipped_missing!r}"
    )
    return WorkspaceActionResult(
        True,
        {"deleted": deleted, "count": len(deleted), "skipped_missing": skipped_missing},
        make_audit(
            "workspace",
            "ok",
            "批量删除路径",
            action=action,
            count=len(deleted),
            skipped=len(skipped_missing),
        ),
    )


def _delete_path(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    paths_arg = args.get("paths")
    if isinstance(paths_arg, list):
        seq = [str(p).strip() for p in paths_arg if isinstance(p, (str, int, float)) and str(p).strip()]
        if seq:
            return _delete_paths_batch(user_id, args, seq)
        return _err(
            "WORKSPACE_INVALID_ARGS",
            "delete_path 的 paths 为空：若由上一步 find_files 自动注入，说明当前 glob 下没有可删除的文件（仅包含 type=file 的项）。",
            action="delete_path",
        )
    raw_path = str(args.get("path") or "")
    recursive_arg = bool(args.get("recursive", False))
    return _delete_path_one_rel(user_id, raw_path, recursive_arg)


def _clear_dir(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    清空目录：删除目录下的所有子项，但保留目录本身。

    与 delete_path 的区别：
    - delete_path 把目标（含其本身）整个删除，且禁止作用于工作区根目录；
    - clear_dir 只清子项，目录本身保留，因此**允许**作用于工作区根目录
      （这是用户『清空根目录』的合法语义）。
    """
    action = "clear_dir"
    target, error = _resolve(user_id, args.get("path") or "", action=action)
    if error:
        return error
    assert target is not None
    root = get_workspace_root(user_id)
    if not target.exists():
        return _err("WORKSPACE_NOT_FOUND", "目录不存在", action=action, path=args.get("path"))
    if not target.is_dir():
        return _err("WORKSPACE_NOT_DIRECTORY", "目标不是目录", action=action, path=args.get("path"))
    deleted_count = 0
    deleted_names: list[str] = []
    for child in sorted(target.iterdir(), key=lambda p: p.name):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        deleted_count += 1
        deleted_names.append(child.name)
    rel = _rel(target, root) or "."
    return WorkspaceActionResult(
        True,
        {"path": rel, "deleted_count": deleted_count, "deleted": deleted_names},
        make_audit(
            "workspace",
            "ok",
            "清空目录" if rel != "." else "清空工作区根目录",
            action=action,
            path=rel,
            count=deleted_count,
        ),
    )


def _copy_path(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    return _copy_or_move(user_id, args, move=False)


def _move_path(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    return _copy_or_move(user_id, args, move=True)


def _copy_or_move(user_id: str, args: dict[str, object], *, move: bool) -> WorkspaceActionResult:
    action = "move_path" if move else "copy_path"
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

    overwrite = bool(args.get("overwrite", False))
    if dst.exists() and not overwrite:
        rel_target = _rel(dst, root)
        confirm_args = {**args, "dst": rel_target}
        return _conflict_error(action, confirm_args, user_id, target_rel=rel_target)

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
    filename = _safe_child_name(args.get("filename") or Path(parsed.path).name or "download.bin")
    target_dir, error = _resolve(user_id, args.get("path") or "", action=action)
    if error:
        return error
    assert target_dir is not None
    if target_dir.exists() and not target_dir.is_dir():
        return _err("WORKSPACE_NOT_DIRECTORY", "下载目标不是目录", action=action, path=args.get("path"))
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / filename
    if dest.exists() and not bool(args.get("overwrite", False)):
        stem, suffix = dest.stem, dest.suffix
        counter = 1
        while dest.exists():
            dest = target_dir / f"{stem}({counter}){suffix}"
            counter += 1
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


def _find_files(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "find_files"
    rel_start = str(args.get("path") or "")
    pattern = str(args.get("glob") or "*").strip() or "*"
    max_m = int(args.get("max_matches") or _max_matches())
    _workspace_debug(
        f"[research_agent][workspace] find_files 开始 user_id={user_id!r} args.path={rel_start!r} "
        f"args.glob={pattern!r} args.max_matches={max_m}"
    )
    start, error = _resolve(user_id, args.get("path") or "", action=action)
    if error:
        _workspace_debug(
            f"[research_agent][workspace] find_files 失败(解析) user_id={user_id!r} path={rel_start!r} "
            f"error_code={error.error_code!r} error_message={error.error_message!r}"
        )
        return error
    assert start is not None
    root = get_workspace_root(user_id)
    _workspace_debug(
        f"[research_agent][workspace] find_files 已解析 user_id={user_id!r} workspace_root={root!s} "
        f"search_start_abs={start!s}"
    )
    if not start.exists() or not start.is_dir():
        _workspace_debug(
            f"[research_agent][workspace] find_files 失败(起点不是目录) user_id={user_id!r} path={rel_start!r} "
            f"start_abs={start!s} exists={start.exists()}"
        )
        return _err("WORKSPACE_NOT_DIRECTORY", "搜索起点不是目录", action=action, path=args.get("path"))
    matches = _walk_files(root, start, pattern, max_m)
    items = [workspace_file_info(path, root) for path in matches]
    preview = [
        {"rel_path": it.get("rel_path"), "type": it.get("type"), "name": it.get("name")}
        for it in items[:40]
        if isinstance(it, dict)
    ]
    _workspace_debug(
        f"[research_agent][workspace] find_files 完成 user_id={user_id!r} count={len(items)} "
        f"preview_first_40={preview!r}"
    )
    return WorkspaceActionResult(
        True,
        {
            "items": items,
            "count": len(items),
            "search_glob": pattern,
            "search_path": rel_start,
        },
        make_audit("workspace", "ok", "查找文件", action=action, glob=pattern, count=len(items)),
    )


def _replace_text(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "replace_text"
    old = str(args.get("old") or "")
    new = str(args.get("new") or "")
    if not old:
        return _err("WORKSPACE_INVALID_ARGS", "old 不能为空", action=action)
    dry_run = bool(args.get("dry_run", True))
    root = get_workspace_root(user_id)
    files_arg = args.get("files")
    files: list[Path] = []
    if isinstance(files_arg, list):
        for item in files_arg:
            target, error = _resolve(user_id, item, action=action)
            if error:
                return error
            assert target is not None
            files.append(target)
    else:
        start, error = _resolve(user_id, args.get("path") or "", action=action)
        if error:
            return error
        assert start is not None
        files = _walk_files(root, start, str(args.get("glob") or "*").strip() or "*", int(args.get("max_matches") or _max_matches()))
    changed: list[dict[str, object]] = []
    for path in files:
        if not path.exists() or not path.is_file() or path.stat().st_size > _max_text_bytes():
            continue
        try:
            text = path.read_text(encoding=str(args.get("encoding") or "utf-8"))
        except UnicodeDecodeError:
            continue
        count = text.count(old)
        if not count:
            continue
        rel = _rel(path, root)
        changed.append({"path": rel, "replacements": count})
        if not dry_run:
            path.write_text(text.replace(old, new), encoding=str(args.get("encoding") or "utf-8"))
    return WorkspaceActionResult(
        True,
        {"dry_run": dry_run, "changed": changed, "changed_count": len(changed)},
        make_audit("workspace", "ok", "批量替换文本" if not dry_run else "预览批量替换", action=action, dry_run=dry_run, changed_count=len(changed)),
    )


def _archive_zip(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    action = "archive_zip"
    src, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    output, error = _resolve(user_id, args.get("output") or "archive.zip", action=action)
    if error:
        return error
    assert src is not None and output is not None
    if not src.exists():
        return _err("WORKSPACE_NOT_FOUND", "待压缩路径不存在", action=action, path=args.get("path"))
    root = get_workspace_root(user_id)
    if output.exists() and not bool(args.get("overwrite", False)):
        rel_target = _rel(output, root)
        return _conflict_error(action, args, user_id, target_rel=rel_target)
    _ensure_parent(output)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
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


def _extract_zip(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
    """
    解压 zip 压缩包到指定目录（默认原地解压：dst = src 所在目录）。

    防护：
    - zip slip：每个 member 解析后必须落在工作区根目录之内；
    - 对绝对路径成员、含 `..` 段的成员一律拒收，不允许"半解压"；
    - 单个 member 体积限制：复用 `RA_WORKSPACE_MAX_TEXT_BYTES * 32` 作为粗略上界，
      防止压缩包炸弹（zip bomb）。
    """
    action = "extract_zip"
    src, error = _resolve(user_id, args.get("path"), action=action)
    if error:
        return error
    assert src is not None
    if not src.exists() or not src.is_file():
        return _err("WORKSPACE_NOT_FOUND", "压缩包不存在", action=action, path=args.get("path"))
    if not zipfile.is_zipfile(src):
        return _err("WORKSPACE_INVALID_ARCHIVE", "目标文件不是有效的 zip 压缩包", action=action, path=args.get("path"))

    # 默认原地解压：dst = src.parent。LLM 可以显式指定 args.output 或 args.dest。
    dest_arg = args.get("output") or args.get("dest")
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

    overwrite = bool(args.get("overwrite", False))
    member_size_cap = _max_text_bytes() * 32
    extracted: list[str] = []
    skipped_existing: list[str] = []
    try:
        with zipfile.ZipFile(src, "r") as zf:
            members = zf.infolist()
            # 先做一遍 zip slip / 异常路径 / 体积预检，全过才开始解压
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
                if target.exists() and not overwrite:
                    skipped_existing.append(name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as zi, open(target, "wb") as out:
                    shutil.copyfileobj(zi, out)
                extracted.append(name)
    except zipfile.BadZipFile as exc:
        return _err("WORKSPACE_INVALID_ARCHIVE", f"压缩包损坏: {exc}", action=action, path=args.get("path"))

    if skipped_existing and not overwrite:
        # 有已存在文件且未允许覆盖：剩余的已经写完，把跳过的列出来作 conflict 提示，
        # 让用户决定是否带 overwrite=true 再跑一次。
        sample = skipped_existing[:5]
        rel_dest = _rel(dest, root) or "."
        target_rel = f"{rel_dest}（含 {len(skipped_existing)} 个已存在文件，例：{', '.join(sample)}）"
        return _conflict_error(action, args, user_id, target_rel=target_rel)

    rel_dest = _rel(dest, root) or "."
    return WorkspaceActionResult(
        True,
        {"path": rel_dest, "extracted_count": len(extracted), "skipped_existing": skipped_existing},
        make_audit(
            "workspace",
            "ok",
            "解压 zip 压缩包",
            action=action,
            path=rel_dest,
            count=len(extracted),
        ),
    )


def _extract_pdf_text(user_id: str, args: dict[str, object]) -> WorkspaceActionResult:
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
    max_chars = int(args.get("max_chars") or 12000)
    try:
        with fitz.open(str(target)) as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        return _err("WORKSPACE_PDF_EXTRACT_FAILED", str(exc) or "PDF 文本提取失败", action=action, path=args.get("path"))
    text = truncate_text(text, max_chars)
    output_path = str(args.get("output") or "").strip()
    output: dict[str, object] = {"path": _rel(target, get_workspace_root(user_id)), "text": text}
    if output_path:
        out, error = _resolve(user_id, output_path, action=action)
        if error:
            return error
        assert out is not None
        _ensure_parent(out)
        out.write_text(text, encoding="utf-8")
        output["output"] = _rel(out, get_workspace_root(user_id))
    return WorkspaceActionResult(True, output, make_audit("workspace", "ok", "提取 PDF 文本", action=action, path=output["path"], chars=len(text)))
