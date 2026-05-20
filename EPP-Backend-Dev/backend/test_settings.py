"""本地/CI 单元测试：SQLite 内存库，避免依赖 MySQL test 库权限。"""

from .settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
