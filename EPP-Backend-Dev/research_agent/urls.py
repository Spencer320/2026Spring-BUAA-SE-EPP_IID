from django.urls import path

from . import views

urlpatterns = [
    path("sessions/", views.sessions_collection),
    path("sessions/<uuid:session_id>/", views.get_session),
    path("sessions/<uuid:session_id>/messages/", views.post_session_message),
    path("tasks/<uuid:task_id>/", views.get_task),
    path("tasks/<uuid:task_id>/intervention/", views.post_intervention),
    path("tasks/<uuid:task_id>/cancel/", views.post_cancel_task),
]
