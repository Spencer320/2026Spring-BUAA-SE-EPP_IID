import json
import os
import os.path
import time

import numpy as np
import faiss
import pickle

import requests
from django.conf import settings
from business.models import Paper
from business.utils.response import ok, fail


def get_all_paper():
    papers = Paper.objects.all()
    for paper in papers:
        keyword = paper.title + "." + paper.abstract
        paper_id = paper.paper_id
        yield keyword, paper_id


def embed(texts):
    """
    调用 Chatchat(OpenAI-compatible) embeddings 接口。
    - 输入：str 或 List[str]
    - 输出：List[List[float]]，与 input 一一对应
    """
    if not isinstance(texts, list):
        texts = [texts]

    timeout_s = 60
    max_retries = 4

    url = f"{settings.REMOTE_MODEL_BASE_PATH}/v1/embeddings"
    headers = {"Content-Type": "application/json"}
    session = requests.Session()

    model_name = settings.CHATCHAT_EMBEDDING_MODEL
    payload = json.dumps({"input": texts, "model": model_name})

    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = session.post(url, headers=headers, data=payload, timeout=timeout_s)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            data_sorted = sorted(data, key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in data_sorted]
        except Exception as e:
            last_err = e
            backoff = min(8.0, (0.5 * (2**attempt)))
            time.sleep(backoff)

    raise RuntimeError(f"Embeddings 请求失败（size={len(texts)}）：{last_err}") from last_err


def _get_effective_vector_dim() -> int:
    """
    优先通过当前 embeddings 模型的真实返回值动态探测向量维度；
    探测失败时回退到 settings.VECTOR_DIM，保证服务可继续运行。
    """
    fallback_dim = int(settings.VECTOR_DIM)
    try:
        probe = embed(["dim probe text"])
        if not probe or not isinstance(probe, list) or not probe[0]:
            raise RuntimeError("embedding 探测返回空结果")
        dim = len(probe[0])
        if dim <= 0:
            raise RuntimeError(f"embedding 探测得到非法维度: {dim}")
        return dim
    except Exception as e:
        print(
            "[warn][FAISS] embedding 维度自动探测失败，"
            f"回退 VECTOR_DIM={fallback_dim}，err={e!r}"
        )
        return fallback_dim


def _resolve_vdb_base_dir() -> str:
    """
    将 settings.LOCAL_VECTOR_DATABASE_PATH 解析为绝对路径。
    - 若配置为相对路径，则以 Django settings.BASE_DIR 为基准
    - 解决“写入/读取因工作目录不同导致找不到文件”的问题
    """
    base_dir = settings.LOCAL_VECTOR_DATABASE_PATH
    if not os.path.isabs(base_dir):
        base_dir = os.path.join(str(settings.BASE_DIR), base_dir)

    base_dir = os.path.normpath(base_dir)

    # faiss 的 Windows 轮子在某些环境下对包含中文/非 ASCII 路径写文件不稳定，
    # 这里做一个“可运行优先”的兜底：若路径含非 ASCII 字符，则落到系统临时目录。

    try:
        base_dir.encode("ascii")
    except UnicodeEncodeError:
        tmp_root = (
            os.environ.get("TEMP")
            or os.environ.get("TMP")
            or os.environ.get("TMPDIR")
            or os.environ.get("LOCALAPPDATA")
            or os.getcwd()
        )
        base_dir = os.path.normpath(os.path.join(tmp_root, "epp_faiss_index"))

    
    return base_dir


def _ensure_local_vdb_dir() -> str:
    base_dir = _resolve_vdb_base_dir()
    os.makedirs(base_dir, exist_ok=True)
    return base_dir


def _faiss_index_path() -> str:
    return os.path.join(_ensure_local_vdb_dir(), settings.LOCAL_FAISS_NAME)


def _faiss_meta_path() -> str:
    return os.path.join(_ensure_local_vdb_dir(), settings.LOCAL_METADATA_NAME)


def _ensure_faiss_ready():
    idx = _faiss_index_path()
    meta = _faiss_meta_path()
    missing = [p for p in [idx, meta] if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            "本地 FAISS 索引未初始化，缺少文件："
            + ", ".join(missing)
            + "。请先调用 POST /api/init/localVDBInit 生成索引。"
        )


def build_local_faiss_index() -> dict:
    """
    全量重建本地 FAISS 索引（paper_index.faiss + paper_metadata.pkl）。
    返回构建信息，便于日志/状态接口展示。
    """
    start = time.time()
    d = _get_effective_vector_dim()

    texts = []
    metadata = []
    for keyword, paper_id in get_all_paper():
        texts.append(keyword)
        metadata.append(paper_id)

    if len(texts) == 0:
        raise RuntimeError("论文库为空，无法初始化本地向量索引")

    embed_texts = embed(texts)
    db_vectors = np.array(embed_texts, dtype=np.float32)
    if db_vectors.ndim != 2 or db_vectors.shape[1] != d:
        raise RuntimeError(
            f"Embedding 维度不匹配：期望 (N, {d})，实际 {tuple(db_vectors.shape)}。请检查 embeddings 服务与 VECTOR_DIM 配置"
        )

    index = faiss.IndexFlatL2(d)
    index.add(db_vectors)

    # 再次确保目录存在（faiss 直接写文件，不会创建父目录）
    base_dir = _ensure_local_vdb_dir()
    if not os.path.isdir(base_dir):
        print(f"basedir={base_dir}, mkdir")
        # 理论上 os.makedirs 已创建；这里做强兜底，避免在 faiss.write_index 处崩溃
        os.makedirs(base_dir, exist_ok=True)
    index_path = os.path.join(base_dir, settings.LOCAL_FAISS_NAME)
    meta_path = os.path.join(base_dir, settings.LOCAL_METADATA_NAME)

    if not os.path.isdir(base_dir):
        raise RuntimeError(f"本地向量索引目录创建失败：{base_dir}")

    faiss.write_index(index, index_path)
    with open(meta_path, "wb") as f:
        pickle.dump(metadata, f)

    elapsed_ms = int((time.time() - start) * 1000)
    # 额外返回实际的向量维度
    return {
        "paper_count": len(metadata),
        "vector_dim": d,
        "configured_vector_dim": int(settings.VECTOR_DIM),
        "embedding_model": settings.CHATCHAT_EMBEDDING_MODEL,
        "index_path": index_path,
        "meta_path": meta_path,
        "elapsed_ms": elapsed_ms,
    }


def local_vdb_init(request):
    try:
        info = build_local_faiss_index()
        return ok({"success": "成功", "info": info})
    except Exception as e:
        return fail(msg=str(e))


def local_vdb_status(_request):
    """
    只读：查看本地 FAISS 索引就绪状态与路径解析结果。
    """
    index_path = _faiss_index_path()
    meta_path = _faiss_meta_path()
    data = {
        "paper_count": Paper.objects.count(),
        "vector_dim": int(settings.VECTOR_DIM),
        "base_dir": _resolve_vdb_base_dir(),
        "index": {
            "path": index_path,
            "exists": os.path.exists(index_path),
            "bytes": os.path.getsize(index_path) if os.path.exists(index_path) else 0,
            "mtime": os.path.getmtime(index_path) if os.path.exists(index_path) else None,
        },
        "metadata": {
            "path": meta_path,
            "exists": os.path.exists(meta_path),
            "bytes": os.path.getsize(meta_path) if os.path.exists(meta_path) else 0,
            "mtime": os.path.getmtime(meta_path) if os.path.exists(meta_path) else None,
        },
    }
    return ok({"data": data})


def get_filtered_paper(text, k, threshold=None):
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    # 1. 加载索引和元数据(是否可在初始化中加载) 2. 进行查询
    try:
        _ensure_faiss_ready()
    except FileNotFoundError as e:
        # 被搜索/推荐等链路调用时，不应直接把整个流程打崩
        print(f"[warn][FAISS] {e}")
        return []

    index = faiss.read_index(_faiss_index_path())
    with open(
        _faiss_meta_path(),
        "rb",
    ) as f:
        metadata = pickle.load(f)
    embed_texts = embed(text)[0]
    distances, indices = index.search(np.array([embed_texts], dtype=np.float32), k)
    i2d_dict = {}
    for d, i in zip(distances[0], indices[0]):
        i2d_dict[metadata[i]] = d
    paper_ids = [metadata[i] for i in indices[0]]
    filtered_papers = Paper.objects.filter(paper_id__in=paper_ids)
    ht_threshold_papers = []
    for p in filtered_papers:
        # IndexFlatL2 返回的是“L2 距离”，越小越相似；threshold 语义应为“最大允许距离”
        dist = i2d_dict[p.paper_id]
        if threshold is not None and dist > threshold:
            continue
        # p_dict = p.to_dict()
        # p_dict['distance'] = float(dist)
        ht_threshold_papers.append(p)
    return ht_threshold_papers


def easy_vector_query(request):
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    # 1. 加载索引和元数据(是否可在初始化中加载) 2. 进行查询
    try:
        _ensure_faiss_ready()
    except FileNotFoundError as e:
        return fail(msg=str(e))

    index = faiss.read_index(_faiss_index_path())
    with open(
        _faiss_meta_path(),
        "rb",
    ) as f:
        metadata = pickle.load(f)

    request_data = json.loads(request.body)
    texts = request_data["texts"]
    k = request_data["k"]
    if not k:
        k = 20
    if not isinstance(texts, list):
        texts = [texts]

    embed_texts = embed(texts)

    # 查找，返回相似论文
    # distances: [1, K], indices: [1, k]
    distances, indices = index.search(np.array(embed_texts, dtype=np.float32), k)
    i2d_dict = {}
    for d, i in zip(distances[0], indices[0]):
        i2d_dict[metadata[i]] = d
    paper_ids = [metadata[i] for i in indices[0]]
    filtered_paper = Paper.objects.filter(paper_id__in=paper_ids)
    paper_dict = []
    for p in filtered_paper:
        p_dict = p.to_dict()
        p_dict["similarity"] = float(i2d_dict[p.paper_id])
        print(p_dict)
        paper_dict.append(p_dict)

    return ok({"papers": paper_dict})
