"""
用户工作区工具模块

每个用户在服务器上拥有一个独立的工作目录（home 目录），路径为：
    <BASE_DIR>/resource/workspaces/<user_id>/

所有对工作区文件的操作都必须通过本模块的 safe_resolve() 进行路径安全校验，
以防止路径穿越攻击（path traversal）。

公开接口：
    get_workspace_root(user_id)  -> Path   获取（并自动创建）用户工作区根目录
    safe_resolve(user_id, rel)   -> Path   将相对路径解析为绝对路径，越界返回 None
    workspace_file_info(path)    -> dict   将 Path 对象转换为文件元信息字典
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from django.conf import settings


def get_workspace_root(user_id: str) -> Path:
    """返回用户工作区根目录（不存在则自动创建）。"""
    base = Path(getattr(settings, "USER_WORKSPACE_PATH", Path(settings.BASE_DIR) / "resource" / "workspaces"))
    root = base / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_resolve(user_id: str, rel_path: str) -> Path | None:
    """
    将相对路径 rel_path 解析为用户工作区内的绝对路径。

    若解析结果逃逸出工作区根目录（路径穿越），返回 None。
    rel_path 为空字符串时返回工作区根目录本身。
    """
    root = get_workspace_root(user_id)
    # 移除开头的 / 防止被 Path / 操作当作绝对路径
    clean_rel = rel_path.lstrip("/").lstrip("\\") if rel_path else ""
    if not clean_rel:
        return root
    try:
        target = (root / clean_rel).resolve()
    except (OSError, ValueError):
        return None
    # 严格包含检查：target 必须在 root 内部（root 本身也允许）
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def workspace_file_info(path: Path, root: Path) -> dict:
    """
    将 Path 对象转换为供 API 返回的文件/目录元信息字典。

    字段：
        name        - 文件/目录名
        type        - "file" | "directory"
        size        - 字节数（目录为 0）
        rel_path    - 相对于工作区根目录的路径（使用 "/" 分隔）
    """
    stat = path.stat()
    is_dir = path.is_dir()
    try:
        rel = path.relative_to(root)
        rel_path_str = rel.as_posix()
    except ValueError:
        rel_path_str = path.name

    modified_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "name": path.name,
        "type": "directory" if is_dir else "file",
        "size": 0 if is_dir else stat.st_size,
        "modified_at": modified_at,
        "rel_path": rel_path_str,
    }


def list_workspace_dir(user_id: str, rel_path: str) -> tuple[list[dict], str | None]:
    """
    列出指定目录的内容。

    返回 (items, error_message)。
    error_message 为 None 表示成功；否则包含错误说明。
    items 中目录排在前面，文件按名称排序。
    """
    target = safe_resolve(user_id, rel_path)
    if target is None:
        return [], "路径越界"
    if not target.exists():
        return [], "目录不存在"
    if not target.is_dir():
        return [], "指定路径不是目录"

    root = get_workspace_root(user_id)
    entries: list[dict] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        for child in children:
            entries.append(workspace_file_info(child, root))

    except PermissionError:
        return [], "无权限读取目录"
    return entries, None


def sanitize_filename(raw: str) -> str:
    """
    清理上传/创建文件名，去除路径分隔符及危险字符，最长 200 字节。
    """
    name = os.path.basename((raw or "").strip())
    # 过滤 Windows 保留字符及控制字符
    import re
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    return name[:200] if name else "unnamed"
