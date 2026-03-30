# EPP-Backend-Dev

EPP 项目的后端服务，基于 Django 实现，负责用户认证、论文检索与推荐、论文解读与摘要、文件上传与存储、向量检索等核心能力。

## 1. 仓库内容概览

本目录是一个独立可运行的 Django 后端项目，核心结构如下：

- `backend/`：Django 项目配置（`settings.py`、`urls.py`、`wsgi.py`）
- `business/`：业务主应用（API、模型、工具函数、后台管理逻辑）
- `resource/`：本地资源目录（用户上传、缓存、数据库相关文件）
- `vector_database/`：向量检索相关数据目录
- `manage.py`：Django 管理入口
- `requirements.txt`：Python 依赖清单
- `development.env`：运行配置（由 `EPP-Configuration/link.sh` 软链接生成）

## 2. 技术栈

- Python `>=3.10`（当前环境建议 `3.12`）
- Django `5.1.7`
- 数据库：
  - 本地开发默认 `SQLite`（`development.sqlite3`）
  - 可切换 MySQL（通过 `DB_ENGINE/DB_*` 配置）
- 任务/定时：
  - `django-background-tasks`
  - `django-crontab` / `django-cron`
- AI 与检索相关：
  - `openai`
  - `faiss-cpu`
  - `tavily-python`
  - `pymupdf`、`jieba` 等文本处理能力
- 对象存储：
  - `minio`

## 3. 配置说明

后端从项目根目录下的 `development.env` 读取配置，代码中通过 `python-decouple` 加载。

### 3.1 配置文件来源

在单仓库根目录执行：（替换为实际路径）

```bash
cd /home/Spencer/projects/SE_project/EPP-Configuration
bash link.sh
```

会在本目录生成软链接：

- `development.env -> ../EPP-Configuration/backend/development.env`

### 3.2 关键配置项

`development.env` 至少应包含以下配置：

- Django 基础：
  - `SECRET_KEY`
  - `ADMIN_USERNAME`
  - `ADMIN_PASSWORD`
  - `JWT_SECRET_KEY`
- 数据库：
  - `DB_ENGINE`
  - `DB_NAME`
  - （若使用 MySQL）`DB_USER`、`DB_PASSWORD`、`DB_HOST`、`DB_PORT`
- 远程模型/服务：
  - `REMOTE_CHAT_CHAT_PATH`
  - `CHAT_CHAT_MANAGER_PORT`
  - `MODEL_BASE_PORT`
  - `CHAT_GLM_PORT`
  - `GLM3_OPENAI_PORT`
- 三方服务：
  - `DEEPSEEK_API_KEY`
  - `TAVILY_API_KEY`
  - `SIMPLIFY_TRANS_KEY`
  - `CENSOR_API_KEY`、`CENSOR_SECRET_KEY`
- 文件与工具：
  - `WKHTMLTOPDF_PATH`
  - `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`

## 4. 本地开发启动

### 4.1 安装依赖

```bash
python3 -m venv .venv
.venv/bin/pip install --default-timeout=600 --retries 10 -r requirements.txt
```

> 若 `mysqlclient` 安装失败，请先安装系统依赖：`pkg-config`、`default-libmysqlclient-dev`、`build-essential`。

### 4.2 初始化数据库

```bash
.venv/bin/python manage.py migrate --noinput
```

### 4.3 启动服务

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

启动后可访问：

- 管理后台登录页：`http://127.0.0.1:8000/admin/login/`

## 5. 接口与业务模块说明

业务代码集中在 `business/`，其中：

- `business/api/`：按业务能力划分的接口模块（认证、检索、推荐、论文解读、摘要、上传等）
- `business/models/`：核心数据模型（用户、论文、评论、检索记录、报告等）
- `business/utils/`：模型调用、存储、下载、向量库初始化、系统信息等工具逻辑

路由统一注册在 `backend/urls.py`，新增接口时建议：

1. 在 `business/api/` 内新增或扩展模块
2. 在 `backend/urls.py` 显式注册路由
3. 在本 README 补充变更说明（接口分组、依赖、配置影响）

## 6. 常用命令

```bash
# 迁移
.venv/bin/python manage.py migrate

# 创建迁移
.venv/bin/python manage.py makemigrations

# 创建管理员
.venv/bin/python manage.py createsuperuser

# 收集静态文件（如需要）
.venv/bin/python manage.py collectstatic
```

## 7. 常见问题（FAQ）

- 端口被占用：`Error: That port is already in use`
  - 处理：释放 `8000` 端口或改用 `runserver 127.0.0.1:<new_port>`
- 启动时报 `development.env` 缺失
  - 处理：先执行 `EPP-Configuration/link.sh`，确认软链接存在
- 前端调用跨域失败
  - 检查 `backend/settings.py` 中 `CORS_ALLOWED_ORIGINS` 是否包含前端地址
- 模型调用失败或超时
  - 检查 `REMOTE_*` 与模型服务端口配置，以及目标服务可达性

## 8. 安全与提交建议

- 不要提交真实密钥、生产口令到仓库
- `development.env` 推荐仅使用脱敏或本地开发值
- 新增配置项时，同时更新：
  - `EPP-Configuration/backend/development.env` 模板
  - 本 README 的“关键配置项”章节
