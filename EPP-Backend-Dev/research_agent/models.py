import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class ResearchPaperShelfItem(models.Model):
    """
    会话论文展示区条目：外链（检索）或工作区文件。

    ``dedupe_key`` 在同一会话内唯一，用于检索结果去重与工作区路径去重。
    """

    SOURCE_KIND_CHOICES = [
        ("external_link", "external_link"),
        ("workspace_file", "workspace_file"),
    ]
    CONTEXT_TIER_CHOICES = [
        ("abstract_only", "abstract_only"),
        ("link_only", "link_only"),
        ("full_text_available", "full_text_available"),
        ("workspace_opaque", "workspace_opaque"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ResearchSession,
        on_delete=models.CASCADE,
        related_name="paper_shelf_items",
    )
    source_kind = models.CharField(max_length=32, choices=SOURCE_KIND_CHOICES, db_index=True)
    display_title = models.CharField(max_length=512)
    authors = models.TextField(blank=True, default="")
    abstract = models.TextField(blank=True, default="")
    primary_url = models.CharField(max_length=2048, blank=True, default="")
    workspace_rel_path = models.CharField(max_length=1024, blank=True, default="")
    file_extension = models.CharField(max_length=32, blank=True, default="")
    context_tier = models.CharField(max_length=32, choices=CONTEXT_TIER_CHOICES, db_index=True)
    dedupe_key = models.CharField(max_length=512, db_index=True)
    added_via = models.CharField(max_length=32, blank=True, default="")
    search_query = models.CharField(max_length=512, blank=True, default="")
    source_detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["session", "dedupe_key"], name="ra_paper_shelf_session_dedupe"),
        ]


class _OrchestrationRunBase(models.Model):
    """会话内一次可编排执行的通用持久化字段（抽象基类）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ResearchSession, on_delete=models.CASCADE)
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
        abstract = True
        ordering = ["-created_at"]


class AgentTask(_OrchestrationRunBase):
    """
    深度研究六阶段流水线专用持久化实体。

    仅由 ``orchestrator.execute_deep_research_pipeline`` 及独立深度研究 API 创建/更新；
    不再承载 basic / workspace 编排状态。
    """

    session = models.ForeignKey(
        ResearchSession,
        on_delete=models.CASCADE,
        related_name="deep_research_tasks",
    )

    class Meta:
        ordering = ["-created_at"]


class BasicOrchestratorRun(_OrchestrationRunBase):
    """会话主入口：Smart Planner + 顺序子任务（chat / search / agent）。"""

    session = models.ForeignKey(
        ResearchSession,
        on_delete=models.CASCADE,
        related_name="basic_runs",
    )

    class Meta:
        ordering = ["-created_at"]


class WorkspaceAgentRun(_OrchestrationRunBase):
    """
    工作区 Agent 多轮执行（``workspace_pipeline``）。

    由 ``agent_orchestrator`` 在 basic 的 ``agent`` 子步骤中创建，可选关联父 basic 运行以便追溯。
    """

    session = models.ForeignKey(
        ResearchSession,
        on_delete=models.CASCADE,
        related_name="workspace_runs",
    )
    parent_basic_run = models.ForeignKey(
        BasicOrchestratorRun,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="workspace_children",
        help_text="非空表示由 basic 编排器委托产生的工作区子运行。",
    )

    class Meta:
        ordering = ["-created_at"]


class AgentBehaviorAuditLog(models.Model):
    """科研助手行为审计日志（外部访问轨迹与交互记录）。"""

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        ResearchSession,
        on_delete=models.CASCADE,
        related_name="behavior_audit_logs",
        help_text="冗余会话外键，便于按用户/会话筛选而无需多态 JOIN。",
    )
    deep_task = models.ForeignKey(
        AgentTask,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="deep_behavior_audit_logs",
    )
    basic_run = models.ForeignKey(
        BasicOrchestratorRun,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="basic_behavior_audit_logs",
    )
    workspace_run = models.ForeignKey(
        WorkspaceAgentRun,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="workspace_behavior_audit_logs",
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
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(deep_task__isnull=False, basic_run__isnull=True, workspace_run__isnull=True)
                    | Q(deep_task__isnull=True, basic_run__isnull=False, workspace_run__isnull=True)
                    | Q(deep_task__isnull=True, basic_run__isnull=True, workspace_run__isnull=False)
                ),
                name="ra_behavior_audit_exactly_one_run",
            ),
        ]

    def clean(self) -> None:
        n = sum(
            1
            for x in (self.deep_task_id, self.basic_run_id, self.workspace_run_id)
            if x is not None
        )
        if n != 1:
            raise ValidationError("行为审计必须且只能关联一种运行实体")

    def linked_run(self) -> AgentTask | BasicOrchestratorRun | WorkspaceAgentRun | None:
        if self.deep_task_id:
            return self.deep_task
        if self.basic_run_id:
            return self.basic_run
        if self.workspace_run_id:
            return self.workspace_run
        return None

    def to_dict(self):
        from .run_registry import run_kind

        run = self.linked_run()
        rk = run_kind(run) if run is not None else ""
        return {
            "id": self.id,
            "task_id": str(run.id) if run else "",
            "run_kind": rk,
            "task_name": str(self.session.title or ""),
            "session_id": str(self.session_id),
            "user_id": str(self.session.owner_id),
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
