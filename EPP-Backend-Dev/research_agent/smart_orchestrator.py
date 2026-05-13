"""
科研助手 Smart 编排器（与「文献研究任务」管线解耦）。

定位
----
- **深度研究编排器**（``orchestrator.execute_task_pipeline``）：六阶段检索—阅读—写作；
  仅处理用户的研究类任务，**不包含**工作区磁盘操作入口（已由顶层分流保证）。
- **Smart Planner**（``smart_planner.py``）：仅为研究任务产出 ``chat`` / ``research`` 步骤；
  与本科程模块无关。
- **Lite 编排器**（``lite_orchestrator.py``）：按 Smart Planner 步骤执行对话/浅层调研，
  **不**操作工作区文件。
- **本模块**：面向「科研助手」独立产品能力——
  普通对话可复用 Lite 链路；若策略判定需要对工作区动手，则编排 ``workspace_pipeline``。

调用约定
--------
- 工作区流水线 **不得** 由 HTTP view 直接启动；须由上层服务在落库 ``AgentTask`` 后
  显式调用 ``execute_smart_assistant_pipeline`` / ``start_smart_assistant_thread``。
- 意图分类、预检确认文案写入 ``runtime_config.workspace_preflight_summary`` 等细节：**TODO**。
"""

from __future__ import annotations

import threading
import uuid

from django.db import close_old_connections, connection


def execute_smart_assistant_pipeline(task_id: uuid.UUID) -> None:
    """
    科研助手统一编排入口（骨架）。

    预期编排骨架::
        1. 加载任务与用户最新提示词 → ``_classify_intent``（TODO）。
        2. **仅对话**：写入 ``smart_plan`` + ``lite_pipeline`` 等 runtime 标记后调用
           ``lite_orchestrator.execute_lite_pipeline``（复用现有 Lite 链路）。
        3. **仅工作区**：写入 ``workspace_pipeline``、初始化 transcript / 预检摘要后调用
           ``workspace_pipeline.execute_workspace_pipeline``。
        4. **混合**：TODO — 例如先对话再工作区，或交错多段；由上层产品定义。

    当前实现为空操作占位，待接入科研助手会话层后再串联。
    """
    close_old_connections()
    try:
        # TODO: AgentTask 加载、审计、intent 分类
        # TODO: 分支 → execute_lite_pipeline / execute_workspace_pipeline
        return
    finally:
        close_old_connections()


def start_smart_assistant_thread(task_id: uuid.UUID) -> None:
    """异步启动 Smart 编排（与 ``start_first_segment_thread`` 对称，供非研究入口使用）。"""

    if connection.vendor == "sqlite":
        execute_smart_assistant_pipeline(task_id)
        return

    def _run() -> None:
        execute_smart_assistant_pipeline(task_id)

    threading.Thread(target=_run, name=f"ra-smart-assistant-{task_id}", daemon=True).start()
