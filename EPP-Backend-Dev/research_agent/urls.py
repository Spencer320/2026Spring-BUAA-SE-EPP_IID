from django.urls import path

from . import views

urlpatterns = [
    path("sessions/", views.sessions_collection),
    path("sessions/<uuid:session_id>/", views.get_session),
    path("sessions/<uuid:session_id>/messages/", views.post_session_message),
    path("tasks/<uuid:task_id>/", views.get_task),
    path("tasks/<uuid:task_id>/intervention/", views.post_intervention),
    path("tasks/<uuid:task_id>/cancel/", views.post_cancel_task),
    path("tasks/<uuid:task_id>/behavior-logs/", views.post_task_behavior_log),
    path("manage/behavior-logs/", views.admin_behavior_logs),
    path("manage/behavior-logs/export/", views.admin_export_behavior_logs),
    path("manage/tasks/<uuid:task_id>/behavior-chain/", views.admin_task_behavior_chain),
]
