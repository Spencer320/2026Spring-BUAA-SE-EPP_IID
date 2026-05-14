# Smart Planner、步间补参与 Workspace Pipeline（完整版）

本文说明 **basic 编排器** 内两段紧密配合的逻辑：`smart_planner`（首轮拆解）、`step_refill`（后续步缺参补全），以及 **`agent` 子步** 触发的 **workspace pipeline**（工作区多轮 Agent）如何运转。代码锚点以仓库当前实现为准。

---

## 一、Smart Planner：什么时候跑、做什么、怎么做

### 1.1 调用时机（仅 basic 管道）

入口：`basic_orchestrator.execute_basic_pipeline`。

在任务进入 `running` 后，若 `runtime_config` 里**还没有**可用的 `smart_plan.steps`（`_smart_steps_from_config` 为空），才会调用：

```text
detect_smart_plan(user_q, dialog_context=..., workspace_context=...)
```

也就是说：

- **每一轮新的 `BasicOrchestratorRun`** 首次进入管道时，通常都会走一遍 Smart Planner。  
- 若 `result_payload.runtime_config` 里**已经**带有完整 `smart_plan`（例如将来做断点续跑、或测试手动注入），则**跳过**规划，只恢复 `session_context_snapshot`（若缺）。

### 1.2 输入是什么

`detect_smart_plan` 接收：

1. **`user_q`**：本会话**最近一条用户消息**（`_latest_user_query`）。  
2. **`dialog_context`**：近期多轮对话摘要（不含本轮最新一句的上文），来自 `session_context_for_prompts`。  
3. **`workspace_context`**：与用户勾选的工作区引用等相关的说明文本，同样来自 `session_context_for_prompts`（与请求体里的 `workspace_refs` 经校验后进入 runtime 有关）。

这些内容拼进 `SMART_PLANNER_USER_PROMPT`，帮助模型判断要不要检索、要不要动工作区。

### 1.3 输出是什么（固定 schema）

成功时返回一个 **dict**，经 `_validate_plan` 清洗后形如：

- `summary`：短总结（最长约 300 字）。  
- `steps`：有序列表，**最多 8 步**；每步 `type` 只能是 **`chat` | `search` | `agent`** 之一，且**必须有非空 `title`**。

各步字段（校验与截断在 `smart_planner._validate_step`）：

| type | 核心执行字段 | 首轮允许「意图先行、参数留空」 |
|------|----------------|----------------------------------|
| `chat` | `prompt`（或兼容 `instruction`） | 可空；另有 `intent`、`use_history` |
| `search` | `query`（或兼容 `goal`） | **可空**，文档约定由步间补全 |
| `agent` | `delegate_prompt`（或兼容 `prompt`） | **可空**，文档约定由步间补全 |

另有可选：`post_write_path`（search 步）、统一从 `intent` / `action_summary` 推导的 `intent` 等。

### 1.4 怎么做（LLM + 校验）

1. 调用 `chat_completion`（温度 0.1，`max_tokens=1100`，非流式）。  
2. 用 `normalize_supplier_json_response` 解析 JSON；非法或供应商包装兜底则放弃。  
3. `_validate_plan`：结构不对、步骤类型非法、`title` 为空、或某步校验失败 → 整份计划作废，返回 `None`。  
4. 调用方若得到 `None`，使用 **`fallback_chat_plan(user_q)`**：退化为**单步 `chat`**，把整段用户文本塞进 `prompt`。

规划结果写入 `runtime_config`：

- `smart_plan`：上一步得到的 plan。  
- `smart_plan_next_index=0`。  
- `basic_chain_context=""`，`basic_step_outputs` 随后每步追加。  
- `session_context_snapshot`：供后续步间补参 LLM 使用的会话快照字符串。

同时在 `task.steps` 里追加一条「Smart Planner 拆解」或「Smart Planner 回退」的 `plan` 阶段记录。

---

## 二、后续空缺参数怎么填（step_refill）

### 2.1 何时触发「步间补参」

在 `execute_basic_pipeline` 的主循环里，对**即将执行**的下标为 `next_index` 的那一步：

- 仅当 **`next_index >= 1`（从第二步起）** 且 `step_refill.step_needs_param_refill(next_index, step)` 为真时才跑补参。  
- 判定规则：  
  - `search`：`query` 全空白才需要；  
  - `agent`：`delegate_prompt` 全空白才需要；  
  - `chat`：`prompt` 全空白才需要。

**第一步（index 0）** 不会走 `step_refill`。此时若 `query` / `delegate_prompt` / `prompt` 仍为空，由各执行器**自己的兜底**处理：

- **search**：`_execute_search_step` 若 `query` 仍空，会退回 `_latest_user_query(task)`。  
- **agent**：`delegate_prompt` 若仍空，`run_workspace_delegate` 处会用 **`delegate or user_query`**，即用户整句。  
- **chat**：`_execute_chat_step` 在 prompt 为空时，用户提示模板里会写明「规划者未提供具体指令…」，让模型直接基于原始请求与前置上下文回复。

### 2.2 补参怎么做（LLM + 规则兜底）

函数：`step_refill.fill_deferred_step_params(...)`。

**输入上下文**（全部截断后塞进 `STEP_REFILL_USER_PROMPT`）包括：

- 原始 `user_query`；  
- `session_context`：即本轮保存的 `session_context_snapshot`；  
- `prior_chain`：当前 `basic_chain_context`（前面各步标题 + 正文拼接）；  
- 上一步的 `last_step_type` / `last_step_title` / `last_output`；  
- 当前待补步的 `type`、`title`、`intent` 及紧凑 JSON。

**流程**：

1. 再调一次 `chat_completion`（温度 0.15，`max_tokens=900`）。  
2. 解析 JSON 后，用 `_pick_refill_keys` 只取出与本步类型相关的键：`query` / `delegate_prompt` / `prompt`。  
3. 若 LLM 失败、解析失败或取出字段仍为空 → **`rule_based_fill_step`**：  
   - `search`：`query = intent`（或 title）；  
   - `agent`：生成固定句式「请结合前置子任务结果…完成意图…」+ `intent`；  
   - `chat`：`prompt = intent`。

随后 `merge_refill_into_step` 合并回该步；若合并后仍缺（例如 LLM 给了空串），会再合并一次纯规则结果。

补全后会写回 `runtime_config.smart_plan.steps[next_index]`，并在 `task.steps` 追加「子任务参数补全」记录。

---

## 三、Agent 编排器与 Workspace Pipeline：具体怎么工作

### 3.1 在 basic 里处于哪一环

当 `smart_plan` 某步 `type == "agent"` 时，`basic_orchestrator` **同步**调用：

```text
run_workspace_delegate(task_id, delegate_prompt=..., prior_context=...)
```

其中：

- `delegate_prompt`：补参后的委托说明；若仍为空则用用户整句。  
- `prior_context`：默认是 `basic_chain_context`；若存在 `session_context_snapshot`，会包一层「会话上下文 + 本 basic run 内已完成子任务」再传入。

**不会**为工作区子运行单独开一个用户 HTTP；子运行由 `agent_orchestrator` 建库后立刻 `execute_workspace_pipeline`。

### 3.2 `run_workspace_delegate` 做什么

1. 读父 `BasicOrchestratorRun` 的 `runtime_config`（风险策略、可选 `workspace_preflight_summary`）。  
2. 组装 **`workspace_user_query_override`**：`delegate_prompt` +「前置子任务结果」块（长度上限约 12000 字符）。  
3. `transaction` 内 `WorkspaceAgentRun.objects.create(...)`，`parent_basic_run` 指向父 basic，`runtime_config` 带上 `workspace_pipeline=True`、`workspace_agent_transcript`、`workspace_tool_execution_log` 等初始容器。  
4. **同步**调用 `execute_workspace_pipeline(child_id)`。  
5. 子运行 `completed` 时取 `result_payload.body` 作为字符串返回给 basic；basic 把它当作本步输出，追加进 `basic_chain_context` 与 `basic_step_outputs`，并推进 `smart_plan_next_index`。

### 3.3 `execute_workspace_pipeline` 主循环

常量：**每轮一次规划 LLM**，最多 **`WORKSPACE_AGENT_MAX_TURNS`（24）** 轮。

每轮大致顺序：

1. **读状态**：`transcript`（字符串列表，模型可见历史）、`workspace_tool_execution_log`、用户侧「规划输入」来自 **`_workspace_user_query_for_task`**：优先 `workspace_user_query_override`（basic 委托），否则会话最近一条用户消息。  
2. **拼提示**：系统/用户提示来自 `WORKSPACE_AGENT_LOOP_*`；用户块内含 **工具目录 Markdown**（`format_tools_catalog_markdown()`）、`query`、`execution_context`（如 `workspace_preflight_summary`，否则一段开发期说明）、当前 `transcript` 文本。  
3. **规划 LLM**：非流式 JSON；解析失败或 HTTP 失败 → 子任务 `failed`，写入错误码。  
4. **解析决策 JSON**，期望字段：  
   - `finished`（bool）：为真则进入收尾；  
   - `assistant_message`（str）：给用户看的说明；  
   - `tool_calls`（list[dict]）：本批要执行的工作区动作。  
5. **若 `finished`**：  
   - `body = assistant_message` + 可选附录（把 `workspace_tool_execution_log` 渲染成「已执行工作区工具」Markdown）；  
   - 写入子运行 `result_payload`（含 `body`、`pipeline` 等），`status=completed`；  
   - **若存在 `parent_basic_run_id`**：**不再**单独 `ResearchMessage.create`（避免与 basic 汇总消息重复）；**独立**工作区运行（无父）则会写一条助手消息。  
6. **若未 `finished` 且无 `tool_calls`**：向 `transcript` 追加一条说明「模型未给 tool_calls」，**继续下一轮**（避免死锁）。  
7. **若有 `tool_calls`**：调用 `run_llm_workspace_tool_batch`（内部 `adapt_llm_workspace_call` → `execute_workspace_action`），顺序执行；结果文本拼进 `transcript`，结构化记录 append 到 `workspace_tool_execution_log`；**`workspace_fs_generation` 自增**；若有父 basic，则 **`_bump_parent_basic_workspace_fs_generation`**，便于前端轮询父任务 status 后刷新 `/api/workspace/files`。  
8. 工具批次可打行为审计（`_emit_tool_batch_audit`）；规划 LLM 打 `_emit_plan_audit`。  
9. 轮次用尽仍未 `finished` → `failed`，错误码 `WS_AGENT_MAX_TURNS`。

### 3.4 与 Smart Planner / step_refill 的关系（一句话）

- **Smart Planner** 决定「这一轮用户请求要不要走 `agent` 步、顺序如何」。  
- **step_refill** 在**第二步及以后**把 `agent` 步缺的 `delegate_prompt` 写具体，避免工作区子 Agent 只看到空指令。  
- **Workspace pipeline** 不关心 `smart_plan`；它只消费 **`workspace_user_query_override`**（由 delegate + 前置链构成）和 **transcript / 工具表**，在多轮里直到模型声明结束或报错/触顶。

---

## 四、代码索引

| 主题 | 文件与符号 |
|------|------------|
| Smart Planner | `smart_planner.py`：`detect_smart_plan`、`fallback_chat_plan`、`_validate_plan` |
| 步间补参 | `step_refill.py`：`step_needs_param_refill`、`fill_deferred_step_params`、`rule_based_fill_step` |
| basic 主循环 | `basic_orchestrator.py`：`execute_basic_pipeline`、`_execute_*_step` |
| 委托入口 | `agent_orchestrator.py`：`run_workspace_delegate` |
| 工作区循环 | `workspace_pipeline.py`：`execute_workspace_pipeline` |
| 工具目录与批次 | `tools/workspace_agent_tools.py`：`format_tools_catalog_markdown`、`run_llm_workspace_tool_batch` |
