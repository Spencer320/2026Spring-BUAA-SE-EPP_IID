# 拆分编排持久化：AgentTask 仅深度研究；新增 BasicOrchestratorRun / WorkspaceAgentRun；
# 行为审计改为 session + 三选一运行外键。

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("research_agent", "0006_agenttask_parent_task"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="agenttask",
            name="parent_task",
        ),
        migrations.AlterField(
            model_name="agenttask",
            name="session",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="deep_research_tasks",
                to="research_agent.researchsession",
            ),
        ),
        migrations.CreateModel(
            name="BasicOrchestratorRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("status", models.CharField(max_length=32)),
                ("step_seq", models.PositiveIntegerField(default=0)),
                ("steps", models.JSONField(default=list)),
                ("intervention", models.JSONField(blank=True, null=True)),
                ("result_payload", models.JSONField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=128, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="basic_runs",
                        to="research_agent.researchsession",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceAgentRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("status", models.CharField(max_length=32)),
                ("step_seq", models.PositiveIntegerField(default=0)),
                ("steps", models.JSONField(default=list)),
                ("intervention", models.JSONField(blank=True, null=True)),
                ("result_payload", models.JSONField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=128, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "parent_basic_run",
                    models.ForeignKey(
                        blank=True,
                        help_text="非空表示由 basic 编排器委托产生的工作区子运行。",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_children",
                        to="research_agent.basicorchestratorrun",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_runs",
                        to="research_agent.researchsession",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.DeleteModel(
            name="AgentBehaviorAuditLog",
        ),
        migrations.CreateModel(
            name="AgentBehaviorAuditLog",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("operation_type", models.CharField(db_index=True, max_length=64)),
                ("target_url", models.CharField(blank=True, default="", max_length=1024)),
                ("target_domain", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("request_headers", models.JSONField(blank=True, default=dict)),
                ("request_payload", models.JSONField(blank=True, default=dict)),
                ("action_payload", models.JSONField(blank=True, default=dict)),
                ("step_id", models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                ("trace_id", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("actor_type", models.CharField(blank=True, db_index=True, default="system", max_length=32)),
                ("tool_type", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("risk_level", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("rule_hit", models.CharField(blank=True, default="", max_length=255)),
                ("policy_version", models.CharField(blank=True, default="", max_length=64)),
                ("status", models.CharField(blank=True, db_index=True, default="", max_length=32)),
                ("response_status", models.IntegerField(blank=True, db_index=True, null=True)),
                ("is_exception", models.BooleanField(db_index=True, default=False)),
                ("exception_message", models.CharField(blank=True, default="", max_length=512)),
                ("trace_detail", models.TextField(blank=True, default="")),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        help_text="冗余会话外键，便于按用户/会话筛选而无需多态 JOIN。",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="behavior_audit_logs",
                        to="research_agent.researchsession",
                    ),
                ),
                (
                    "basic_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="basic_behavior_audit_logs",
                        to="research_agent.basicorchestratorrun",
                    ),
                ),
                (
                    "deep_task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deep_behavior_audit_logs",
                        to="research_agent.agenttask",
                    ),
                ),
                (
                    "workspace_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_behavior_audit_logs",
                        to="research_agent.workspaceagentrun",
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="agentbehaviorauditlog",
            constraint=models.CheckConstraint(
                condition=(
                    Q(deep_task__isnull=False, basic_run__isnull=True, workspace_run__isnull=True)
                    | Q(deep_task__isnull=True, basic_run__isnull=False, workspace_run__isnull=True)
                    | Q(deep_task__isnull=True, basic_run__isnull=True, workspace_run__isnull=False)
                ),
                name="ra_behavior_audit_exactly_one_run",
            ),
        ),
    ]
