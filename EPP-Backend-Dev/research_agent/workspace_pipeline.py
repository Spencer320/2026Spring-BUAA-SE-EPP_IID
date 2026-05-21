"""兼容旧路径 → ``research_agent.pipelines.workspace.pipeline``。"""
from research_agent.pipelines.workspace import pipeline as _mod

globals().update(_mod.__dict__)
