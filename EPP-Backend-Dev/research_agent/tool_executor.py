"""
兼容层：对外保留 research_agent.tool_executor 旧导出。
新实现位于 research_agent.tools 子模块。
"""

from __future__ import annotations

import httpx

from .tools.base import ToolAuditEvent
from .tools.local_command_executor import CommandExecutionResult, execute_controlled_local_command
from .tools.web_fetch_executor import OutboundResult, allowed_get, is_host_allowed
from .tools.web_search_executor import WebSearchResult, execute_web_search

__all__ = [
    "ToolAuditEvent",
    "OutboundResult",
    "WebSearchResult",
    "CommandExecutionResult",
    "allowed_get",
    "is_host_allowed",
    "execute_web_search",
    "execute_controlled_local_command",
    "httpx",
]

