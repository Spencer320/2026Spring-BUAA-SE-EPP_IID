"""管理端行为审计 API（列表 / 链路 / 导出）。"""

from django.views.decorators.http import require_http_methods

from .auth import authenticate_research_admin
from .views import (
    AUDIT_SCOPE_ASSISTANT,
    AUDIT_SCOPE_DEEP_RESEARCH,
    _admin_behavior_logs_impl,
    _admin_export_behavior_logs_impl,
    _admin_task_behavior_chain_impl,
    admin_behavior_logs,
    admin_export_behavior_logs,
    admin_task_behavior_chain,
)


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_assistant_behavior_logs(request, _admin):
    return _admin_behavior_logs_impl(request, AUDIT_SCOPE_ASSISTANT)


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_deep_research_behavior_logs(request, _admin):
    return _admin_behavior_logs_impl(request, AUDIT_SCOPE_DEEP_RESEARCH)


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_assistant_task_behavior_chain(request, _admin, task_id):
    return _admin_task_behavior_chain_impl(request, _admin, task_id, AUDIT_SCOPE_ASSISTANT)


@require_http_methods(["GET"])
@authenticate_research_admin
def admin_deep_research_task_behavior_chain(request, _admin, task_id):
    return _admin_task_behavior_chain_impl(request, _admin, task_id, AUDIT_SCOPE_DEEP_RESEARCH)


@require_http_methods(["POST"])
@authenticate_research_admin
def admin_assistant_export_behavior_logs(request, _admin):
    return _admin_export_behavior_logs_impl(request, _admin, AUDIT_SCOPE_ASSISTANT)


@require_http_methods(["POST"])
@authenticate_research_admin
def admin_deep_research_export_behavior_logs(request, _admin):
    return _admin_export_behavior_logs_impl(request, _admin, AUDIT_SCOPE_DEEP_RESEARCH)
