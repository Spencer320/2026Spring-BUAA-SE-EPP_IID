"""兼容旧路径 → ``research_agent.api.manage_views``。"""
from research_agent.api import manage_views as _mod

globals().update(_mod.__dict__)
