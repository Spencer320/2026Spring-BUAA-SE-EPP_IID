"""
科研助手 Agent 编排器（用户不直接调用）。

由 **basic 编排器** 在子任务 ``type=agent`` 时同步调用。通过独立的 ``WorkspaceAgentRun``
（``parent_basic_run`` 指向父 basic 运行）隔离 ``workspace_pipeline`` 的终态，避免打断父级 basic 串行循环。

子运行**持久保留**，行为审计随 ``WorkspaceAgentRun`` 保留；会话内可正常出现工作区执行说明等助手消息
（用户视角仍为单一助手，不关心内部编排）。

对外入口：:pyfunc:`run_workspace_delegate`。
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction

from research_agent.models import BasicOrchestratorRun, WorkspaceAgentRun
from research_agent.pipelines.common import runtime_config


def run_workspace_delegate(
    basic_run_id: uuid.UUID,
    *,
    delegate_prompt: str,
    prior_context: str,
) -> str:
    """
    basic 编排器委托：同步跑完工作区子运行并返回可写入 ``basic_chain_context`` 的文本。

    - 新建 ``WorkspaceAgentRun``，``parent_basic_run`` 关联父 basic 运行，持久落库；
    - ``workspace_user_query_override`` 合并委托说明与前置子任务输出；
    - 工作区管线完成时照常写入会话助手消息（用户可见执行过程摘要）。
    """
    from research_agent.pipelines.workspace.pipeline import execute_workspace_pipeline

    parent = BasicOrchestratorRun.objects.select_related("session").filter(id=basic_run_id).first()
    if parent is None:
        print(
            f"[research_agent][agent_orchestrator] parent basic run missing basic_run_id={basic_run_id}",
            flush=True,
        )
        return "（错误：父 basic 运行不存在）"

    pcfg = runtime_config(parent)
    combined = (
        f"{delegate_prompt.strip()}\n\n"
        f"--- 前置子任务结果（由 basic 编排器注入） ---\n"
        f"{prior_context.strip() or '（无）'}"
    ).strip()[:12000]

    print(
        f"[research_agent][agent_orchestrator] delegate_start basic_run_id={basic_run_id} "
        f"session_id={parent.session_id} delegate_chars={len(delegate_prompt.strip())} "
        f"prior_chars={len(prior_context.strip())} combined_chars={len(combined)}",
        flush=True,
    )

    child_cfg: dict[str, Any] = {
        "workspace_pipeline": True,
        "workspace_agent_transcript": [],
        "workspace_tool_execution_log": [],
        "workspace_user_query_override": combined,
        "risk_confirmation_strategy": str(pcfg.get("risk_confirmation_strategy") or "on_high_risk"),
    }
    ws_note = str(pcfg.get("workspace_preflight_summary") or "").strip()
    if ws_note:
        child_cfg["workspace_preflight_summary"] = ws_note[:8000]

    with transaction.atomic():
        child = WorkspaceAgentRun.objects.create(
            session=parent.session,
            parent_basic_run=parent,
            status="pending",
            steps=[],
            result_payload={"runtime_config": child_cfg},
        )
        cid = child.id

    print(
        f"[research_agent][agent_orchestrator] workspace_run_created "
        f"workspace_run_id={cid} parent_basic_run_id={basic_run_id}",
        flush=True,
    )
    execute_workspace_pipeline(cid)

    child_after = WorkspaceAgentRun.objects.filter(id=cid).first()
    if child_after is None:
        print(
            f"[research_agent][agent_orchestrator] workspace run missing after pipeline "
            f"workspace_run_id={cid}",
            flush=True,
        )
        return "（工作区子运行记录缺失）"
    if child_after.status == "completed":
        payload = child_after.result_payload if isinstance(child_after.result_payload, dict) else {}
        body = str(payload.get("body", "") or "").strip()
        print(
            f"[research_agent][agent_orchestrator] delegate_done workspace_run_id={cid} "
            f"status=completed body_chars={len(body)}",
            flush=True,
        )
        return body or "（工作区子运行已完成，无摘要正文）"
    code = str(child_after.error_code or "ERR").strip()
    msg = str(child_after.error_message or "").strip()
    print(
        f"[research_agent][agent_orchestrator] delegate_done workspace_run_id={cid} "
        f"status={child_after.status} error_code={code} error_msg={msg[:500]}",
        flush=True,
    )
    return f"（工作区子运行失败：{code} {msg}）".strip()
