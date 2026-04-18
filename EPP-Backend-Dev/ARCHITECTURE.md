# EPP-Backend 项目架构说明文档

## 目录

1. [Django 快速入门](#1-django-快速入门)
2. [项目整体结构总览](#2-项目整体结构总览)
3. [配置层：`backend/` 目录](#3-配置层backend-目录)
4. [业务层：`business/` 应用](#4-业务层business-应用)
   - [4.1 模型层 `models/`](#41-模型层models)
   - [4.2 接口层 `api/`](#42-接口层api)
   - [4.3 工具层 `utils/`](#43-工具层utils)
   - [4.4 管理命令 `management/`](#44-管理命令management)
   - [4.5 测试 `tests/`](#45-测试tests)
5. [资源与文件存储：`resource/`](#5-资源与文件存储resource)
6. [独立脚本：`scripts/` 与 `vector_database/`](#6-独立脚本scripts-与-vector_database)
7. [配置文件说明](#7-配置文件说明)
8. [核心技术机制详解](#8-核心技术机制详解)
9. [API 接口速查表](#9-api-接口速查表)

---

## 1. Django 快速入门

### Django 是什么？

Django 是 Python 的一个 Web 框架，遵循 **MTV 架构**（Model-Template-View），用来快速构建 Web 后端。本项目是纯后端 API 服务，不使用 Template（模板），只使用 Model 和 View。

### Django 项目的标准结构

一个典型的 Django 项目由两层组成：

```
项目根目录/
├── 项目配置包/          ← 与项目同名的包，存放全局配置（settings、urls）
│   ├── settings.py     ← 全局配置文件（数据库、中间件、已安装应用等）
│   ├── urls.py         ← 根 URL 路由表（将 URL 分发给各 App 的视图函数）
│   ├── wsgi.py         ← 生产部署入口（WSGI 协议）
│   └── asgi.py         ← 异步部署入口（ASGI 协议）
│
├── 应用(App)/           ← 一个 Django 项目可有多个 App，每个 App 负责一块功能
│   ├── models.py       ← 数据模型（对应数据库中的表）
│   ├── views.py        ← 视图函数（处理 HTTP 请求并返回响应）
│   ├── urls.py         ← App 级别的 URL 路由（可选）
│   ├── admin.py        ← 后台管理界面注册
│   ├── apps.py         ← App 配置信息
│   └── migrations/     ← 数据库迁移文件（自动生成，记录 model 变更历史）
│
└── manage.py           ← 命令行工具（启动服务器、执行迁移等）
```

### 核心概念速览

| 概念 | 说明 | 本项目中的位置 |
|------|------|---------------|
| **Model（模型）** | 用 Python 类定义数据库表结构，Django 自动生成 SQL | `business/models/` |
| **View（视图）** | 接收 HTTP 请求、执行业务逻辑、返回 JSON 响应的函数 | `business/api/` |
| **URL 路由** | 将形如 `/api/login` 的路径映射到对应的视图函数 | `backend/urls.py` |
| **Migration（迁移）** | 每次修改 Model 后，运行 `makemigrations` 生成迁移文件，再运行 `migrate` 更新数据库 | `business/migrations/` |
| **settings.py** | 相当于项目的"配置中心"，控制数据库连接、中间件、跨域等一切全局行为 | `backend/settings.py` |
| **manage.py** | 项目管理脚本，常用命令见下表 | 根目录 |

### 常用 `manage.py` 命令

```bash
# 启动开发服务器（默认端口 8000）
python manage.py runserver

# 根据 models.py 的改动生成迁移文件
python manage.py makemigrations

# 将迁移文件同步到数据库（真正修改数据库表结构）
python manage.py migrate

# 进入 Django 的交互式 Shell（可直接操作数据库）
python manage.py shell

# 执行自定义管理命令（如本项目的 insert_paper）
python manage.py insert_paper
```

### 一个请求的完整生命周期

```
前端发送 HTTP 请求
        ↓
    WSGI/ASGI 服务器（uWSGI / Uvicorn）
        ↓
    Django 中间件（Middleware）链式处理
    （跨域检查 CORS、Session 验证、安全头 等）
        ↓
    根 URL 路由（backend/urls.py）匹配路径
        ↓
    视图函数（business/api/*.py）执行业务逻辑
    ├── 读取 request.body / request.GET 中的参数
    ├── 调用 Model 操作数据库（ORM）
    ├── 调用 utils/ 中的工具（AI 模型、翻译、存储等）
    └── 返回 JsonResponse
        ↓
    前端接收 JSON 响应
```

---

## 2. 项目整体结构总览

```
EPP-Backend-Dev/
├── backend/                    # Django 项目配置包（全局配置）
│   ├── settings.py             # 全局配置：数据库、中间件、路径、密钥等
│   ├── urls.py                 # 根路由：所有 API 端点的总入口
│   ├── wsgi.py                 # 生产部署入口（WSGI）
│   └── asgi.py                 # 异步部署入口（ASGI）
│
├── business/                   # 核心业务 Django App（项目唯一的 App）
│   ├── api/                    # 视图层：所有 HTTP 接口处理函数
│   ├── models/                 # 数据层：所有数据库模型定义
│   ├── utils/                  # 工具层：AI 调用、存储、认证等通用工具
│   ├── management/commands/    # 自定义 CLI 命令（数据初始化等）
│   ├── migrations/             # 数据库迁移文件（自动生成）
│   ├── tests/                  # 单元测试与集成测试
│   ├── admin.py                # Django 后台管理注册
│   ├── admin_site.py           # 自定义管理员后台认证后端
│   ├── apps.py                 # App 元信息配置
│   └── views.py                # 空文件（接口逻辑已全部迁移到 api/ 目录）
│
├── resource/                   # 持久化文件存储目录
│   ├── database/papers/        # 论文 PDF 文件缓存
│   ├── database/users/         # 用户相关数据（报告、对话历史）
│   └── uploads/users/          # 用户上传的文档
│
├── scripts/                    # 开发/实验性独立脚本（不属于 Django）
├── vector_database/            # 向量数据库相关实验脚本
│
├── manage.py                   # Django 命令行管理工具
├── development.env             # 本地开发环境变量配置（含密钥、数据库连接等）
├── requirements.txt            # Python 依赖包清单
├── Epp_BackEnd.ini             # uWSGI 生产部署配置文件
├── .github/workflows/          # GitHub Actions CI 配置（代码格式检查）
└── README.md                   # 原始文件状态追踪说明
```

---

## 3. 配置层：`backend/` 目录

这是 Django 自动生成的项目配置包，包含最关键的全局配置。

### `backend/settings.py` — 项目配置中心

这是整个项目最重要的配置文件，以下是各配置块的说明：

#### 环境变量加载
```python
config = RepositoryEnv(str(BASE_DIR / "development.env"))
```
使用 `python-decouple` 库从 `development.env` 文件中读取所有敏感配置（密钥、数据库密码等），避免硬编码在代码中。

#### 已安装的应用（`INSTALLED_APPS`）
| App 名称 | 用途 |
|---------|------|
| `django.contrib.admin` | Django 自带的后台管理界面（`/admin/`） |
| `django.contrib.auth` | 用户认证框架 |
| `corsheaders` | 处理跨域请求（CORS）|
| `business` | 本项目的核心业务 App |
| `django_crontab` | 定时任务支持 |
| `background_task` | 后台异步任务支持 |

#### 跨域配置（CORS）
项目允许来自特定前端域名（`localhost:8080`、`localhost:5173`、`epp.swkfk.top` 等）的跨域请求，并支持携带 Cookie（`CORS_ALLOW_CREDENTIALS = True`）。

#### 数据库配置
通过 `development.env` 动态读取，**本地开发默认使用 MySQL**：
```ini
DB_ENGINE = django.db.backends.mysql
DB_NAME = EPP
DB_HOST = 127.0.0.1
DB_PORT = 3306
```

#### 文件路径配置
`settings.py` 中定义了大量路径常量，供各 API 模块使用：

| 常量 | 说明 |
|------|------|
| `USER_AVATARS_PATH` | 用户头像存储路径 |
| `USER_DOCUMENTS_PATH` | 用户上传文档路径 |
| `USER_REPORTS_PATH` | AI 生成报告路径 |
| `USER_SEARCH_CONSERVATION_PATH` | 调研助手对话历史 JSON 文件路径 |
| `USER_READ_CONSERVATION_PATH` | 论文研读对话历史路径 |
| `PAPERS_PATH` | 论文 PDF 本地缓存路径 |
| `BATCH_DOWNLOAD_PATH` | 批量下载压缩包路径 |

#### AI 模型服务地址
项目依赖外部部署的 AI 服务（ChatGLM、DeepSeek 等），通过环境变量配置其地址和端口：

| 常量 | 说明 |
|------|------|
| `REMOTE_MODEL_BASE_PATH` | 知识库/对话基础模型 API 地址 |
| `REMOTE_CHATCHAT_GLM3_OPENAI_PATH` | GLM3 的 OpenAI 兼容接口地址 |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `TAVILY_API_KEY` | Tavily 搜索引擎 API 密钥 |

#### 定时任务（CRONJOBS）
```python
CRONJOBS = [
    ("*/3 * * * *", "business.models.paper_visit_recent.PaperVisitRecent.clear_three_days"),
]
```
每 3 分钟自动清理超过 3 天的"最近浏览"记录。

---

### `backend/urls.py` — 根路由总表

这是所有 API 端点的"目录"，将 URL 路径映射到 `business/api/` 下的视图函数。路由按功能模块分组：

| URL 前缀 | 对应功能模块 |
|----------|------------|
| `/api/login`、`/api/sign` 等 | 用户与管理员认证 |
| `/api/getPaperInfo`、`/api/likeComment` 等 | 论文详情页 |
| `/api/uploadPaper`、`/api/userInfo/documents` 等 | 用户文档管理 |
| `/api/userInfo/...` | 个人中心 |
| `/api/manage/...` | 管理员后台 |
| `/api/v2/search/...` | 智能文献检索 |
| `/api/study/...` | 论文研读（AI 对话） |
| `/api/summary/...` | 综述报告生成 |
| `/api/paperRecommend/...` | 文献推荐 |
| `/api/translate/...` 等 | 文献翻译 |
| `/api/paper/annotations` 等 | 文献批注 |
| `/resource/...` | 静态资源（PDF、图片等）访问 |

---

## 4. 业务层：`business/` 应用

`business` 是本项目唯一的 Django App，承载所有业务逻辑。

### 4.1 模型层：`models/`

每个文件对应数据库中的一张或多张表，使用 Django ORM 定义。

#### 核心数据模型

**`user.py` — 普通用户表 `User`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | UUIDField（主键） | 自动生成的唯一用户 ID |
| `username` | CharField | 用户名 |
| `password` | CharField | 哈希后的密码（PBKDF2） |
| `avatar` | ImageField | 头像图片 |
| `registration_date` | DateTimeField | 注册时间（自动填充） |
| `collected_papers` | ManyToManyField → Paper | 收藏的论文（多对多） |
| `liked_papers` | ManyToManyField → Paper | 点赞的论文（多对多） |

**`paper.py` — 论文表 `Paper`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `paper_id` | UUIDField（主键） | 唯一论文 ID |
| `title` | CharField | 论文标题 |
| `authors` | CharField | 作者（逗号分隔） |
| `abstract` | TextField | 摘要 |
| `publication_date` | DateField | 发布日期 |
| `journal` | CharField | 期刊名称 |
| `citation_count` | IntegerField | 引用次数 |
| `original_url` | URLField | 原文链接（arXiv 等） |
| `read/like/collect/comment/download_count` | IntegerField | 各类计数 |
| `score` / `score_count` | Float/Int | 评分及评分人数 |
| `local_path` | CharField | 本地 PDF 文件路径 |
| `sub_classes` | ManyToManyField → Subclass | 所属学科分类 |

#### 完整模型列表

| 文件 | 模型类 | 用途 |
|------|--------|------|
| `user.py` | `User` | 普通用户 |
| `paper.py` | `Paper` | 论文主体信息 |
| `admin.py` | `Admin` | 管理员账户 |
| `subclass.py` | `Subclass` | 学科分类标签 |
| `comment.py` | `FirstLevelComment`, `SecondLevelComment`, `AutoDeletedFirstComment`, `AutoDeletedSecondComment` | 论文评论（一级/二级） |
| `comment_report.py` | `CommentReport` | 评论举报记录 |
| `paper_score.py` | `PaperScore` | 用户对论文的打分记录 |
| `paper_note.py` | `PaperNote`, `UserDocumentNote` | 论文/文档笔记 |
| `paper_annotation_new.py` | `PaperAnnotationNew`, `PaperAnnotationComment`, `PaperAnnotationSubComment`, `PaperAnnotationItem` 等 | PDF 批注及批注评论体系（新版） |
| `paper_annotation.py` | `PaperAnnotation`, `PaperAnnotationCommentFirstLevel`, `PaperAnnotationCommentSecondLevel` | PDF 批注（旧版，保留兼容） |
| `paper_translation.py` | `PaperTranslation`, `UserDocumentTranslation` | 论文/文档翻译记录 |
| `paper_visit_recent.py` | `PaperVisitRecent` | 最近浏览记录（定时清理） |
| `paper_position.py` | `PaperPosition` | PDF 阅读位置记录 |
| `search_record.py` | `SearchRecord` | 用户检索记录（含关联论文） |
| `file_reading.py` | `FileReading` | 用户论文研读会话记录 |
| `glossary.py` | `Glossary`, `GlossaryTerm` | 用户自定义术语表 |
| `summary_report.py` | `SummaryReport` | AI 生成的综述报告 |
| `summary_generation_session.py` | `SummaryGenerateSession` | 综述报告生成会话 |
| `abstract_report.py` | `AbstractReport` | 摘要报告 |
| `ai_dialog_storage.py` | `SummaryDialogStorage`, `VectorSearchStorage`, `DialogSearchStorage` | AI 异步任务的中间状态存储 |
| `notification.py` | `Notification` | 系统通知（如举报处理结果） |
| `user_document.py` | `UserDocument` | 用户上传的文档记录 |
| `statistic.py` | `UserDailyAddition`, `UserVisit` | 统计数据（每日新增用户、访问量） |
| `recommended_papers.py` | — | 推荐论文缓存相关 |
| `auto_deleted.py` | `AutoDeletedPaperAnnotation` 等 | 被删除（待管理员审核）的批注记录 |
| `detectable.py` | — | 可检测实体基类（Mixin） |

#### `models/__init__.py` 的作用
将所有模型集中导出，使得其他模块只需 `from business.models import User, Paper` 即可使用，无需关心具体文件路径。

---

### 4.2 接口层：`api/`

每个文件对应一个功能模块，文件内的函数即为视图函数（View），每个视图函数处理一个 HTTP 接口。

#### 视图函数的通用写法模式

```python
from django.views.decorators.http import require_http_methods
from business.utils.authenticate import authenticate_user
from business.utils.response import ok, fail

@authenticate_user                  # 装饰器：验证 JWT Token，注入 user 对象
@require_http_methods(["POST"])     # 装饰器：限定 HTTP 方法
def some_api(request, user: User):  # user 由 authenticate_user 注入
    data = json.loads(request.body) # 解析请求体
    # ... 业务逻辑 ...
    return ok({"result": "..."})    # 返回统一格式的 JSON 响应
```

#### API 文件详解

**`auth.py` — 认证模块**
- `login`：用户登录，验证密码后签发 JWT Token
- `signup`：用户注册，密码 PBKDF2 哈希后存储，同时记录每日新增统计
- `logout`：清除 Session
- `manager_login` / `manager_logout`：管理员登录/登出，签发管理员角色 JWT

**`paper_details.py` — 论文详情模块**
提供论文详情页所需的全部接口：点赞、评分、收藏、评论（一级/二级）、举报评论、批量下载（打包为 ZIP）、获取论文基本信息、获取用户与论文的关系（是否收藏/点赞）。

**`search.py` — 智能检索模块**（最复杂的模块）

采用**异步任务**模式：
1. 前端调用 `POST /api/v2/search/vectorQuery` 发起检索，后端立即返回 `search_record_id`，并在新线程中执行耗时检索
2. 前端轮询 `GET /api/v2/search/status` 查询进度
3. 检索完成后，前端调用 `GET /api/v2/search/result` 获取结果

检索流程包含：
- **字符检索**：中译英 → 分词 → 数据库 LIKE 查询 → 编辑距离排序
- **对话检索**：向量检索（本地 FAISS 库）+ 关键词检索 → 合并结果 → 调用 GLM 生成摘要 → 构建临时知识库
- **调研助手对话**（`dialog_query_v2`）：使用 DeepSeek R1 拆解子问题 → 三路并行（本地知识库 LLM + Tavily 搜索 + arXiv API）→ 多智能体结果整合

**`paper_interpret.py` — 论文研读模块**
用于基于 PDF 进行 AI 对话，支持创建/恢复研读会话、发送消息、清空对话。

**`summary.py` — 综述报告生成模块**
基于用户选定的多篇论文，使用 AI 生成综述报告，同样采用异步任务 + 状态轮询的模式。

**`translation.py` — 文献翻译模块**
支持整篇文章（PDF）翻译、术语表查询、自定义词汇表管理，翻译状态异步查询。

**`annotation.py` — 文献批注模块**
提供 PDF 批注的增删查，以及批注的评论（两级评论体系）、点赞功能。

**`note.py` / `paper_notes.py` — 笔记模块**
`paper_notes.py` 为新版笔记（按论文或文档存储富文本），`note.py` 为旧版简单笔记。

**`upload_document.py` — 用户文档上传模块**
用户可上传自己的 PDF 文档（非平台收录的论文），支持存储到 MinIO 对象存储。

**`user_info.py` — 个人中心模块**
获取/修改用户信息、头像，管理收藏列表、搜索历史、综述报告、研读记录、通知消息。

**`manage.py` — 管理员模块**
管理员的统计数据查看（用户列表、论文列表、评论举报处理、服务器状态、访问统计等）。

**`manage_auto_deleted_items.py` — 管理员审核被删除内容**
查看被系统标记（软删除）的批注，管理员可选择恢复。

**`paper_recommend.py` — 文献推荐模块**
- `get_recommendation`：基于热度（点赞/阅读/收藏）的热门推荐
- `individuation_recommend`：基于用户历史行为的个性化推荐

**`vector_database.py`**
向量数据库相关接口（已基本迁移到 `utils/paper_vdb_init.py`）。

---

### 4.3 工具层：`utils/`

存放各种可复用的工具函数，被 `api/` 层调用。

| 文件 | 主要功能 |
|------|---------|
| `authenticate.py` | JWT 认证装饰器 `authenticate_user` 和 `authenticate_admin`，从请求头提取并验证 Token，将用户对象注入视图函数 |
| `jwt_provider.py` | JWT Token 的生成（`encode`）与解析（`decode`），封装了 PyJWT 库，Token 有效期默认 14 天 |
| `response.py` | 统一响应工具：`ok(data)`（200）、`fail(data)`（400）、`unauthorized(data)`（401）|
| `chat_glm.py` | 调用远程 ChatGLM 大模型进行对话（`query_glm`） |
| `chat_r1.py` | 调用 DeepSeek R1 / DeepSeek API 进行推理（`query_r1`）|
| `chat_tavily.py` | 调用 Tavily 搜索引擎 API 进行实时网络检索（`query_tavily`）|
| `knowledge_base.py` | 操作远程知识库服务：上传论文构建临时知识库（`build_kb_by_paper_ids`）、上传摘要构建知识库（`build_abs_kb_by_paper_ids`）、删除临时知识库 |
| `paper_vdb_init.py` | 本地向量数据库（FAISS）的初始化与查询（`get_filtered_paper`），用于语义相似度检索 |
| `vector_embedding.py` | 文本向量化，生成论文摘要的向量表示（供 FAISS 索引） |
| `storage.py` | 自定义 Django 存储后端（`ImageStorage`），将文件上传到 MinIO 对象存储 |
| `download_paper.py` | 从 arXiv 等网址下载论文 PDF 到本地 |
| `article_translate.py` | 整篇文章翻译的核心逻辑 |
| `pdf_translate.py` | PDF 文件翻译（提取文本 + 翻译 + 重新排版）|
| `trans.py` | 文本翻译工具（调用第三方翻译 API）|
| `glossary_recommend.py` | 基于术语表的推荐翻译 |
| `auto_detect.py` | 自动检测内容（如评论内容安全检测） |
| `text_censor.py` | 调用百度内容审核 API 对评论文本进行违规检测 |
| `scholar_search.py` | 查询学者信息（通过外部 API）|
| `system_info.py` | 获取服务器状态信息（CPU、内存、GPU 等，供管理员界面展示）|
| `futures.py` | 工具装饰器，如 `@deprecated` 标记废弃函数 |
| `md_pdf.py` | Markdown 转 PDF（已标记为不在主线服务器运行）|
| `milvus.py` | Milvus 向量数据库接口（已标记为不在主线服务器运行）|
| `classification.py` | 论文分类模型（已标记为不在主线服务器运行）|
| `container_helper.py` | Docker 容器操作辅助工具 |

---

### 4.4 管理命令：`management/commands/`

使用 `python manage.py <命令名>` 调用，主要用于数据初始化。

| 命令文件 | 命令名 | 用途 |
|---------|--------|------|
| `insert_paper.py` | `insert_paper` | 向数据库批量导入论文数据 |
| `insert_glossary.py` | `insert_glossary` | 初始化系统术语表 |
| `insert_manager.py` | `insert_manager` | 创建管理员账户 |
| `query_paper.py` | `query_paper` | 命令行查询论文信息（调试用） |
| `clean_cache.py` | `clean_cache` | 清理临时缓存文件 |

---

### 4.5 测试：`tests/`

| 文件 | 测试内容 |
|------|---------|
| `helper_user.py` | 用户相关测试辅助函数（创建测试用户等） |
| `helper_paper.py` | 论文相关测试辅助函数 |
| `helper_session.py` | 认证 Session/Token 辅助函数 |
| `test_basic_auth.py` | 登录、注册、登出接口测试 |
| `test_annotation.py` | 批注功能接口测试 |
| `test_note.py` | 笔记功能接口测试 |
| `test_translation.py` | 翻译功能接口测试 |
| `test_manager_statistics.py` | 管理员统计接口测试 |

运行测试：
```bash
python manage.py test business.tests
```

---

## 5. 资源与文件存储：`resource/`

```
resource/
├── database/
│   ├── papers/              # 论文 PDF 文件缓存（文件名为 paper_id.pdf）
│   │   └── abs/             # 论文摘要文本文件（用于快速构建知识库）
│   └── users/
│       ├── batch_download/  # 批量下载生成的 ZIP 压缩包
│       ├── conversation/
│       │   ├── read/        # 论文研读会话对话历史 JSON 文件
│       │   └── search/      # 调研助手会话对话历史 JSON 文件
│       │       └── search_record_2_tmp_kb_id_map.json  # 检索记录与临时知识库的映射表
│       └── reports/         # AI 生成的综述报告文件
└── uploads/
    └── users/
        └── documents/       # 用户上传的个人文档（PDF 等）
```

**注意**：用户头像存储在 MinIO 对象存储服务中（通过 `storage.ImageStorage` 实现），不在 `resource/` 目录下。

---

## 6. 独立脚本：`scripts/` 与 `vector_database/`

这两个目录下的脚本**不属于 Django 项目的一部分**，是开发/实验阶段的独立脚本，直接运行而无需 Django 环境（部分除外）。

### `scripts/`

| 文件 | 用途 |
|------|------|
| `chatchat.py` / `chatchat_newopenai.py` | 测试与 ChatChat 服务对话 |
| `chatGLM.py` | 测试 ChatGLM 接口 |
| `kimi.py` | 测试 Kimi 大模型接口 |
| `upload_paper_to_database.py` | 批量从 arXiv 爬取论文并写入数据库 |
| `train_recommand_model.py` | 训练个性化推荐模型 |
| `clear_abs.py` | 清理摘要文件 |

### `vector_database/`

| 文件 | 用途 |
|------|------|
| `main.py` | 向量数据库初始化主脚本 |
| `sci_bert_embedding.py` | 使用 SciBERT 模型生成论文摘要的向量表示 |
| `milvus_test.py` | Milvus 向量数据库连接测试 |
| `langchain_test.py` | LangChain 集成测试 |
| `exe_pdf.py` | PDF 处理工具 |
| `t5_translate.py` | 使用 T5 模型进行翻译 |
| `chatglm_translate.py` | 使用 ChatGLM 进行翻译 |

---

## 7. 配置文件说明

### `development.env` — 本地开发环境配置

此文件**不应提交到 Git**（已加入 `.gitignore`），包含所有敏感信息：

```ini
SECRET_KEY = ...          # Django 安全密钥（用于签名 Session 等）
JWT_SECRET_KEY = ...      # JWT Token 签名密钥

# 数据库连接
DB_ENGINE = django.db.backends.mysql
DB_NAME = EPP
DB_USER = ...
DB_PASSWORD = ...
DB_HOST = 127.0.0.1
DB_PORT = 3306

# AI 服务地址（本地部署的 ChatChat 服务）
REMOTE_CHAT_CHAT_PATH = http://127.0.0.1
CHAT_CHAT_MANAGER_PORT = 8001
MODEL_BASE_PORT = 7861
CHAT_GLM_PORT = 8000
GLM3_OPENAI_PORT = 20005

# 外部 API 密钥
DEEPSEEK_API_KEY = ...
TAVILY_API_KEY = ...
SIMPLIFY_TRANS_KEY = ...   # 翻译 API 密钥
CENSOR_API_KEY = ...       # 百度内容审核 API Key
CENSOR_SECRET_KEY = ...    # 百度内容审核 Secret

# MinIO 对象存储
MINIO_ENDPOINT = 127.0.0.1:9000
MINIO_ACCESS_KEY = ...
MINIO_SECRET_KEY = ...

# 管理员账号（用于初始化）
ADMIN_USERNAME = admin
ADMIN_PASSWORD = admin

# 工具路径
WKHTMLTOPDF_PATH = /usr/bin/wkhtmltopdf
```

### `Epp_BackEnd.ini` — uWSGI 生产部署配置

生产环境使用 uWSGI 作为 WSGI 服务器，通过该配置文件启动：
```bash
uwsgi --ini Epp_BackEnd.ini
```

### `.github/workflows/format-check.yaml` — CI 流水线

GitHub Actions 配置，每次 Push/PR 时自动检查代码格式（使用 `ruff` 或类似工具）。

---

## 8. 核心技术机制详解

### 8.1 认证机制（JWT）

本项目采用**无状态 JWT Token 认证**，同时保留了 Django Session（用于部分旧接口）。

**登录流程：**
1. 前端 POST `/api/login`，传入用户名和密码
2. 后端 PBKDF2 验证密码，签发 JWT Token（有效期 14 天，含 `user_id` 和 `role` 字段）
3. 前端将 Token 存储并在后续请求的 `Authorization` 请求头中携带

**鉴权流程（`authenticate_user` 装饰器）：**
```python
# 每个需要登录才能访问的接口都会加上这个装饰器
@authenticate_user
def some_protected_api(request, user: User):
    # user 是已经从数据库查询好的 User 对象
    pass
```
装饰器内部：从 `Authorization` 请求头提取 Token → 解析验证 → 查询数据库获取用户 → 将用户对象传入视图函数。

### 8.2 异步任务模式

由于 AI 推理耗时较长（数秒到数十秒），项目采用"**提交任务 → 轮询状态 → 获取结果**"的三步异步模式：

```
前端                          后端
  |                             |
  | POST /api/v2/search/query   |
  |─────────────────────────→  | 创建 SearchRecord
  |                             | 启动新线程执行检索
  | ← 200 {search_record_id}   |
  |                             |   [后台线程运行中...]
  | GET /api/v2/search/status   |   更新 VectorSearchStorage 状态
  |─────────────────────────→  |
  | ← {type: "hint", content}  |
  |                             |
  | GET /api/v2/search/status   |
  |─────────────────────────→  |
  | ← {type: "success"}        |   [后台线程完成]
  |                             |
  | GET /api/v2/search/result   |
  |─────────────────────────→  |
  | ← {paper_infos, ai_reply}  |
```

状态信息存储在 `VectorSearchStorage` / `DialogSearchStorage` 等 Model 中，实现跨线程通信。

### 8.3 AI 多智能体架构（调研助手）

`search.py` 中的 `solve_multi_agent` 函数实现了三路并行的多智能体问答：

```
用户问题
    ↓
DeepSeek R1 判断是否需要拆解子问题
    ↓
[对每个子问题]
    ↓
三路并行（ThreadPoolExecutor）
├── 原生 LLM 专家：基于本地知识库（kb_ask_ai）
├── 搜索引擎专家：Tavily 实时网络搜索
└── API 专家（local_expert_dispatch）
    ├── 学者查询 → Semantic Scholar API
    ├── 机构查询 → 机构查询 API
    └── arXiv 文献下载 → 实时构建临时知识库 → 知识库问答
    ↓
ChatGLM 整合三路结果
    ↓
最终回答（含参考文献）
```

### 8.4 向量检索（本地 FAISS）

`utils/paper_vdb_init.py` 维护了一个本地 FAISS 向量索引：
- 离线阶段：将数据库中所有论文的标题+摘要向量化（使用 sentence-transformer 类模型），保存为 `paper_index.faiss` 和 `paper_metadata.pkl`
- 在线阶段：用户查询时，将查询文本向量化，在 FAISS 中进行 Top-K 最近邻搜索，返回语义最相关的论文

### 8.5 数据库 ORM 使用

Django ORM 将 Python 操作转化为 SQL，常用模式：

```python
# 查询单条（不存在返回 None）
user = User.objects.filter(username="alice").first()

# 查询多条（带条件）
papers = Paper.objects.filter(title__icontains="deep learning").order_by("-publication_date")

# 创建并保存
paper = Paper(title="...", authors="...")
paper.save()

# 多对多关系操作
user.collected_papers.add(paper)
user.collected_papers.remove(paper)
papers = user.collected_papers.all()

# 复杂 OR 查询
from django.db.models import Q
results = Paper.objects.filter(Q(title__icontains="AI") | Q(abstract__icontains="AI"))
```

---

## 9. API 接口速查表

### 认证类
| Method | URL | 说明 | 需要登录 |
|--------|-----|------|---------|
| POST | `/api/login` | 用户登录 | 否 |
| POST | `/api/sign` | 用户注册 | 否 |
| GET | `/api/logout` | 用户登出 | 否 |
| POST | `/api/managerLogin` | 管理员登录 | 否 |
| GET | `/api/managerLogout` | 管理员登出 | 否 |

### 论文详情类
| Method | URL | 说明 | 需要登录 |
|--------|-----|------|---------|
| GET/POST | `/api/getPaperInfo` | 获取论文详情 | 否 |
| POST | `/api/userLikePaper` | 点赞/取消点赞 | 是 |
| POST | `/api/userScoring` | 给论文评分 | 是 |
| POST | `/api/collectPaper` | 收藏/取消收藏 | 是 |
| POST | `/api/commentPaper` | 发表评论 | 是 |
| GET | `/api/getComment1` | 获取一级评论 | 否 |
| GET | `/api/getComment2` | 获取二级评论 | 否 |
| POST | `/api/likeComment` | 评论点赞 | 是 |
| POST | `/api/reportComment` | 举报评论 | 是 |
| POST | `/api/batchDownload` | 批量下载论文 | 是 |

### 检索类
| Method | URL | 说明 | 需要登录 |
|--------|-----|------|---------|
| POST | `/api/v2/search/vectorQuery` | 发起向量/字符检索 | 是 |
| GET | `/api/v2/search/status` | 查询检索进度 | 是 |
| GET | `/api/v2/search/result` | 获取检索结果 | 是 |
| POST | `/api/v2/search/dialogQuery` | 发起调研助手对话 | 是 |
| GET | `/api/v2/search/dialog/status` | 查询对话进度 | 是 |
| GET | `/api/v2/search/dialog/result` | 获取对话结果 | 是 |

### 论文研读类
| Method | URL | 说明 | 需要登录 |
|--------|-----|------|---------|
| POST | `/api/study/createPaperStudy` | 创建研读会话 | 是 |
| GET | `/api/study/restorePaperStudy` | 恢复历史研读会话 | 是 |
| POST | `/api/study/doPaperStudy` | 发送研读消息 | 是 |
| GET | `/api/study/getPaperPDF` | 获取论文 PDF URL | 是 |
| DELETE | `/api/study/clearConversation` | 清空研读对话 | 是 |

### 综述生成类
| Method | URL | 说明 | 需要登录 |
|--------|-----|------|---------|
| POST | `/api/summary/generateSummaryReport` | 发起综述生成 | 是 |
| GET | `/api/v2/summary/status` | 查询生成进度 | 是 |
| POST | `/api/v2/summary/response` | 交互式综述对话 | 是 |

### 个人中心类
| Method | URL | 说明 | 需要登录 |
|--------|-----|------|---------|
| GET | `/api/userInfo/userInfo` | 获取用户信息 | 是 |
| POST | `/api/userInfo/avatar` | 修改头像 | 是 |
| GET | `/api/userInfo/collectedPapers` | 收藏的论文列表 | 是 |
| GET | `/api/userInfo/searchHistory` | 搜索历史 | 是 |
| GET | `/api/userInfo/summaryReports` | 综述报告列表 | 是 |
| GET | `/api/userInfo/notices` | 通知列表 | 是 |
| GET | `/api/userInfo/translations` | 翻译记录列表 | 是 |

---

*本文档由 Cursor AI 自动分析生成，基于项目代码截至 2026 年 3 月的状态。*
