"""
Deep Research相关数据模型
"""

from django.db import models
from django.utils import timezone
import json
from typing import List, Dict, Any, Optional

from business.models import User, SummaryReport


class DeepResearchStatus:
    """深度研究状态常量"""
    PENDING = 0  # 等待处理
    IN_PROGRESS = 1  # 处理中
    COMPLETED = 2  # 已完成
    FAILED = 3  # 失败


class DeepResearchRecord(models.Model):
    """深度研究记录模型"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="deep_research_records")
    summary_report = models.ForeignKey(SummaryReport, on_delete=models.CASCADE, related_name="deep_research_records")
    title = models.CharField(max_length=255)
    research_requirement = models.TextField()  # 用户输入的研究需求
    status = models.IntegerField(default=DeepResearchStatus.PENDING)  # 状态
    progress = models.CharField(max_length=255, default="待处理")  # 处理进度描述
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    report_path = models.CharField(max_length=255, null=True, blank=True)  # 报告文件路径
    error_message = models.TextField(null=True, blank=True)  # 错误信息
    
    # 保存为JSON字段的数据
    _subtasks = models.TextField(null=True, blank=True)  # 任务拆解结果
    _follow_up_qa = models.TextField(null=True, blank=True)  # 后续问答记录
    _section_details = models.TextField(null=True, blank=True)  # 局部内容详细展开
    _recommended_questions = models.TextField(null=True, blank=True)  # 推荐问题
    
    class Meta:
        db_table = "deep_research_record"
        ordering = ["-created_at"]
    
    def update_progress(self, progress: str) -> None:
        """更新处理进度
        
        Args:
            progress: 进度描述
        """
        self.progress = progress
        self.updated_at = timezone.now()
        self.save(update_fields=["progress", "updated_at"])
    
    @property
    def subtasks(self) -> List[Dict[str, str]]:
        """获取任务拆解结果
        
        Returns:
            任务拆解结果列表
        """
        if not self._subtasks:
            return []
        return json.loads(self._subtasks)
    
    @subtasks.setter
    def subtasks(self, value: List[Dict[str, str]]) -> None:
        """设置任务拆解结果
        
        Args:
            value: 任务拆解结果列表
        """
        self._subtasks = json.dumps(value, ensure_ascii=False)
    
    @property
    def follow_up_qa(self) -> List[Dict[str, Any]]:
        """获取后续问答记录
        
        Returns:
            后续问答记录列表
        """
        if not self._follow_up_qa:
            return []
        return json.loads(self._follow_up_qa)
    
    @follow_up_qa.setter
    def follow_up_qa(self, value: List[Dict[str, Any]]) -> None:
        """设置后续问答记录
        
        Args:
            value: 后续问答记录列表
        """
        self._follow_up_qa = json.dumps(value, ensure_ascii=False)
    
    @property
    def section_details(self) -> Dict[str, Dict[str, Any]]:
        """获取局部内容详细展开
        
        Returns:
            局部内容详细展开字典
        """
        if not self._section_details:
            return {}
        return json.loads(self._section_details)
    
    @section_details.setter
    def section_details(self, value: Dict[str, Dict[str, Any]]) -> None:
        """设置局部内容详细展开
        
        Args:
            value: 局部内容详细展开字典
        """
        self._section_details = json.dumps(value, ensure_ascii=False)
    
    @property
    def recommended_questions(self) -> List[str]:
        """获取推荐问题
        
        Returns:
            推荐问题列表
        """
        if not self._recommended_questions:
            return []
        return json.loads(self._recommended_questions)
    
    @recommended_questions.setter
    def recommended_questions(self, value: List[str]) -> None:
        """设置推荐问题
        
        Args:
            value: 推荐问题列表
        """
        self._recommended_questions = json.dumps(value, ensure_ascii=False)