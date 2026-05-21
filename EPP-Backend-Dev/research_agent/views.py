"""兼容旧路径 ``research_agent.views`` → ``research_agent.api.views``（含私有符号）。"""
from research_agent.api import views as _views

globals().update(_views.__dict__)
