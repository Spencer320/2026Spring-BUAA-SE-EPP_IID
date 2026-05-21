"""兼容旧路径 → ``research_agent.api.site_access_views``。"""
from research_agent.api import site_access_views as _mod

globals().update(_mod.__dict__)
