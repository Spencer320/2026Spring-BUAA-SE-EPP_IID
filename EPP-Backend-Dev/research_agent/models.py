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
    step_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    trace_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    actor_type = models.CharField(max_length=32, blank=True, default="system", db_index=True)
    tool_type = models.CharField(max_length=64, blank=True, default="", db_index=True)
    risk_level = models.CharField(max_length=16, blank=True, default="", db_index=True)
    rule_hit = models.CharField(max_length=255, blank=True, default="")
    policy_version = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=32, blank=True, default="", db_index=True)
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
            "task_name": str(self.task.session.title or ""),
            "session_id": str(self.task.session_id),
            "user_id": str(self.task.session.owner_id),
            "operation_type": self.operation_type,
            "target_url": self.target_url,
            "target_domain": self.target_domain,
            "request_headers": self.request_headers or {},
            "request_payload": self.request_payload or {},
            "action_payload": self.action_payload or {},
            "step_id": self.step_id,
            "trace_id": self.trace_id,
            "actor_type": self.actor_type,
            "tool_type": self.tool_type,
            "risk_level": self.risk_level,
            "rule_hit": self.rule_hit,
            "policy_version": self.policy_version,
            "status": self.status,
            "response_status": self.response_status,
            "is_exception": self.is_exception,
            "exception_message": self.exception_message,
            "trace_detail": self.trace_detail,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else "",
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


SITE_ACCESS_POLICY_MODE_CHOICES = [
    ("whitelist", "whitelist"),
    ("blacklist", "blacklist"),
]

SITE_ACCESS_RULE_TYPE_CHOICES = [
    ("allow", "allow"),
    ("deny", "deny"),
]

SITE_ACCESS_MATCH_TYPE_CHOICES = [
    ("exact", "exact"),
    ("suffix", "suffix"),
    ("wildcard", "wildcard"),
]


class SiteAccessPolicyConfig(models.Model):
    """
    目标站点访问策略配置（全局单例）。
    mode:
      - whitelist: 仅命中 allow 规则才放行（deny 规则优先拦截）
      - blacklist: 命中 deny 规则拦截，其余放行（allow 可用于显式例外）
    """

    id = models.BigAutoField(primary_key=True)
    mode = models.CharField(
        max_length=16,
        choices=SITE_ACCESS_POLICY_MODE_CHOICES,
        default="blacklist",
        db_index=True,
    )
    policy_version = models.PositiveIntegerField(default=1)
    updated_by = models.CharField(max_length=64, blank=True, default="")
    description = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]

    def to_dict(self):
        return {
            "id": self.id,
            "mode": self.mode,
            "policy_version": int(self.policy_version or 1),
            "updated_by": self.updated_by,
            "description": self.description,
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class SiteAccessRule(models.Model):
    """
    目标站点规则（支持精确域名、后缀域名与简单通配符）。
    """

    rule_id = models.AutoField(primary_key=True)
    rule_type = models.CharField(
        max_length=16,
        choices=SITE_ACCESS_RULE_TYPE_CHOICES,
        db_index=True,
    )
    match_type = models.CharField(
        max_length=16,
        choices=SITE_ACCESS_MATCH_TYPE_CHOICES,
        default="suffix",
        db_index=True,
    )
    pattern = models.CharField(max_length=255, db_index=True)
    priority = models.PositiveIntegerField(default=100, db_index=True)
    is_enabled = models.BooleanField(default=True, db_index=True)
    description = models.CharField(max_length=255, blank=True, default="")
    created_by = models.CharField(max_length=64, blank=True, default="")
    updated_by = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "rule_id"]

    def to_dict(self):
        return {
            "rule_id": int(self.rule_id),
            "rule_type": self.rule_type,
            "match_type": self.match_type,
            "pattern": self.pattern,
            "priority": int(self.priority or 0),
            "is_enabled": bool(self.is_enabled),
            "description": self.description,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }
