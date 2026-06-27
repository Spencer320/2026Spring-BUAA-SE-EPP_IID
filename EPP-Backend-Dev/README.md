# EPP-Backend-Dev

## 环境要求

- Python `>=3.10`（建议 `3.12`）
- 包管理：项目根目录下使用虚拟环境 `.venv`
- 数据库：本地默认 SQLite；生产可切换 MySQL（需安装 `mysqlclient` 及系统依赖 `pkg-config`、`default-libmysqlclient-dev`、`build-essential`）
- 可选外部服务（按功能需要）：
  - MinIO（对象存储）
  - 远程 ChatChat / 模型服务（`REMOTE_*` 相关配置）
  - Playwright Chromium（启用 Web Operator 时：`playwright install chromium`）

## 配置

后端从项目根目录的 `development.env` 读取配置（`python-decouple`），该文件通过 `EPP-Configuration/link.sh` 软链接到 `EPP-Configuration/backend/development.env`。

### 首次配置

在 mono-repo 根目录执行：

```bash
cd EPP-Configuration
bash link.sh
```

若本地尚无 `development.env`，脚本会从 `development.env.template` 复制生成。编辑该文件，填入有效密钥后再启动后端。

### 关键配置项

完整字段与注释见 `EPP-Configuration/backend/development.env.template`。本地开发至少需要：

| 分类 | 变量 |
|------|------|
| Django 基础 | `SECRET_KEY`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`、`JWT_SECRET_KEY` |
| 数据库 | `DB_ENGINE`、`DB_NAME`（MySQL 另需 `DB_USER`、`DB_PASSWORD`、`DB_HOST`、`DB_PORT`） |
| 远程模型 | `REMOTE_CHAT_CHAT_PATH`、`CHAT_CHAT_MANAGER_PORT`、`MODEL_BASE_PORT`、`CHAT_GLM_PORT`、`GLM3_OPENAI_PORT`、`CHATCHAT_CHAT_MODEL`、`CHATCHAT_EMBEDDING_MODEL` |
| LLM / 搜索 | `RA_LLM_BASE_URL`、`RA_LLM_API_KEY`、`RA_LLM_MODEL`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_API_KEY`、`TAVILY_API_KEY` |
| 存储与工具 | `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`WKHTMLTOPDF_PATH` |
| 其他 | `SIMPLIFY_TRANS_KEY`、`CENSOR_API_KEY`、`CENSOR_SECRET_KEY` |

配置变更在 `EPP-Configuration/backend/development.env` 中修改即可，子项目软链接会自动生效。

## 启动

```bash
# 1. 安装依赖
python3 -m venv .venv
.venv/bin/pip install --default-timeout=600 --retries 10 -r requirements.txt

# 2. 初始化数据库
.venv/bin/python manage.py migrate --noinput

# 3. 启动开发服务
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

默认地址：`http://127.0.0.1:8000`  
Django 管理后台：`http://127.0.0.1:8000/admin/login/`（账号见 `ADMIN_USERNAME` / `ADMIN_PASSWORD`）

## 常用命令

```bash
.venv/bin/python manage.py migrate          # 执行迁移
.venv/bin/python manage.py makemigrations   # 生成迁移文件
.venv/bin/python manage.py createsuperuser  # 创建管理员
.venv/bin/python -m pytest business/tests/  # 运行测试
```

## 与前端联调

后端 `backend/settings.py` 中 `CORS_ALLOWED_ORIGINS` 需包含前端开发地址，默认已包含：

- 用户端：`http://localhost:8080`、`http://127.0.0.1:8080`
- 管理端：`http://localhost:5173`

若前端端口变化（如 Vite 自动切换），需在后端追加对应 origin。

## 常见问题

- **`development.env` 缺失**  
  执行 `EPP-Configuration/link.sh`，确认 `development.env` 为指向配置中心的软链接。

- **端口被占用**  
  释放 `8000` 端口，或改用 `runserver 127.0.0.1:<其他端口>`，并同步修改前端 API 地址。

- **跨域失败**  
  检查 `CORS_ALLOWED_ORIGINS` 是否包含当前前端 origin。

- **`mysqlclient` 安装失败**  
  安装系统依赖后重试：`pkg-config`、`default-libmysqlclient-dev`、`build-essential`。

- **模型 / 外部服务调用失败**  
  检查 `REMOTE_*`、LLM、MinIO 等配置及对应服务是否可达。
