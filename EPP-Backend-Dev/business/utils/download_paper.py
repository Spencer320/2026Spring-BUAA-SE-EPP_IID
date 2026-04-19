import os

import requests
from minio import Minio

from backend.settings import (
    PAPERS_PATH,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
)

if not os.path.exists(PAPERS_PATH):
    os.makedirs(PAPERS_PATH)

minio_endpoints = ["120.46.1.4:9000", "120.46.1.4:9010"]
minio_clients = [
    Minio(
        endpoint=ep,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )
    for ep in minio_endpoints
]


def cache_from_minio(url: str) -> bytes | None:
    for client in minio_clients:
        file = _cache_from_single_minio(client, url)
        if file:
            print(f"[minio]: file {url} downloaded successfully")
            return file
        print(f"[minio]: file {url} not found, trying next candidate...")

    print(f"[minio]: failed to download {url}")
    return None


def _cache_from_single_minio(minio_client, url: str) -> bytes | None:

    file_name = url.split("/")[-1]
    if not file_name.endswith(".pdf"):
        file_name = file_name + ".pdf"
    response = None
    file = None
    try:
        print("[minio]: path", f"pdf/{file_name}")
        response = minio_client.get_object(
            bucket_name="papers",
            object_name=f"pdf/{file_name}",
        )
        file = response.read()
    finally:
        if response:
            response.close()
            response.release_conn()
        return file


def cache_paper(url, *, from_minio=True, from_arxiv=True) -> bytes | None:
    file = None
    if from_minio:
        file = cache_from_minio(url)

    if from_arxiv and file is None:
        response = requests.get(url)
        if response.status_code == 200:
            file = response.content

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
    print(f"Starting downloading paper: {filename}, via {url}")
    file = cache_paper(url)
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
