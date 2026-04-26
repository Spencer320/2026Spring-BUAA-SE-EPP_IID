# 科研助手执行引擎架构、数据模型与 API 契约草案（P0）

## 1. 文档目标与边界
- 目标：输出可直接指导开发的执行引擎设计、数据模型草案与接口契约草案，支撑 `P0` 用户侧闭环交付。
- 覆盖范围：任务创建、执行主循环、实时状态、人工干预、报告查询/导出、追问继续执行。
- 边界约束：管理端不在本轮实现，仅预留接口与事件字段兼容能力。

## 2. 执行引擎架构草案

### 2.1 组件划分
- `TaskIngress`：任务入口与参数校验，负责限频/配额校验、任务初始化。
- `TaskPlanner`：问题拆解与阶段计划生成。
- `ToolRouter`：按任务类型路由到联网搜索、本地命令、RAG、重排等工具。
- `StateMachine`：驱动 `planning -> searching -> reading -> reflecting -> writing`。
- `Observer`：收集工具结果、风险判定、成本统计与异常信息。
- `DecisionLoop`：根据观察结果决定继续、重试、降级、人工确认或终止。
- `ReportBuilder`：聚合结论、引用与附加产物，生成报告与导出结构。
- `ProgressAuditStream`：向前端输出步骤流，并写入审计事件。

### 2.2 核心状态机
- 任务状态：`pending -> queued -> running -> completed | failed | aborted`。
- 阶段状态：`planning -> searching -> reading -> reflecting -> writing`。
- 干预状态：`pending_action`（等待用户确认）为挂起子状态，可回到 `running`。
- 终态收敛规则：
  - 成功完成写作并产出报告：`completed`；
  - 不可恢复异常或重试耗尽：`failed`；
  - 用户主动终止：`aborted`。

### 2.3 执行循环协议
1. 初始化任务上下文（用户输入、预算、风险策略、模型路由配置）。
2. 进入当前阶段并写入阶段开始事件。
3. 调用工具/模型并接收结构化结果。
4. 经过观察器判定：质量、可信度、风险、成本。
5. 决策器输出下一个动作：
   - `proceed`：进入下一阶段；
   - `retry`：阶段内重试（受重试上限限制）；
   - `degrade`：模型/工具降级；
   - `ask_human`：挂起到 `pending_action`；
   - `abort`：终止任务。
6. 记录步骤结果、token、引用和事件，再进入下一轮。
7.  输出协议：所有的AI生成内容都会有具体的json返回格式需求

### 2.4 重试与恢复策略
- 阶段内重试：同类错误有限重试（如超时、暂时不可用）。
- 跨模型降级：主模型失败后按分层路由回退。
- 工具降级：外部检索失败时回退到替代来源或本地 RAG。
- 恢复执行：人工确认后，从挂起阶段继续，不回滚已完成步骤。
- 反思轮次上限：每个任务必须配置 `max_reflect_rounds`，达到上限后即使仍返回 `yes` 也必须收敛到写作或失败终态。

### 2.5 人工干预点（用户侧）
- 高风险命令执行前。
- 高风险外部来源访问前（命中策略时）。
- 关键结论冲突且无法自动裁决时（可选）。
- 用户动作：
  - `allow`：放行当前动作；
  - `revise`：修订参数后再评估；
  - `abort`：终止任务。

## 3. 数据模型变更草案

### 3.1 `DeepResearchTask`（任务主表）
- 主键：`task_id`（UUID）
- 归属：`user_id`、`file_reading_id`（可空）
- 输入与配置：
  - `query`、`mode`、`image_enabled`、`risk_policy`、`max_rounds`
  - `max_reflect_rounds`（反思最大轮数）
- 运行态：
  - `status`、`current_phase`、`progress`、`step_summary`
  - `token_used_total`、`tool_calls_total`、`retry_count_total`
- 结果态：
  - `report`（JSON）、`citation_coverage`、`attachments`（JSON，可含图像产物）
- 异常与控制：
  - `error_code`、`error_message`
  - `pending_action`（bool）、`pending_action_payload`（JSON）
  - `admin_stop_flag`（预留）、`output_suppressed`（预留）
- 时间戳：
  - `created_at`、`started_at`、`finished_at`、`updated_at`

### 3.2 `DeepResearchStep`（步骤表）
- 关联：`task_id` + `seq`（联合唯一）
- 基础字段：
  - `phase`、`action`、`summary`、`status`
  - `input_snapshot`（脱敏）、`output_snapshot`（截断）
- 资源与质量：
  - `token_used`、`latency_ms`、`confidence`
- 溯源字段：
  - `citations`（JSON：来源 URL、文献 ID、证据片段）
- 失败信息：
  - `error_code`、`error_message`
- 时间字段：`created_at`

### 3.3 `ToolAuditEvent`（工具调用审计表）
- 主键与链路：`event_id`、`task_id`、`step_id`、`trace_id`
- 调用信息：
  - `tool_type`（web_search/local_command/rag/reranker/image_gen）
  - `action`、`risk_level`、`rule_hit`
- 请求响应：
  - `request_payload`（脱敏）、
  - `response_summary`、`status`
- 资源统计：
  - `latency_ms`、`token_used`、`output_truncated`
- 错误信息：`error_code`、`error_message`
- 时间字段：`created_at`

### 3.4 `TaskResourceUsage`（资源消耗统计表，可选）
- 粒度：按任务、按阶段聚合
- 字段：`task_id`、`phase`、`token_used`、`tool_call_count`、`duration_ms`、`created_at`
- 用途：成本分析、阈值策略评估、后续管理端统计兼容。

## 4. 接口契约草案（用户侧）

### 4.1 创建任务
- `POST /api/deep-research/tasks`
- 请求体：
  - `query`（string, required）
  - `mode`（string, optional, default=`standard`）
  - `image_enabled`（boolean, optional, default=false）
  - `risk_policy`（string, optional, default=`strict`）
  - `max_rounds`（int, optional, default=3）
  - `max_reflect_rounds`（int, optional, default=2）
  - `file_reading_id`（string, optional）
- 成功响应：
  - `task_id`、`status`、`current_phase`、`progress`
- 失败响应：
  - 参数错误、限频超限、配额不足、策略拦截。

### 4.2 查询任务状态
- `GET /api/deep-research/tasks/{task_id}/status`
- 响应字段：
  - `task_id`、`status`、`current_phase`、`progress`、`step_summary`
  - `token_used_total`、`pending_action`、`updated_at`

### 4.3 查询任务事件流（增量）
- `GET /api/deep-research/tasks/{task_id}/events?since_seq={n}`
- 响应字段：
  - `task_id`、`next_seq`、`has_more`
  - `events[]`（`seq`、`phase`、`type`、`summary`、`created_at`）

### 4.4 用户人工干预动作
- `POST /api/deep-research/tasks/{task_id}/actions`
- 请求体：
  - `action`：`allow | revise | abort`
  - `payload`：当 `revise` 时提供修订参数
- 响应字段：
  - `task_id`、`status`、`pending_action`、`message`

### 4.5 查询报告
- `GET /api/deep-research/tasks/{task_id}/report`
- 响应字段：
  - `task_id`、`status`、`report`
  - `citation_coverage`、`attachments`
- 约束：
  - 若 `output_suppressed=true`（管理端预留控制位），返回受控错误。

### 4.6 继续追问
- `POST /api/deep-research/tasks/{task_id}/follow-up`
- 请求体：
  - `query`（string, required）
  - `mode`、`image_enabled`（optional）
- 响应字段：
  - `task_id`（可沿用原任务或返回子任务 ID）
  - `status`、`message`

### 4.7 导出任务报告
- `POST /api/deep-research/tasks/export`
- 请求体：
  - `task_ids`（string[]）
  - `format`（`markdown | json`）
- 响应字段：
  - `export_id`、`download_url` 或同步 `content`

## 5. 管理端接口预留（仅契约，不实现）

### 5.1 预留接口清单
- `GET /api/manage/deep-research/tasks`
- `GET /api/manage/deep-research/tasks/{task_id}`
- `GET /api/manage/deep-research/tasks/{task_id}/trace`
- `POST /api/manage/deep-research/tasks/{task_id}/force-stop`
- `POST /api/manage/deep-research/tasks/{task_id}/suppress-output`
- `GET /api/manage/deep-research/stats`

### 5.2 用户侧需兼容的预留字段
- 任务主表字段预留：
  - `admin_stop_flag`：供执行循环周期检查；
  - `output_suppressed`：供报告查询接口拦截；
  - `admin_last_action`（可选）：记录最近管理动作摘要。
- 事件流字段预留：
  - `operator_type`（user/system/admin）
  - `control_signal`（force_stop/suppress_output）

## 6. 错误码与响应约定
- 统一返回结构：
  - 成功：`{"ok": true, "data": ...}`
  - 失败：`{"ok": false, "error": {"code": "...", "message": "...", "details": ...}}`
- 推荐错误码：
  - `INVALID_PARAM`
  - `RATE_LIMIT_EXCEEDED`
  - `QUOTA_EXCEEDED`
  - `TASK_NOT_FOUND`
  - `TASK_FORBIDDEN`
  - `TASK_NOT_ACTIONABLE`
  - `RISK_BLOCKED`
  - `TOOL_TIMEOUT`
  - `INTERNAL_ERROR`

## 7. 验收用例映射（P0）
- 创建任务：合法参数成功、非法参数失败、限频失败可解释。
- 执行闭环：阶段推进完整，步骤记录与状态一致。
- 人工干预：`allow/revise/abort` 行为生效且状态正确。
- 报告与导出：可查询、可下载、引用可追溯。
- 异常路径：超时、策略拦截、资源超预算时可降级或可解释失败。
- 预留兼容：管理端预留字段存在但不影响用户侧主流程。

## 8. 与实施计划对齐
- 对齐阶段 D：覆盖执行引擎设计、数据模型变更草案、接口契约草案。
- 对齐阶段 E/F：文档字段与流程可直接拆解为开发任务与测试用例。
