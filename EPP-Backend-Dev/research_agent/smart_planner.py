"""兼容旧路径 → ``research_agent.pipelines.basic.planner``。"""
from research_agent.pipelines.basic import planner as _mod

globals().update(_mod.__dict__)
