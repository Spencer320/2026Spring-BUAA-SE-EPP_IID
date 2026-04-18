# Deep Research 主模块对接说明

> **文档对象**：负责实现 Deep Research 编排器与用户端接口的同学  
> **文档目的**：介绍已就绪的数据模型、工具函数和存根接口，明确 DR 主模块需要填充的内容  
> **相关文件**：
> - 模型：`business/models/deep_research_task.py`  
> - 用户端接口存根：`business/api/deep_research.py`（顶部用户端部分）  
> - 限频工具：`business/utils/rate_limit.py`  
> - 概要设计：`Deep-Research-概要设计.md`

---

## 1. 已就绪的基础设施

### 1.1 数据模型（已定义，可直接 ORM 操作）

三张表已定义在 `business/models/deep_research_task.py`，执行 `python manage.py makemigrations && python manage.py migrate` 后即可使用。

#### `DeepResearchTask`（任务主表）

```python
from business.models import DeepResearchTask
```

**你需要关注的字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | UUIDField (PK) | 自动生成，创建任务后返回给前端 |
| `user` | FK → User | 任务归属用户 |
| `file_reading` | FK → FileReading (null) | 关联的论文研读会话，可为空 |
| `query` | TextField | 用户输入的研究问题 |
| `max_rounds` | IntegerField | 最大迭代轮数，默认 3 |
| `status` | CharField | 任务状态，使用类常量赋值（见下） |
| `current_phase` | CharField | 当前执行阶段，使用类常量赋值 |
| `progress` | IntegerField | 进度 0~100 |
| `step_summary` | CharField(512) | 最新步骤摘要（轮询时展示给用户） |
| `token_used_total` | IntegerField | 累计消耗 Token，每步累加 |
| `report` | JSONField (null) | 最终结构化报告 |
| `citation_coverage` | FloatField (null) | 循证覆盖率 0.0~1.0 |
| `error_message` | TextField | 失败时的错误信息 |
| `started_at` | DateTimeField (null) | 编排器开始时填写 |
| `finished_at` | DateTimeField (null) | 终态时填写 |
| `admin_stop_flag` | BooleanField | **管理员强制中断信号**，编排器每轮必须检查 |
| `output_suppressed` | BooleanField | 由管理端控制，不影响编排器逻辑 |

**状态常量（`DeepResearchTask.STATUS_*`）：**

```python
DeepResearchTask.STATUS_PENDING        = "pending"
DeepResearchTask.STATUS_QUEUED         = "queued"
DeepResearchTask.STATUS_RUNNING        = "running"
DeepResearchTask.STATUS_COMPLETED      = "completed"
DeepResearchTask.STATUS_FAILED         = "failed"
DeepResearchTask.STATUS_ABORTED        = "aborted"
DeepResearchTask.STATUS_ADMIN_STOPPED  = "admin_stopped"
```

**阶段常量（`DeepResearchTask.PHASE_*`）：**

```python
DeepResearchTask.PHASE_PLANNING    = "planning"
DeepResearchTask.PHASE_SEARCHING   = "searching"
DeepResearchTask.PHASE_READING     = "reading"
DeepResearchTask.PHASE_REFLECTING  = "reflecting"
DeepResearchTask.PHASE_WRITING     = "writing"
```

---

#### `DeepResearchStep`（执行步骤表）

```python
from business.models import DeepResearchStep
```

编排器每完成一个具体动作，调用一次 `create`：

```python
DeepResearchStep.objects.create(
    task=task,
    seq=step_counter,          # 从 1 递增
    phase=DeepResearchTask.PHASE_SEARCHING,
    action="检索 arXiv",
    summary="查询关键词 'Transformer medical imaging'，获得 15 篇候选",
    token_used=0,
)
```

`summary` 可存放截断后的 LLM 输出（建议 ≤ 500 字），`token_used` 记录本步骤消耗。

---

#### `DeepResearchAuditLog`

由管理端接口自动写入，**编排器无需处理**。

---

### 1.2 用户端接口存根

`business/api/deep_research.py` 顶部已定义 7 个用户端函数，路由已在 `backend/urls.py` 注册完毕：

| 函数名 | 路由 | 当前状态 |
|--------|------|---------|
| `user_create_task` | POST `/api/deep-research/tasks` | **需实现** |
| `user_task_status` | GET `/api/deep-research/tasks/<id>/status` | 已实现（直接读 DB） |
| `user_task_events` | GET `/api/deep-research/tasks/<id>/events` | 已实现（读 Step 增量） |
| `user_task_report` | GET `/api/deep-research/tasks/<id>/report` | 已实现（含屏蔽检查） |
| `user_abort_task` | POST `/api/deep-research/tasks/<id>/abort` | 已实现（直接写状态） |
| `user_follow_up` | POST `/api/deep-research/tasks/<id>/follow-up` | **需实现** |
| `user_export_tasks` | POST `/api/deep-research/tasks/export` | **需实现** |

你只需要在 `deep_research.py` 中填充 `user_create_task`、`user_follow_up`、`user_export_tasks` 的具体逻辑，其他接口已可用。

---

## 2. 编排器必须遵守的约定

### 2.1 创建任务时调用限频检查

在 `user_create_task` 视图中，**创建任务前必须先调用限频检查**：

```python
from business.utils.rate_limit import check_rate_limit
from business.utils.response import fail

@authenticate_user
@require_http_methods(["POST"])
def user_create_task(request, user):
    # ① 限频检查（必须在任务创建前调用）
    allowed, msg = check_rate_limit(
        user,
        "deep_research",
        ip_address=request.META.get("REMOTE_ADDR"),
        extra={},           # 此时 task_id 还未生成，可留空
    )
    if not allowed:
        return fail({"error": msg})

    # ② 解析参数
    body = json.loads(request.body)
    query = body.get("query", "").strip()
    if not query:
        return fail({"error": "研究问题不能为空"})

    # ③ 创建任务记录
    task = DeepResearchTask.objects.create(
        user=user,
        file_reading_id=body.get("file_reading_id"),
        query=query,
        max_rounds=body.get("max_rounds", 3),
        status=DeepResearchTask.STATUS_PENDING,
    )

    # ④ 启动编排器线程
    import threading
    t = threading.Thread(target=run_orchestrator, args=(task.task_id,), daemon=True)
    t.start()

    return ok({"task_id": str(task.task_id), "status": task.status})
```

> `check_rate_limit` 内部已异步写入日志，调用方无需手动处理日志。

---

### 2.2 编排器循环内必须检查 `admin_stop_flag`

```python
def run_orchestrator(task_id):
    task = DeepResearchTask.objects.get(task_id=task_id)
    task.status = DeepResearchTask.STATUS_RUNNING
    task.started_at = timezone.now()
    task.save(update_fields=["status", "started_at"])

    step_counter = 0

    for round_idx in range(task.max_rounds):
        # ── 每轮开始前检查管理员中断信号 ──────────────────────────
        task.refresh_from_db(fields=["admin_stop_flag"])
        if task.admin_stop_flag:
            task.status = DeepResearchTask.STATUS_ADMIN_STOPPED
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "finished_at"])
            return  # 安全退出，释放所有资源
        # ──────────────────────────────────────────────────────────

        # 规划阶段
        task.current_phase = DeepResearchTask.PHASE_PLANNING
        task.step_summary = "正在规划子问题..."
        task.save(update_fields=["current_phase", "step_summary"])

        step_counter += 1
        DeepResearchStep.objects.create(
            task=task, seq=step_counter,
            phase=DeepResearchTask.PHASE_PLANNING,
            action="LLM 分解子问题",
            summary="...",
            token_used=860,
        )
        task.token_used_total += 860
        task.save(update_fields=["token_used_total"])

        # ... 检索、阅读、反思阶段（每阶段前都建议检查一次 admin_stop_flag）

    # 生成报告
    task.report = {"sections": [...]}
    task.citation_coverage = 0.85
    task.status = DeepResearchTask.STATUS_COMPLETED
    task.finished_at = timezone.now()
    task.progress = 100
    task.save(update_fields=["report", "citation_coverage", "status", "finished_at", "progress"])
```

**关键点：**
- `refresh_from_db(fields=["admin_stop_flag"])` 每轮只刷新这一个字段，开销极小
- 检测到中断后立即 `return`，不要再写任何步骤
- 状态必须更新为 `STATUS_ADMIN_STOPPED`，管理端监控依赖此状态

---

### 2.3 失败处理

```python
try:
    # 编排逻辑
    ...
except Exception as e:
    task.status = DeepResearchTask.STATUS_FAILED
    task.error_message = str(e)
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "error_message", "finished_at"])
```

---

### 2.4 进度更新建议

每个阶段切换时更新 `current_phase`、`progress`、`step_summary`，供前端轮询展示：

| 阶段 | 建议 progress |
|------|-------------|
| planning | 10 |
| searching（每轮） | 20~40 |
| reading（每轮） | 40~60 |
| reflecting（每轮） | 60~75 |
| writing | 80~99 |
| 完成 | 100 |

---

## 3. 与管理端的接口边界

管理端接口已完整实现，编排器**无需调用**任何管理端接口，双方通过数据库字段通信：

```
管理员操作                    编排器感知
─────────────────────────────────────────────────────
POST .../force-stop       →  admin_stop_flag = True
                              编排器下轮 refresh_from_db 后检测并停止

POST .../suppress-output  →  output_suppressed = True
                              仅影响用户端 GET report 接口，编排器无感知

GET .../trace             →  读取 DeepResearchStep 表
                              编排器写 Step 越详细，轨迹越清晰
```

---

## 4. 快速验证清单

实现完 `user_create_task` 后，可通过以下步骤验证管理端联通：

1. 用普通用户 Token 调用 `POST /api/deep-research/tasks`，拿到 `task_id`
2. 用管理员 Token 调用 `GET /api/manage/deep-research/tasks`，确认任务出现在列表中
3. 调用 `GET /api/manage/deep-research/stats`，确认 `running_count` 正确
4. 对运行中任务调用 `POST /api/manage/deep-research/tasks/<id>/force-stop`
5. 编排器感知到中断后，再次调用 `GET /api/manage/deep-research/tasks/<id>`，
   确认 `status` 变为 `admin_stopped`
6. 调用 `GET /api/manage/deep-research/tasks/<id>/audit-logs`，
   确认 `force_stop` 日志已写入

---

## 5. 常见问题

**Q: `check_rate_limit` 返回 False，但我想在创建时绕过限频（比如测试用）？**  
A: 管理端为测试用户设置 `UserAccessQuotaOverride.max_count = -1` 即可，无需修改代码。

**Q: 编排器线程崩溃后任务状态卡在 `running`，怎么处理？**  
A: 建议在编排器最外层加 `try/except`，catch 所有异常后将状态置为 `failed`。
管理端也可通过 `force-stop` 接口手动将状态更正（force-stop 会置 `admin_stop_flag`，
但若线程已死，可直接在 DB 中更新状态，或后续加定时任务扫描超时任务）。

**Q: `DeepResearchStep.summary` 可以存完整 LLM 输出吗？**  
A: 建议截断到 500 字以内（字段 `TextField` 无硬限制，但管理端轨迹页面会完整展示，
过长影响体验）。完整输出可存入 `report` JSON 的对应步骤节点中。

**Q: 我需要在编排器中也写入 `FeatureAccessLog` 吗？**  
A: 不需要。`check_rate_limit` 已在创建任务时异步写入一条 `allowed` 日志，
编排器只需专注更新 `DeepResearchTask` 和写 `DeepResearchStep`。
