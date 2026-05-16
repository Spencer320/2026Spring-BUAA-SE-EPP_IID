"""
用户工作区 API

每个已登录用户拥有一个服务器端"home 目录"，用于存放科研助手下载的文件、
报告及用户自行上传的文件。前端通过本模块的接口对工作区进行管理。

路由（注册于 backend/urls.py）：
    GET    /api/workspace/files              列出工作区根目录内容
    GET    /api/workspace/files?path=<dir>  列出子目录内容
    POST   /api/workspace/files             上传文件（multipart/form-data）
    GET    /api/workspace/files/<rel_path>  下载单个文件（流式）
    DELETE /api/workspace/files/<rel_path>  删除文件或目录（含非空目录）
    POST   /api/workspace/mkdir             创建子目录

所有接口均需携带合法的用户 JWT（Authorization 头），
路径越界（path traversal）会被强制拦截。
"""

from __future__ import annotations

import json
import mimetypes
import shutil

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from business.utils.authenticate import authenticate_user
from business.utils.user_workspace import (
    get_workspace_root,
    list_workspace_dir,
    safe_resolve,
    sanitize_filename,
)


# ── 响应辅助 ─────────────────────────────────────────────────────────

def _ok(data: dict, status: int = 200) -> JsonResponse:
    return JsonResponse({"ok": True, "data": data}, status=status)


def _err(message: str, status: int = 400, code: str = "BAD_REQUEST") -> JsonResponse:
    return JsonResponse({"ok": False, "error": {"code": code, "message": message}}, status=status)


# ── /api/workspace/files  （GET=列出，POST=上传） ─────────────────────

@authenticate_user
@require_http_methods(["GET", "POST"])
def workspace_files_collection(request, user):
    """
    GET  /api/workspace/files[?path=<subdir>]   列出目录内容
    POST /api/workspace/files                   上传文件
    """
    if request.method == "GET":
        return _list_files(request, user)
    return _upload_file(request, user)


def _list_files(request, user):
    """
    列出工作区目录内容。

    查询参数：
        path  （可选）相对子目录路径，默认为根目录（""）

    返回：
        {
            "path": "subdir",
            "items": [
                {"name": "report.md", "type": "file", "size": 2048,
                 "modified_at": "2026-05-03T22:00:00", "rel_path": "report.md"},
                {"name": "papers",    "type": "directory", "size": 0, ...},
                ...
            ]
        }
    """
    rel_path = (request.GET.get("path") or "").strip().lstrip("/")
    items, error = list_workspace_dir(str(user.user_id), rel_path)
    if error:
        if "越界" in error:
            return _err(error, 403, "FORBIDDEN")
        if "不存在" in error:
            return _err(error, 404, "NOT_FOUND")
        return _err(error)
    return _ok({"path": rel_path, "items": items})


def _upload_file(request, user):
    """
    上传文件到工作区。

    表单字段（multipart/form-data）：
        file  （必须，可多个）要上传的文件
        path  （可选）目标子目录路径，默认为根目录

    单文件大小上限由 USER_WORKSPACE_MAX_UPLOAD_BYTES 控制（默认 50 MB）。

    返回：
        {"uploaded": [{"name": "...", "size": 1234, "rel_path": "..."}, ...]}
    """
    if not request.FILES:
        return _err("未检测到上传文件（Content-Type 需为 multipart/form-data，并包含 file 字段）")

    rel_dir = (request.POST.get("path") or "").strip().lstrip("/")
    target_dir = safe_resolve(str(user.user_id), rel_dir)
    if target_dir is None:
        return _err("目标目录路径越界", 403, "FORBIDDEN")
    if target_dir.exists() and not target_dir.is_dir():
        return _err("目标路径不是目录", 400, "NOT_A_DIRECTORY")
    target_dir.mkdir(parents=True, exist_ok=True)

    max_bytes: int = int(getattr(settings, "USER_WORKSPACE_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
    root = get_workspace_root(str(user.user_id))
    uploaded = []

    files = request.FILES.getlist("file")
    if not files:
        return _err("file 字段为空")

    for f in files:
        if f.size > max_bytes:
            return _err(
                f"文件 {f.name!r} 超过大小限制（{max_bytes // 1024 // 1024} MB）",
                413,
                "FILE_TOO_LARGE",
            )
        safe_name = sanitize_filename(f.name)
        dest = target_dir / safe_name

        # 同名文件已存在时追加序号，避免覆盖
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = target_dir / f"{stem}({counter}){suffix}"
                counter += 1

        with open(dest, "wb") as fp:
            for chunk in f.chunks():
                fp.write(chunk)

        try:
            rel = dest.relative_to(root).as_posix()
        except ValueError:
            rel = dest.name
        uploaded.append({"name": dest.name, "size": dest.stat().st_size, "rel_path": rel})

    return _ok({"uploaded": uploaded}, status=201)


# ── /api/workspace/files/<rel_path>  （GET=下载，DELETE=删除） ────────

@authenticate_user
@require_http_methods(["GET", "DELETE"])
def workspace_file_detail(request, user, rel_path: str):
    """
    GET    /api/workspace/files/<rel_path>  下载文件
    DELETE /api/workspace/files/<rel_path>  删除文件或目录（含非空目录）
    """
    if request.method == "GET":
        return _download_file(request, user, rel_path)
    return _delete_file(request, user, rel_path)


def _download_file(request, user, rel_path: str):
    """
    以附件形式流式下载工作区内的文件到用户本机（浏览器触发 Save As）。
    路径越界、不存在或目标是目录时返回 JSON 错误。
    """
    target = safe_resolve(str(user.user_id), rel_path)
    if target is None:
        return _err("路径越界或非法", 403, "FORBIDDEN")
    if not target.exists():
        return _err("文件不存在", 404, "NOT_FOUND")
    if target.is_dir():
        return _err("目标是目录，如需列出内容请使用 GET /api/workspace/files?path=<dir>", 400, "IS_DIRECTORY")

    mime_type, _ = mimetypes.guess_type(str(target))
    mime_type = mime_type or "application/octet-stream"
    return FileResponse(
        open(target, "rb"),
        content_type=mime_type,
        as_attachment=True,
        filename=target.name,
    )


def _delete_file(request, user, rel_path: str):
    """
    删除工作区内的文件或目录（目录非空时递归删除）。
    禁止删除工作区根目录本身（rel_path 为空或解析为根目录）。
    """
    if not rel_path or rel_path.strip("/") == "":
        return _err("禁止删除工作区根目录", 403, "FORBIDDEN")

    uid = str(user.user_id)
    root = get_workspace_root(uid)
    target = safe_resolve(uid, rel_path)
    if target is None:
        return _err("路径越界或非法", 403, "FORBIDDEN")
    if target.resolve() == root.resolve():
        return _err("禁止删除工作区根目录", 403, "FORBIDDEN")
    if not target.exists():
        return _err("文件或目录不存在", 404, "NOT_FOUND")

    if target.is_dir():
        try:
            shutil.rmtree(target)
        except OSError as exc:
            return _err(f"删除目录失败：{exc}", 500, "DELETE_FAILED")
    else:
        try:
            target.unlink()
        except OSError as exc:
            return _err(f"删除失败：{exc}", 500, "DELETE_FAILED")

    return _ok({"deleted": rel_path})


# ── /api/workspace/mkdir  （POST=创建目录） ───────────────────────────

@authenticate_user
@require_http_methods(["POST"])
def make_directory(request, user):
    """
    POST /api/workspace/mkdir
    Content-Type: application/json

    请求体：
        {"path": "papers/2026"}   （相对于工作区根目录，支持多级）

    在工作区内创建多级子目录（类似 mkdir -p）。
    目录已存在时不报错。
    """
    try:
        body = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        return _err("请求体不是合法 JSON")

    rel_path = str(body.get("path") or "").strip().lstrip("/")
    if not rel_path:
        return _err("path 不能为空")

    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    if not parts:
        return _err("path 不合法")
    for part in parts:
        clean = sanitize_filename(part)
        if not clean or clean != part:
            return _err(f"目录名含非法字符：{part!r}")

    target = safe_resolve(str(user.user_id), "/".join(parts))
    if target is None:
        return _err("路径越界", 403, "FORBIDDEN")

    if target.exists():
        if not target.is_dir():
            return _err("目标路径已存在且不是目录", 409, "CONFLICT")
        return _ok({"path": rel_path, "created": False, "message": "目录已存在"})

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _err(f"创建目录失败：{exc}", 500, "MKDIR_FAILED")

    return _ok({"path": rel_path, "created": True}, status=201)
