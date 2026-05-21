"""兼容旧路径 → ``research_agent.pipelines.basic.orchestrator``。"""
from research_agent.pipelines.basic import orchestrator as _basic

globals().update(_basic.__dict__)
