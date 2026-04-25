from django.apps import AppConfig
import os
import sys
import threading


class BusinessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "business"

    def ready(self):
        """
        启动时检查本地 FAISS 索引文件是否缺失，缺失则后台自动重建一次。
        - 仅在服务启动场景触发（runserver/gunicorn等）
        - 避免 autoreload 导致重复执行
        """
        argv = " ".join(sys.argv).lower()
        is_server_start = any(k in argv for k in ["runserver", "gunicorn", "uwsgi", "daphne"])

        # Django autoreload: only run in main process
        if "runserver" in argv and os.environ.get("RUN_MAIN") != "true":
            return
        if not is_server_start:
            return

        from business.utils.paper_vdb_init import _faiss_index_path, _faiss_meta_path, build_local_faiss_index

        idx = _faiss_index_path()
        meta = _faiss_meta_path()
        missing = (not os.path.exists(idx)) or (not os.path.exists(meta))
        if not missing:
            return

        # 进程内互斥，避免并发触发多次重建
        if getattr(self, "_faiss_rebuild_started", False):
            return
        self._faiss_rebuild_started = True

        def _bg_rebuild():
            try:
                info = build_local_faiss_index()
                print(f"[FAISS] 自动重建完成: {info}")
            except Exception as e:
                print(f"[FAISS] 自动重建失败: {e!r}")

        threading.Thread(target=_bg_rebuild, daemon=True).start()
