"""兼容旧路径 → ``research_agent.pipelines.registry``。"""
from research_agent.pipelines import registry as _mod

globals().update(_mod.__dict__)
