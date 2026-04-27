from __future__ import annotations

from dataclasses import dataclass
import os
import re
from urllib.parse import urlparse

import httpx
from django.conf import settings

from .base import ToolAuditEvent, make_audit
from .web_fetch_executor import is_host_allowed


@dataclass(frozen=True)
class LocalFileActionResult:
    ok: bool
    output: dict[str, object]
    audit: ToolAuditEvent
    requires_confirmation: bool = False
    confirmation_payload: dict[str, object] | None = None
    error_code: str = ""
    error_message: str = ""


def _sanitize_filename(raw_name: str) -> str:
    name = (raw_name or "").strip()
    if not name:
        return "download.bin"
    name = os.path.basename(name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    if not name:
        return "download.bin"
    return name[:120]


def _allowed_actions() -> set[str]:
    configured = getattr(settings, "RA_LOCAL_FILE_ALLOWED_ACTIONS", None)
    if isinstance(configured, (list, tuple, set)):
        return {str(item).strip() for item in configured if str(item).strip()}
    return {"download_file_to_dir"}


def _allowed_target_dirs() -> dict[str, str]:
    configured = getattr(settings, "RA_LOCAL_FILE_ALLOWED_TARGET_DIRS", None)
    if isinstance(configured, dict) and configured:
        result: dict[str, str] = {}
        for key, val in configured.items():
            if not isinstance(key, str) or not isinstance(val, str):
                continue
            k = key.strip()
            v = val.strip()
            if not k or not v:
                continue
            result[k] = os.path.abspath(v)
        if result:
            return result
    fallback = os.path.abspath(getattr(settings, "BASE_DIR", os.getcwd()))
    return {"workspace_downloads": fallback}


def execute_local_file_action(
    *,
    action: str,
    args: dict[str, object] | None,
    risk_confirmation_strategy: str,
) -> LocalFileActionResult:
    normalized_action = (action or "").strip()
    runtime_args = args or {}
    allowed = _allowed_actions()
    if normalized_action not in allowed:
        payload = {
            "type": "tool_confirmation",
            "tool": "local_file",
            "action": normalized_action,
            "args": runtime_args,
            "risk_level": "high",
            "message": f"本地文件动作 {normalized_action or 'unknown'} 需要人工确认",
        }
        return LocalFileActionResult(
            ok=False,
            output={},
            requires_confirmation=True,
            confirmation_payload=payload,
            error_code="LOCAL_FILE_CONFIRM_REQUIRED",
            error_message=payload["message"],
            audit=make_audit(
                "local_file",
                "pending_action",
                payload["message"],
                action=normalized_action,
                args=runtime_args,
            ),
        )
    if normalized_action != "download_file_to_dir":
        return LocalFileActionResult(
            ok=False,
            output={},
            error_code="LOCAL_FILE_ACTION_UNSUPPORTED",
            error_message=f"不支持的动作: {normalized_action}",
            audit=make_audit("local_file", "error", "不支持的动作", action=normalized_action),
        )
    return _download_file_to_dir(runtime_args, risk_confirmation_strategy=risk_confirmation_strategy)


def _download_file_to_dir(
    args: dict[str, object],
    *,
    risk_confirmation_strategy: str,
) -> LocalFileActionResult:
    raw_url = str(args.get("url", "")).strip()
    target_key = str(args.get("target_dir_key", "")).strip()
    filename = _sanitize_filename(str(args.get("filename", "")).strip())

    if not raw_url:
        return LocalFileActionResult(
            ok=False,
            output={},
            error_code="LOCAL_FILE_INVALID_ARGS",
            error_message="url 不能为空",
            audit=make_audit("local_file", "error", "参数缺失：url"),
        )
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        return LocalFileActionResult(
            ok=False,
            output={},
            error_code="LOCAL_FILE_INVALID_URL",
            error_message="仅允许 http/https",
            audit=make_audit("local_file", "error", "URL 协议非法", url=raw_url),
        )
    if not parsed.hostname or not is_host_allowed(parsed.hostname, setting_name="RA_LOCAL_FILE_ALLOWED_HOSTS"):
        if not parsed.hostname or not is_host_allowed(parsed.hostname):
            return LocalFileActionResult(
                ok=False,
                output={},
                error_code="LOCAL_FILE_HOST_DENIED",
                error_message=f"主机不在白名单: {parsed.hostname or 'unknown'}",
                audit=make_audit("local_file", "error", "主机不在白名单", url=raw_url),
            )

    dirs = _allowed_target_dirs()
    if not target_key:
        target_key = next(iter(dirs.keys()))
    if target_key not in dirs:
        return LocalFileActionResult(
            ok=False,
            output={},
            error_code="LOCAL_FILE_DIR_DENIED",
            error_message=f"目标目录不在白名单: {target_key}",
            audit=make_audit("local_file", "error", "目标目录不在白名单", target_dir_key=target_key),
        )

    if (risk_confirmation_strategy or "on_high_risk").strip() == "always":
        payload = {
            "type": "tool_confirmation",
            "tool": "local_file",
            "action": "download_file_to_dir",
            "args": args,
            "risk_level": "medium",
            "message": "下载文件动作需要人工确认",
        }
        return LocalFileActionResult(
            ok=False,
            output={},
            requires_confirmation=True,
            confirmation_payload=payload,
            error_code="LOCAL_FILE_CONFIRM_REQUIRED",
            error_message=payload["message"],
            audit=make_audit("local_file", "pending_action", payload["message"]),
        )

    target_root = dirs[target_key]
    os.makedirs(target_root, exist_ok=True)
    path = os.path.abspath(os.path.join(target_root, filename))
    if not path.startswith(target_root + os.sep) and path != target_root:
        return LocalFileActionResult(
            ok=False,
            output={},
            error_code="LOCAL_FILE_PATH_DENIED",
            error_message="非法文件路径",
            audit=make_audit("local_file", "error", "非法文件路径", path=path),
        )

    timeout = float(getattr(settings, "RA_LOCAL_FILE_DOWNLOAD_TIMEOUT", 30.0))
    max_bytes = int(getattr(settings, "RA_LOCAL_FILE_MAX_BYTES", 20 * 1024 * 1024))
    written = 0
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            with client.stream("GET", raw_url) as resp:
                if resp.status_code >= 400:
                    return LocalFileActionResult(
                        ok=False,
                        output={},
                        error_code="LOCAL_FILE_DOWNLOAD_HTTP_ERROR",
                        error_message=f"HTTP {resp.status_code}",
                        audit=make_audit(
                            "local_file",
                            "error",
                            "下载失败",
                            response_status=resp.status_code,
                            url=raw_url,
                        ),
                    )
                with open(path, "wb") as f:
                    for chunk in resp.iter_bytes():
                        written += len(chunk)
                        if written > max_bytes:
                            f.close()
                            os.remove(path)
                            return LocalFileActionResult(
                                ok=False,
                                output={},
                                error_code="LOCAL_FILE_TOO_LARGE",
                                error_message=f"文件超过上限 {max_bytes} 字节",
                                audit=make_audit("local_file", "error", "文件超过上限", url=raw_url, max_bytes=max_bytes),
                            )
                        f.write(chunk)
    except httpx.TimeoutException:
        return LocalFileActionResult(
            ok=False,
            output={},
            error_code="LOCAL_FILE_DOWNLOAD_TIMEOUT",
            error_message="下载超时",
            audit=make_audit("local_file", "error", "下载超时", url=raw_url),
        )
    except (httpx.RequestError, OSError) as exc:
        return LocalFileActionResult(
            ok=False,
            output={},
            error_code="LOCAL_FILE_DOWNLOAD_ERROR",
            error_message=str(exc) or "下载失败",
            audit=make_audit("local_file", "error", "下载失败", url=raw_url),
        )

    output = {"saved_path": path, "file_size": written, "target_dir_key": target_key, "filename": filename}
    return LocalFileActionResult(
        ok=True,
        output=output,
        audit=make_audit("local_file", "ok", "下载成功", **output),
    )

