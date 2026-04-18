import uuid

from django.db import models

from business.models.user import User


class ResearchSession(models.Model):
    """科研智能助手会话，与 business 内旧会话隔离。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="research_sessions"
    )
    title = models.CharField(max_length=512, default="新会话")
    status = models.CharField(max_length=32, default="active")  # active | archived
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class ResearchMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ResearchSession, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=32)  # user | assistant
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class AgentTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ResearchSession, on_delete=models.CASCADE, related_name="tasks"
    )
    status = models.CharField(max_length=32)
    step_seq = models.PositiveIntegerField(default=0)
    steps = models.JSONField(default=list)
    intervention = models.JSONField(null=True, blank=True)
    result_payload = models.JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=128, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
