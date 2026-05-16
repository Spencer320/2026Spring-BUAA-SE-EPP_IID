# FR-KYZS-0007 高风险动作人工干预删除说明

## 修改目标

根据需求调整，删除“3.8.7 功能 7：高风险动作人工干预（FR-KYZS-0007）”的运行链路。删除后，科研智能助手不再在高风险动作前挂起任务，也不再向前端弹出“允许执行 / 终止任务 / 修改要求并继续”的人工确认卡片。

## 修改范围

### 后端接口

- `EPP-Backend-Dev/research_agent/views.py`
  - 删除人工确认通过后继续执行的审批标记逻辑。
  - 删除 `approve` / `revise` 后重启任务线程的处理。
  - 保留旧接口路径，但 `/intervention/` 与 `actions` 中的 `allow` / `revise` 返回 `410 FEATURE_REMOVED`，避免旧前端或旧调用方误以为任务仍可人工确认。
  - `abort` 仍保留为取消任务能力，不影响用户主动终止任务。

### 后端编排

- `EPP-Backend-Dev/research_agent/orchestrator.py`
  - 删除本地命令、本地文件、工作区动作中的“批准后跳过确认”状态记录。
  - 工具调用统一使用 `risk_confirmation_strategy="never"`。
  - 如果旧逻辑或旧数据意外返回 `requires_confirmation=True`，任务直接失败为 `FEATURE_REMOVED`，不再进入 `pending_action`。

- `EPP-Backend-Dev/research_agent/agent_orchestrator.py`
  - 工作区子任务不再继承旧的人工确认策略，统一使用 `risk_confirmation_strategy="never"`。

- `EPP-Backend-Dev/research_agent/workspace_pipeline.py`
  - 工作区工具批次执行不再触发人工确认挂起。
  - 工具执行过程保留审计记录和错误返回，但不再等待用户确认后恢复。

### 后端工具

- `EPP-Backend-Dev/research_agent/tools/local_command_executor.py`
  - 删除高风险命令模板触发人工确认的返回分支。
  - 白名单内命令直接执行；非白名单命令仍直接拒绝。

- `EPP-Backend-Dev/research_agent/tools/local_file_executor.py`
  - 删除高风险本地文件动作触发人工确认的返回分支。
  - 未授权动作直接拒绝。

- `EPP-Backend-Dev/research_agent/tools/workspace_executor.py`
  - 删除工作区高风险动作的人工确认返回分支。
  - 高风险动作按既有权限边界和新版工作区工具语义直接执行或失败。
  - 覆盖、删除、解压等场景不再挂起等待确认。

### 提示词

- `EPP-Backend-Dev/research_agent/prompts.py`
  - 更新工作区动作提示词：不再告诉模型“高风险动作会由后端拦截并请求用户确认”。
  - 改为说明越权、冲突或参数非法会直接返回错误。

### 前端

- `EPP-Frontend-Dev/src/views/ResearchAgent/ResearchAgentSession.vue`
  - 删除人工确认卡片 UI。
  - 删除“允许执行 / 终止任务 / 修改要求并继续”的提交逻辑。
  - 对旧 `pending_action` 数据仅作为停用状态展示，不再提供继续确认入口。

- `EPP-Frontend-Dev/src/views/ResearchAgent/researchAgentApi.js`
  - 删除 `postIntervention` 调用封装。

### 测试

- `EPP-Backend-Dev/research_agent/tests/test_api.py`
  - 将干预接口测试更新为验证 `410 FEATURE_REMOVED`。

- `EPP-Backend-Dev/research_agent/tests/test_local_file_executor.py`
  - 更新本地文件动作测试：不再期待人工确认。

- `EPP-Backend-Dev/research_agent/tests/test_state_machine.py`
  - 删除依赖 `pending_action` 与 approve 恢复流程的状态机测试。

- `EPP-Backend-Dev/research_agent/tests/test_tool_executor.py`
  - 更新本地命令测试：高风险模板不再等待人工确认。

## 未修改内容

- 未删除用户主动取消任务能力。
- 未删除工具白名单、路径安全校验、站点访问策略、动作合法性校验。
- 未提交本地运行配置、API key、环境目录、admin 登录修复或启动指南。
- 未提交科研助手 ModelArts 流式请求兼容修改；该修改属于运行环境兼容问题，不属于 FR-KYZS-0007 删除范围。

## 建议验证

```powershell
cd EPP-Backend-Dev
.\.conda-py312\python.exe manage.py check
.\.conda-py312\python.exe manage.py test research_agent
```

前端验证建议：

1. 打开用户端科研助手页面。
2. 执行普通对话任务，确认不会出现人工确认卡片。
3. 执行涉及工作区文件操作的任务，确认不会进入人工确认挂起状态。
4. 调用旧 `/api/research-agent/tasks/<task_id>/intervention/` 接口时应返回 `410 FEATURE_REMOVED`。
