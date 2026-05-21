"""兼容旧路径 → ``research_agent.pipelines.common``。"""
from research_agent.pipelines import common as _mod

globals().update(_mod.__dict__)
