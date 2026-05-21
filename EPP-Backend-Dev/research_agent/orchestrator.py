"""兼容旧路径 ``research_agent.orchestrator`` → ``research_agent.pipelines.deep.orchestrator``。"""
from research_agent.pipelines.audit import _append_behavior_log  # noqa: F401
from research_agent.pipelines.deep import orchestrator as _deep

globals().update(_deep.__dict__)
