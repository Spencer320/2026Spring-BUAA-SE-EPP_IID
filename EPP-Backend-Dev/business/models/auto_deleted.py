import uuid

from django.db import models

from .user import User
from .paper_annotation import (
    PaperAnnotation,
    PaperAnnotationCommentFirstLevel,
    PaperAnnotationCommentSecondLevel,
)


class AutoDeleted(models.Model):
    """Field:
    - date            创建时间
    - reverted        是否已恢复
    """

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    date = models.DateTimeField(auto_now_add=True)
    reverted = models.BooleanField(default=False)
    reason = models.TextField(null=True)

    class Meta:
        abstract = True

    def get_author(self) -> User:
        """获取作者"""
        raise NotImplementedError("This method should be implemented in subclasses")

    def get_level(self) -> str:
        """获取评论级别"""
        raise NotImplementedError("This method should be implemented in subclasses")

    def get_id(self) -> str:
        """获取内容 ID"""
        raise NotImplementedError("This method should be implemented in subclasses")

    def get_content(self) -> str:
        """获取内容"""
        raise NotImplementedError("This method should be implemented in subclasses")

    def get_date(self) -> str:
        """获取创建时间"""
        return self.date.strftime("%Y-%m-%d %H:%M:%S")

    def mark_content_safe(self):
        """标记内容为安全"""
        raise NotImplementedError("This method should be implemented in subclasses")

    def mark_content_blocked(self):
        """标记内容为不安全"""
        raise NotImplementedError("This method should be implemented in subclasses")


class AutoDeletedPaperAnnotation(AutoDeleted):
    """Deprecated

    Field:
    - annotation_id   注释ID
    """

    annotation_id = models.ForeignKey(PaperAnnotation, on_delete=models.CASCADE)


class AutoDeletedPaperAnnotationFirstComment(AutoDeleted):
    """Deprecated

    Field:
    - comment_id      评论ID
    """

    comment_id = models.ForeignKey(
        PaperAnnotationCommentFirstLevel, on_delete=models.CASCADE
    )


class AutoDeletedPaperAnnotationSecondComment(AutoDeleted):
    """Deprecated

    Field:
    - comment_id      评论ID
    """

    comment_id = models.ForeignKey(
        PaperAnnotationCommentSecondLevel, on_delete=models.CASCADE
    )
