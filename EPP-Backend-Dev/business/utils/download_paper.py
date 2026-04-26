import os
from urllib.parse import urlparse

import requests
import urllib3
from minio import Minio
import urllib3

from backend.settings import (
    PAPERS_PATH,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_ENDPOINT,
    RA_HTTP_TIMEOUT,
)

if not os.path.exists(PAPERS_PATH):
    os.makedirs(PAPERS_PATH)

_MINIO_CLIENTS: list[Minio] | None = None


def _minio_enabled() -> bool:
    """
    MinIO 在该项目里经常处于“未实际部署/未配置”状态。
    未配置时应直接跳过，避免在 get_object 上长时间空等。
    """
    if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
        return False
    if "xxxx" in str(MINIO_ACCESS_KEY).strip().lower():
        return False
    # 一些部署会把它们填成 "None"/"null"/"changeme" 之类的占位符
    bad = {"none", "null", "changeme", "placeholder", "dummy"}
    if str(MINIO_ACCESS_KEY).strip().lower() in bad:
        return False
    if str(MINIO_SECRET_KEY).strip().lower() in bad:
        return False
    if not MINIO_ENDPOINT or not str(MINIO_ENDPOINT).strip():
        return False
    return True


def _get_minio_clients() -> list[Minio]:
    global _MINIO_CLIENTS
    if _MINIO_CLIENTS is not None:
        return _MINIO_CLIENTS

    if not _minio_enabled():
        _MINIO_CLIENTS = []
        return _MINIO_CLIENTS

    # 允许配置多个 endpoint，用逗号分隔；兼容老的硬编码候选
    endpoints = [e.strip() for e in str(MINIO_ENDPOINT).split(",") if e.strip()]
    if not endpoints:
        endpoints = ["120.46.1.4:9000", "120.46.1.4:9010"]

    # 关键：为 MinIO 的底层 HTTP 客户端设置短超时，避免无配置时空等
    timeout_s = float(RA_HTTP_TIMEOUT) if RA_HTTP_TIMEOUT else 15.0
    http_client = urllib3.PoolManager(timeout=urllib3.Timeout(connect=2.0, read=timeout_s))

    _MINIO_CLIENTS = [
        Minio(
            endpoint=ep,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False,
            http_client=http_client,
        )
        for ep in endpoints
    ]
    return _MINIO_CLIENTS
minio_endpoints = ["120.46.1.4:9000", "120.46.1.4:9010"]
MINIO_CONNECT_TIMEOUT_SECONDS = 2
MINIO_READ_TIMEOUT_SECONDS = 5
ARXIV_CONNECT_TIMEOUT_SECONDS = 3
ARXIV_READ_TIMEOUT_SECONDS = 10


def _build_minio_http_client():
    return urllib3.PoolManager(
        timeout=urllib3.Timeout(
            connect=MINIO_CONNECT_TIMEOUT_SECONDS,
            read=MINIO_READ_TIMEOUT_SECONDS,
        ),
        retries=False,
    )


minio_clients = [
    Minio(
        endpoint=ep,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
        http_client=_build_minio_http_client(),
    )
    for ep in minio_endpoints
]


def _normalize_pdf_url(url: str) -> str:
    """
    Normalize arXiv URL into downloadable PDF URL.
    """
    if not url:
        return url
    normalized = url.strip().replace("http://", "https://")
    if "arxiv.org/abs/" in normalized:
        normalized = normalized.replace("arxiv.org/abs/", "arxiv.org/pdf/")
    if "arxiv.org/pdf/" in normalized and not normalized.endswith(".pdf"):
        normalized += ".pdf"
    return normalized


def _build_download_candidates(url: str) -> list[str]:
    normalized = _normalize_pdf_url(url)
    if not normalized:
        return []
    candidates = [normalized]

    parsed = urlparse(normalized)
    # export.arxiv.org is often more stable in server-side downloads.
    if parsed.netloc == "arxiv.org":
        candidates.append(parsed._replace(netloc="export.arxiv.org").geturl())

    # Keep order and remove duplicates.
    return list(dict.fromkeys(candidates))


def cache_from_minio(url: str) -> bytes | None:
    clients = _get_minio_clients()
    if not clients:
        return None
    for client in clients:
        file = _cache_from_single_minio(client, url)
        if file:
            print(f"[minio]: file {url} downloaded successfully")
            return file
        print(f"[minio]: file {url} unavailable, trying next candidate...")

    print(f"[minio]: failed to download {url}")
    return None


def _cache_from_single_minio(minio_client, url: str) -> bytes | None:
    file_name = _normalize_pdf_url(url).split("/")[-1]
    if not file_name.endswith(".pdf"):
        file_name = file_name + ".pdf"
    response = None
    try:
        print("[minio]: path", f"pdf/{file_name}")
        response = minio_client.get_object(
            bucket_name="papers",
            object_name=f"pdf/{file_name}",
        )
        file = response.read()
    except Exception as e:
        # 不让 MinIO 失败拖慢主流程（尤其是未配置/网络不可达时）
        print(f"[minio]: error downloading {url}: {e}")
        return response.read()
    except Exception as e:
        print(f"[minio]: failed to get {file_name}: {repr(e)}")
        return None
    finally:
        if response:
            response.close()
            response.release_conn()


def cache_paper(url, *, from_minio=True, from_arxiv=True) -> bytes | None:
    file = None
    if from_minio and _minio_enabled():
        file = cache_from_minio(url)

    if from_arxiv and file is None:
        response = requests.get(url, timeout=float(RA_HTTP_TIMEOUT) if RA_HTTP_TIMEOUT else 15.0)
        if response.status_code == 200:
            file = response.content
        for candidate in _build_download_candidates(url):
            try:
                print(f"[arxiv]: trying {candidate}")
                response = requests.get(
                    candidate,
                    timeout=(
                        ARXIV_CONNECT_TIMEOUT_SECONDS,
                        ARXIV_READ_TIMEOUT_SECONDS,
                    ),
                )
            except requests.RequestException as e:
                print(f"[arxiv]: request failed: {repr(e)}")
                continue
            if response.status_code == 200:
                return response.content
            print(f"[arxiv]: bad status code {response.status_code} for {candidate}")

    return file


def download_paper(url, filename):
    """
    下载文献到服务器
    """
    path = (
        os.path.join(PAPERS_PATH, filename)
        if filename.endswith(".pdf")
        else os.path.join(PAPERS_PATH, filename + ".pdf")
    )
    if os.path.exists(path):
        return path
    resolved_url = _normalize_pdf_url(url)
    print(f"Starting downloading paper: {filename}, via {resolved_url}")
    file = cache_paper(resolved_url)
    if file:
        print(f"Downloaded successfully, saving to {path}")
        if not filename.endswith(".pdf"):
            filepath = os.path.join(PAPERS_PATH, filename + ".pdf")
        else:
            filepath = os.path.join(PAPERS_PATH, filename)
        with open(filepath, "wb") as f:
            f.write(file)
        return filepath
    else:
        print(f"Failed to download paper: {filename}, via {url}")
        return None
