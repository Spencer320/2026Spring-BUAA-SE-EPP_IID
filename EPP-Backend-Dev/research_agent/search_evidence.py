"""兼容旧路径 → ``research_agent.pipelines.deep.evidence``。"""
from research_agent.pipelines.deep import evidence as _mod

globals().update(_mod.__dict__)
