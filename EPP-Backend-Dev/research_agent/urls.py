from django.urls import path

from . import site_access_views, views

urlpatterns = [
    path("sessions/", views.sessions_collection),
    path("sessions/messages/", views.create_session_with_first_message),
    path("sessions/batch-delete/", views.post_batch_delete_sessions),
    path("tasks/", views.create_task),
    path("tasks/export/", views.export_tasks),
    path("sessions/<uuid:session_id>/", views.get_session),
    path("sessions/<uuid:session_id>/messages/", views.post_session_message),
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
    path("manage/behavior-logs/", views.admin_behavior_logs),
    path("manage/behavior-logs/export/", views.admin_export_behavior_logs),
    path("manage/tasks/<uuid:task_id>/behavior-chain/", views.admin_task_behavior_chain),
    path("manage/site-access/policy/", site_access_views.admin_site_access_policy),
    path("manage/site-access/rules/", site_access_views.admin_site_access_rules),
    path("manage/site-access/rules/<int:rule_id>/", site_access_views.admin_site_access_rule_detail),
    path("manage/site-access/events/", site_access_views.admin_site_access_events),
    path("manage/site-access/stats/", site_access_views.admin_site_access_stats),
]
