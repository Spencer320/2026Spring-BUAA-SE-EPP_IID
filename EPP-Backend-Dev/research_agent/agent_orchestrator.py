"""兼容旧路径 → ``research_agent.pipelines.workspace.agent``。"""
from research_agent.pipelines.workspace import agent as _mod

globals().update(_mod.__dict__)
