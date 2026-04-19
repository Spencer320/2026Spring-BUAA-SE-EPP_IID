"""
访问频次控制相关模型

包含：
  - AccessFrequencyRule       全局功能访问频次规则
  - UserAccessQuotaOverride   用户级配额覆盖（高于或低于全局规则）
  - FeatureAccessLog          功能访问明细日志（异步写入）
"""

from django.db import models

from .user import User


FEATURE_CHOICES = [
    ("deep_research", "Deep Research 任务"),
    ("ai_chat", "AI 对话（研读/调研助手）"),
    ("summary", "综述报告生成"),
    ("export", "报告批量导出"),
]

WINDOW_CHOICES = [
    ("daily", "每日"),
    ("weekly", "每周"),
    ("monthly", "每月"),
]


class AccessFrequencyRule(models.Model):
    """
    全局访问频次规则。
    针对特定功能类型，在指定时间窗口内允许的最大访问次数。
    max_count = -1 表示不限制。
    """

    rule_id = models.AutoField(primary_key=True)
    feature = models.CharField(
        max_length=32, choices=FEATURE_CHOICES, unique=True, verbose_name="功能类型"
    )
    window = models.CharField(
        max_length=16, choices=WINDOW_CHOICES, default="daily", verbose_name="统计窗口"
    )
    max_count = models.IntegerField(default=10, verbose_name="最大次数（-1=不限）")
    is_enabled = models.BooleanField(default=True, verbose_name="是否启用")
    description = models.CharField(max_length=255, blank=True, default="", verbose_name="描述")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=64, blank=True, default="", verbose_name="最后修改人")

    class Meta:
        db_table = "access_frequency_rule"
        verbose_name = "访问频次规则"

    def __str__(self):
        return f"{self.feature} / {self.window} / max={self.max_count}"

    def to_dict(self):
        feature_label = dict(FEATURE_CHOICES).get(self.feature, self.feature)
        window_label = dict(WINDOW_CHOICES).get(self.window, self.window)
        return {
            "rule_id": self.rule_id,
            "feature": self.feature,
            "feature_label": feature_label,
            "window": self.window,
            "window_label": window_label,
            "max_count": self.max_count,
            "is_enabled": self.is_enabled,
            "description": self.description,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by,
        }


class UserAccessQuotaOverride(models.Model):
    """
    用户级配额覆盖。
    若存在此记录，则忽略全局规则，使用本记录中的 max_count。
      max_count = -1  不限制（VIP / 管理员特批）
      max_count =  0  完全封禁此功能
      max_count >  0  自定义次数上限
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="quota_overrides"
    )
    feature = models.CharField(max_length=32, choices=FEATURE_CHOICES, verbose_name="功能类型")
    max_count = models.IntegerField(default=-1, verbose_name="覆盖次数上限")
    reason = models.CharField(max_length=255, blank=True, default="", verbose_name="原因")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=64, blank=True, default="", verbose_name="操作人")

    class Meta:
        db_table = "user_access_quota_override"
        unique_together = ("user", "feature")
        verbose_name = "用户配额覆盖"

    def __str__(self):
        return f"{self.user.username} - {self.feature} - {self.max_count}"

    def to_dict(self):
        return {
            "override_id": self.pk,
            "user_id": str(self.user.user_id),
            "username": self.user.username,
            "feature": self.feature,
            "feature_label": dict(FEATURE_CHOICES).get(self.feature, self.feature),
            "max_count": self.max_count,
            "reason": self.reason,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by,
        }


class FeatureAccessLog(models.Model):
    """
    功能访问明细日志。
    记录每次受限功能的调用（放行 / 被拒），用于频次统计与合规审计。
    由 rate_limit.py 中的工具函数在后台线程中异步写入，不阻塞主请求。
    """

    STATUS_ALLOWED = "allowed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_ALLOWED, "放行"),
        (STATUS_REJECTED, "因超限被拒"),
    ]

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="access_logs"
    )
    feature = models.CharField(max_length=32, db_index=True, verbose_name="功能类型")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    accessed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "feature_access_log"
        verbose_name = "功能访问日志"
        indexes = [
            models.Index(fields=["feature", "accessed_at"]),
            models.Index(fields=["user", "feature", "accessed_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} / {self.feature} / {self.status} / {self.accessed_at}"
