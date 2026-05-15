"""
聚合导出 ``research_agent.tools`` 常用符号；包路径 ``research_agent.tool_executor``。
"""

from __future__ import annotations

import httpx

from .tools.base import ToolAuditEvent
from .tools.local_command_executor import CommandExecutionResult, execute_controlled_local_command
from .tools.web_fetch_executor import OutboundResult, allowed_get, is_host_allowed
from .tools.web_search_executor import WebSearchResult, execute_web_search
from .tools.workspace_executor import WorkspaceActionResult, execute_workspace_action

__all__ = [
    "ToolAuditEvent",
    "OutboundResult",
    "WebSearchResult",
    "CommandExecutionResult",
    "WorkspaceActionResult",
    "allowed_get",
    "is_host_allowed",
    "execute_web_search",
    "execute_controlled_local_command",
    "execute_workspace_action",
    "httpx",
]

