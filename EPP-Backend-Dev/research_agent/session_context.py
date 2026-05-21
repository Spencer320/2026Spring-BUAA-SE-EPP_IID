"""兼容旧路径 → ``research_agent.pipelines.basic.session_context``。"""
from research_agent.pipelines.basic import session_context as _mod

globals().update(_mod.__dict__)
