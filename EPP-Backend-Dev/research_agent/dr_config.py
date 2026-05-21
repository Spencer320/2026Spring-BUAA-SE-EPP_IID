"""兼容旧路径 → ``research_agent.pipelines.deep.config``。"""
from research_agent.pipelines.deep import config as _mod

globals().update(_mod.__dict__)
