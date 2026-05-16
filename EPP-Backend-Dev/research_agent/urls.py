from django.urls import path

from . import manage_audit, manage_views, site_access_views, views

urlpatterns = [
    path("sessions/", views.sessions_collection),
    path("sessions/messages/", views.create_session_with_first_message),
    path("sessions/batch-delete/", views.post_batch_delete_sessions),
    path("tasks/", views.create_task),
    path("tasks/deep-research/", views.create_deep_research_task),
    path("tasks/export/", views.export_tasks),
    path("sessions/<uuid:session_id>/paper-shelf/", views.paper_shelf_list),
    path("sessions/<uuid:session_id>/paper-shelf/workspace/", views.paper_shelf_add_workspace),
    path("sessions/<uuid:session_id>/paper-shelf/<uuid:item_id>/", views.paper_shelf_delete_item),
    path("sessions/<uuid:session_id>/messages/", views.post_session_message),
    path("sessions/<uuid:session_id>/", views.get_session),
    path("tasks/<uuid:task_id>/", views.get_task),
    path("tasks/<uuid:task_id>/status/", views.get_task_status),
    path("tasks/<uuid:task_id>/events/", views.get_task_events),
    path("tasks/<uuid:task_id>/report/", views.get_task_report),
    path("tasks/<uuid:task_id>/actions/", views.post_task_actions),
    path("tasks/<uuid:task_id>/follow-up/", views.post_task_follow_up),
    path("tasks/<uuid:task_id>/download/", views.download_task_report),
    path("tasks/<uuid:task_id>/intervention/", views.post_intervention),
    path("tasks/<uuid:task_id>/cancel/", views.post_cancel_task),
    path("tasks/<uuid:task_id>/behavior-logs/", views.post_task_behavior_log),
    # 管理端任务列表（按 Run 聚合）
    path("manage/deep-research/stats/", manage_views.admin_deep_research_stats),
    path("manage/deep-research/tasks/", manage_views.admin_deep_research_tasks),
    path(
        "manage/deep-research/tasks/<uuid:task_id>/behavior-chain/",
        manage_audit.admin_deep_research_task_behavior_chain,
    ),
    path(
        "manage/deep-research/tasks/<uuid:task_id>/cancel/",
        manage_views.admin_deep_research_task_cancel,
    ),
    path(
        "manage/deep-research/tasks/<uuid:task_id>/detail/",
        manage_views.admin_deep_research_task_detail,
    ),
    path("manage/assistant/stats/", manage_views.admin_assistant_stats),
    path("manage/assistant/tasks/", manage_views.admin_assistant_tasks),
    path(
        "manage/assistant/tasks/<uuid:task_id>/detail/",
        manage_views.admin_assistant_task_detail,
    ),
    path(
        "manage/assistant/tasks/<uuid:task_id>/cancel/",
        manage_views.admin_assistant_task_cancel,
    ),
    # 管理端行为审计
    path("manage/assistant/behavior-logs/", manage_audit.admin_assistant_behavior_logs),
    path("manage/assistant/behavior-logs/export/", manage_audit.admin_assistant_export_behavior_logs),
    path(
        "manage/assistant/tasks/<uuid:task_id>/behavior-chain/",
        manage_audit.admin_assistant_task_behavior_chain,
    ),
    path("manage/deep-research/behavior-logs/", manage_audit.admin_deep_research_behavior_logs),
    path(
        "manage/deep-research/behavior-logs/export/",
        manage_audit.admin_deep_research_export_behavior_logs,
    ),
    # 兼容旧管理端路径（须带 audit_scope）
    path("manage/behavior-logs/", manage_audit.admin_behavior_logs),
    path("manage/behavior-logs/export/", manage_audit.admin_export_behavior_logs),
    path("manage/tasks/<uuid:task_id>/behavior-chain/", manage_audit.admin_task_behavior_chain),
    path("manage/site-access/policy/", site_access_views.admin_site_access_policy),
    path("manage/site-access/rules/", site_access_views.admin_site_access_rules),
    path("manage/site-access/rules/<int:rule_id>/", site_access_views.admin_site_access_rule_detail),
    path("manage/site-access/events/", site_access_views.admin_site_access_events),
    path("manage/site-access/stats/", site_access_views.admin_site_access_stats),
]
