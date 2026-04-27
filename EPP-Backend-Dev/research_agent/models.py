import uuid

from django.db import models
from django.utils import timezone


class ResearchSession(models.Model):
    """科研智能助手会话，与 business 内旧会话隔离。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = models.CharField(max_length=128, db_index=True)
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


class AgentBehaviorAuditLog(models.Model):
    """科研助手行为审计日志（外部访问轨迹与交互记录）。"""

    id = models.BigAutoField(primary_key=True)
    task = models.ForeignKey(
        AgentTask, on_delete=models.CASCADE, related_name="behavior_audit_logs"
    )
    operation_type = models.CharField(max_length=64, db_index=True)
    target_url = models.CharField(max_length=1024, blank=True, default="")
    target_domain = models.CharField(max_length=255, blank=True, default="", db_index=True)
    request_headers = models.JSONField(default=dict, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    action_payload = models.JSONField(default=dict, blank=True)
    response_status = models.IntegerField(null=True, blank=True, db_index=True)
    is_exception = models.BooleanField(default=False, db_index=True)
    exception_message = models.CharField(max_length=512, blank=True, default="")
    trace_detail = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": str(self.task_id),
            "session_id": str(self.task.session_id),
            "user_id": str(self.task.session.owner_id),
            "operation_type": self.operation_type,
            "target_url": self.target_url,
            "target_domain": self.target_domain,
            "request_headers": self.request_headers or {},
            "request_payload": self.request_payload or {},
            "action_payload": self.action_payload or {},
            "response_status": self.response_status,
            "is_exception": self.is_exception,
            "exception_message": self.exception_message,
            "trace_detail": self.trace_detail,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }
