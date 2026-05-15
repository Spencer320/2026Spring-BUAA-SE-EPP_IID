# 科研助手模块：前端 API 对接（完整版）

所有路径均相对于 Django 挂载前缀 **`/api/research-agent/`**（见项目根 `backend/urls.py` 中 `path("api/research-agent/", include("research_agent.urls"))`）。  
认证走 `research_agent.auth.authenticate_research_user`（具体 Header / Cookie 与主站一致，实现细节见 `auth.py`）。

统一 JSON 约定：

- 成功：`{"ok": true, "data": { ... }}`  
- 失败：`{"ok": false, "error": {"code": "...", "message": "..."}}`

---

## 1. 科研助手 vs 深度研究：是否分离？

**已分离。**

| 能力 | HTTP 入口 | 创建的持久化实体 | 后台入口 |
|------|------------|------------------|----------|
| 日常科研助手（对话 / 检索 / 工作区委托） | `POST /tasks/`、`POST /sessions/<id>/messages/`、`POST /sessions/messages/`（首条）、`POST /tasks/<id>/follow-up/` | `BasicOrchestratorRun` | `start_first_segment_thread` → `execute_basic_pipeline` |
| 独立深度研究 | `POST /tasks/deep-research/` | `AgentTask` | `start_deep_research_thread` → `execute_deep_research_pipeline` |

- Basic 路径**不会**在 `runtime_config` 里写 `deep_research_pipeline`；深度研究 API 会写 `deep_research_pipeline: true` 并可选写入规范化后的 `selected_papers`。  
- 同一会话**并发**限制：`views._active_task` 在 basic 与 deep 的「进行中」任务间取最新一条；若已有进行中任务，再发起任一类请求返回 **409**。  
- **说明**：仓库根路由下另有 **`/api/deep-research/...`**（`business` 包），属于另一套深度研究产品接口，与本文 `research_agent` 前缀不同；前端对接本模块时请认准 `/api/research-agent/`。

---

## 2. 路由一览（`research_agent/urls.py`）

### 2.1 会话

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/sessions/` | 分页列表 |
| POST | `/sessions/` | 新建空会话 |
| POST | `/sessions/messages/` | 新建会话并带首条用户消息 + 启动 basic 任务 |
| GET / DELETE / PATCH | `/sessions/<session_id>/` | 拉消息列表、`active_task`、`latest_task`；删会话；改标题 |
| POST | `/sessions/<session_id>/messages/` | 在已有会话发用户消息 + 启动 basic 任务 |

### 2.2 任务（含深度研究）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/tasks/` | 可带 `session_id`；否则新建会话；启动 **basic** |
| POST | `/tasks/deep-research/` | 启动 **深度研究**；`selected_papers` 非空时必须带合法 `session_id` |
| POST | `/tasks/export/` | 导出任务列表（见实现） |
| GET | `/tasks/<task_id>/` | **多态**：basic / deep / workspace 任一 UUID |
| GET | `/tasks/<task_id>/status/` | 轻量轮询进度 |
| GET | `/tasks/<task_id>/events/` | 事件流式/分页（见实现） |
| GET | `/tasks/<task_id>/report/` | 报告 JSON |
| GET | `/tasks/<task_id>/download/` | 报告 Markdown 下载 |
| POST | `/tasks/<task_id>/actions/` | 任务动作（如批准工具） |
| POST | `/tasks/<task_id>/follow-up/` | 父任务须 **completed**；新建一条 **basic** 跟进任务（不区分父任务是 deep 还是 basic） |
| POST | `/tasks/<task_id>/cancel/` | 取消 |
| POST | `/tasks/<task_id>/intervention/` | 人机干预（如 `pending_action`） |
| POST | `/tasks/<task_id>/behavior-logs/` | 行为日志上报 |

### 2.3 论文展示区（Paper shelf）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/sessions/<session_id>/paper-shelf/` | 列表（最多 500 条） |
| POST | `/sessions/<session_id>/paper-shelf/workspace/` | 把工作区文件加入展示区 |
| DELETE | `/sessions/<session_id>/paper-shelf/<item_id>/` | 删除条目 |

### 2.4 管理端（行为审计 / 站点策略）

见 `urls.py` 中 `manage/behavior-logs/`、`manage/site-access/` 等；需管理员鉴权。

---

## 3. 常用请求体字段

### 3.1 启动任务类（basic 与 deep 共用一部分）

- `content` 或 `query`：用户问题（至少其一非空，由 `_normalize_query_field` 处理）。  
- `session_id`：可选 UUID 字符串。  
- `title`：新建会话时标题。  
- `risk_confirmation_strategy`：`on_high_risk` | `always` | `never`。  
- `max_reflect_rounds`：整数 1–5（默认 2）。  
- `local_command`、`local_file_action`：可选对象（深度研究流水线里可能触发本地工具与 `pending_action`）。  
- `workspace_refs`：若请求体**包含该键**，则按 `session_context.parse_and_validate_workspace_refs` 校验（可为空数组）；用于把用户勾选的工作区文件注入本轮 runtime。

### 3.2 仅深度研究 `POST /tasks/deep-research/`

- `selected_papers`：可选数组；每项为展示区条目的 UUID 字符串，或 `{"shelf_item_id"|"item_id"|"id": "<uuid>"}`。  
- 非空 `selected_papers` 时 **必须** 提供 `session_id`。  
- 最多 **50** 条（常量 `_MAX_DEEP_RESEARCH_SELECTED_PAPERS`）。

---

## 4. 任务 JSON 中与前端强相关的字段

`GET /tasks/<id>/` 与 `GET /session/...` 内嵌的 `_task_to_json` 大致包含：

- `task_id`、`session_id`、`status`、`orchestrator`：`deep_research` | `basic` | `workspace`  
- `current_phase`、`progress`、`step_seq`、`steps`、`intervention`、`result`  
- 若 `runtime_config.workspace_fs_generation` 存在，顶层也会带 `workspace_fs_generation`（整数），用于发现工作区文件变更后轮询 `GET /api/workspace/files`。

---

## 5. 典型前端轮询建议

1. 用户发消息后拿到 `task_id`。  
2. 轮询 `GET /tasks/<task_id>/status/`（或刷新整个 `GET /sessions/<id>/` 使用其中的 `active_task`）。  
3. 若 `orchestrator` 为 `basic` 且 `workspace_fs_generation` 变化 → 调业务侧 **`GET /api/workspace/files`** 刷新树。  
4. 深度研究若 `status == pending_action` → 展示 `intervention`，用户确认后 `POST .../intervention/` 或 `actions`（以当前 `views` 实现为准，读对应 view 函数）。

---

## 6. 代码索引

- 路由：`research_agent/urls.py`  
- 视图：`research_agent/views.py`  
- 运行解析：`research_agent/run_registry.py`
