"""按 UUID 解析会话内各类编排运行实体（深度 / basic / 工作区）。"""

from __future__ import annotations

import uuid
from typing import Literal

from .models import AgentTask, BasicOrchestratorRun, WorkspaceAgentRun

RunKind = Literal["deep_research", "basic", "workspace"]

AnyRun = AgentTask | BasicOrchestratorRun | WorkspaceAgentRun


def run_kind(run: AnyRun) -> RunKind:
    if isinstance(run, AgentTask):
        return "deep_research"
    if isinstance(run, BasicOrchestratorRun):
        return "basic"
    if isinstance(run, WorkspaceAgentRun):
        return "workspace"
    raise TypeError(type(run))


def resolve_owned_run(owner_id: str, task_id: uuid.UUID) -> AnyRun | None:
    """用户名下按 UUID 查找任一类运行（深度 / basic / 工作区），已 ``select_related('session')``。"""
    for model in (AgentTask, BasicOrchestratorRun, WorkspaceAgentRun):
        hit = (
            model.objects.filter(id=task_id, session__owner_id=owner_id)
            .select_related("session")
            .first()
        )
        if hit is not None:
            return hit
    return None


def resolve_run_by_id(task_id: uuid.UUID) -> AnyRun | None:
    """管理端等场景：不按用户过滤，仅按主键解析。"""
    for model in (AgentTask, BasicOrchestratorRun, WorkspaceAgentRun):
        hit = model.objects.filter(id=task_id).select_related("session").first()
        if hit is not None:
            return hit
    return None
