"""
Deep Research 任务相关模型

包含：
  - DeepResearchTask       任务主记录（编排器运行时持续更新）
  - DeepResearchStep       任务执行轨迹（每步一条，由编排器写入）
  - DeepResearchAuditLog   管理员干预审计日志（不可删除）
"""

import uuid

from django.db import models

from .user import User
from .file_reading import FileReading
from .admin import Admin


class DeepResearchTask(models.Model):
    """
    Deep Research 任务主记录。

    生命周期：
      pending / queued → running → completed / failed / aborted / admin_stopped
                                 → violation_pending → needs_review → archived

    编排器负责更新：status / current_phase / progress / step_summary /
                    token_used_total / report / citation_coverage /
                    started_at / finished_at / error_message

    管理端通过写 admin_stop_flag=True 触发强制中断；
    编排器每轮执行前检查该字段，为 True 时安全退出并将 status 改为 admin_stopped。
    """

    # ── 状态常量（编排器与管理端共用，避免硬编码字符串）──────────────
    STATUS_PENDING = "pending"
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_ABORTED = "aborted"
    STATUS_ADMIN_STOPPED = "admin_stopped"
    STATUS_VIOLATION_PENDING = "violation_pending"
    STATUS_NEEDS_REVIEW = "needs_review"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = [
        (STATUS_PENDING, "待处理"),
        (STATUS_QUEUED, "排队中"),
        (STATUS_RUNNING, "执行中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_FAILED, "失败"),
        (STATUS_ABORTED, "用户主动中止"),
        (STATUS_ADMIN_STOPPED, "管理员强制中断"),
        (STATUS_VIOLATION_PENDING, "合规审核中"),
        (STATUS_NEEDS_REVIEW, "待人工审核"),
        (STATUS_ARCHIVED, "已归档"),
    ]

    # 运行中或排队中的终态前状态，供管理端筛选"活跃任务"
    ACTIVE_STATUSES = [STATUS_PENDING, STATUS_QUEUED, STATUS_RUNNING]

    # ── 阶段常量（编排器写 current_phase 时使用）──────────────────────
    PHASE_PLANNING = "planning"
    PHASE_SEARCHING = "searching"
    PHASE_READING = "reading"
    PHASE_REFLECTING = "reflecting"
    PHASE_WRITING = "writing"

    PHASE_CHOICES = [
        (PHASE_PLANNING, "规划"),
        (PHASE_SEARCHING, "检索"),
        (PHASE_READING, "阅读"),
        (PHASE_REFLECTING, "反思"),
        (PHASE_WRITING, "生成报告"),
    ]

    # ── 字段定义 ──────────────────────────────────────────────────────
    task_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dr_tasks")
    file_reading = models.ForeignKey(
        FileReading,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dr_tasks",
    )

    # 任务配置（用户端创建时填入）
    query = models.TextField(verbose_name="研究问题")
    max_rounds = models.IntegerField(default=3, verbose_name="最大迭代轮数")

    # 运行态（编排器实时更新）
    status = models.CharField(
        max_length=24,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name="状态",
    )
    current_phase = models.CharField(
        max_length=16, choices=PHASE_CHOICES, null=True, blank=True, verbose_name="当前阶段"
    )
    progress = models.IntegerField(default=0, verbose_name="进度 0-100")
    step_summary = models.CharField(
        max_length=512, blank=True, default="", verbose_name="最新步骤摘要"
    )
    token_used_total = models.IntegerField(default=0, verbose_name="累计消耗 Token")
    error_message = models.TextField(blank=True, default="", verbose_name="错误信息")

    # 结果（编排器完成后写入）
    report = models.JSONField(null=True, blank=True, verbose_name="结构化报告 JSON")
    citation_coverage = models.FloatField(null=True, blank=True, verbose_name="循证覆盖率")

    # 管理端控制字段
    admin_stop_flag = models.BooleanField(
        default=False,
        verbose_name="强制中断信号",
        help_text="管理员置 True 后，编排器下轮检查时安全退出",
    )
    output_suppressed = models.BooleanField(
        default=False,
        verbose_name="屏蔽报告输出",
        help_text="True 时用户端获取报告接口返回 403",
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "deep_research_task"
        verbose_name = "Deep Research 任务"

    def __str__(self):
        return f"DRTask {self.task_id} [{self.status}]"

    # ── 序列化辅助方法 ─────────────────────────────────────────────────

    def to_list_dict(self):
        """管理端列表视图的序列化格式（不含报告内容）"""
        return {
            "task_id": str(self.task_id),
            "user_id": str(self.user.user_id),
            "username": self.user.username,
            "query": self.query,
            "status": self.status,
            "current_phase": self.current_phase,
            "progress": self.progress,
            "step_summary": self.step_summary,
            "token_used_total": self.token_used_total,
            "output_suppressed": self.output_suppressed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    def to_detail_dict(self):
        """管理端详情视图的序列化格式（含配置与报告元信息）"""
        d = self.to_list_dict()
        d.update(
            {
                "max_rounds": self.max_rounds,
                "error_message": self.error_message,
                "citation_coverage": self.citation_coverage,
                "admin_stop_flag": self.admin_stop_flag,
                "report_available": self.report is not None,
                "file_reading_id": self.file_reading_id,
            }
        )
        return d

    def to_user_status_dict(self):
        """用户端轮询状态接口的序列化格式"""
        return {
            "task_id": str(self.task_id),
            "status": self.status,
            "current_phase": self.current_phase,
            "progress": self.progress,
            "step_summary": self.step_summary,
        }


class DeepResearchStep(models.Model):
    """
    Deep Research 任务的单个执行步骤，构成可追溯的执行轨迹。
    编排器每完成一个阶段动作即调用 DeepResearchStep.objects.create(...) 写入一条记录。
    """

    task = models.ForeignKey(
        DeepResearchTask, on_delete=models.CASCADE, related_name="steps"
    )
    seq = models.IntegerField(verbose_name="步骤序号（从 1 开始）")
    phase = models.CharField(max_length=16, verbose_name="所属阶段")
    action = models.CharField(max_length=64, verbose_name="动作描述")
    summary = models.TextField(blank=True, default="", verbose_name="步骤摘要")
    token_used = models.IntegerField(default=0, verbose_name="本步骤 Token 消耗")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "deep_research_step"
        verbose_name = "Deep Research 执行步骤"
        ordering = ["seq"]
        unique_together = ("task", "seq")

    def __str__(self):
        return f"Step {self.seq} [{self.phase}] {self.action}"

    def to_dict(self):
        return {
            "seq": self.seq,
            "phase": self.phase,
            "action": self.action,
            "summary": self.summary,
            "token_used": self.token_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DeepResearchAuditLog(models.Model):
    """
    管理员对 Deep Research 任务的干预操作审计日志。
    所有管理端干预行为（强制中断、屏蔽、恢复）均自动写入，不可删除。
    """

    ACTION_FORCE_STOP = "force_stop"
    ACTION_SUPPRESS = "suppress_output"
    ACTION_UNSUPPRESS = "unsuppress_output"
    ACTION_VIEW_TRACE = "view_trace"

    ACTION_CHOICES = [
        (ACTION_FORCE_STOP, "强制中断"),
        (ACTION_SUPPRESS, "屏蔽输出"),
        (ACTION_UNSUPPRESS, "恢复输出"),
        (ACTION_VIEW_TRACE, "查看轨迹"),
    ]

    log_id = models.AutoField(primary_key=True)
    task = models.ForeignKey(
        DeepResearchTask, on_delete=models.CASCADE, related_name="audit_logs"
    )
    admin = models.ForeignKey(
        Admin, on_delete=models.SET_NULL, null=True, related_name="dr_audit_logs"
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    reason = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "deep_research_audit_log"
        verbose_name = "DR 管理操作审计日志"

    def __str__(self):
        return f"AuditLog {self.log_id} [{self.action}] task={self.task_id}"

    def to_dict(self):
        return {
            "log_id": self.log_id,
            "task_id": str(self.task_id),
            "admin_id": str(self.admin.admin_id) if self.admin else None,
            "admin_name": self.admin.admin_name if self.admin else "已删除管理员",
            "action": self.action,
            "action_label": dict(self.ACTION_CHOICES).get(self.action, self.action),
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "extra": self.extra,
        }
