"""兼容旧路径 → ``research_agent.api.manage_audit``。"""
from research_agent.api import manage_audit as _mod

globals().update(_mod.__dict__)
