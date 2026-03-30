import uuid

from django.db import models

from .user import User
from .notification import Notification
from .auto_deleted import AutoDeleted
from .detectable import Detectable


class AutoDeletedAnnotationNew(AutoDeleted):
    """Field:
    - annotation   批注ID
    """

    annotation = models.ForeignKey("PaperAnnotationItem", on_delete=models.CASCADE)

    def get_author(self) -> User:
        return self.annotation.author

    def get_level(self) -> str:
        return "N/A"

    def get_id(self) -> str:
        return str(self.annotation.id)

    def get_content(self) -> str:
        return self.annotation.content

    def mark_content_safe(self):
        self.annotation.safe()

    def mark_content_blocked(self):
        self.annotation.block()


class AutoDeletedAnnotationCommentNew(AutoDeleted):
    """Field:
    - comment      评论
    """

    comment = models.ForeignKey("PaperAnnotationComment", on_delete=models.CASCADE)

    def get_author(self) -> User:
        return self.comment.author

    def get_level(self) -> str:
        return "1"

    def get_id(self) -> str:
        return str(self.comment.id)

    def get_content(self) -> str:
        return self.comment.content

    def mark_content_safe(self):
        self.comment.safe()

    def mark_content_blocked(self):
        self.comment.block()


class AutoDeletedAnnotationSubCommentNew(AutoDeleted):
    """Field:
    - sub_comment  子评论
    """

    sub_comment = models.ForeignKey(
        "PaperAnnotationSubComment",
        on_delete=models.CASCADE,
        related_name="sub_comments",
    )

    def get_author(self) -> User:
        return self.sub_comment.author

    def get_level(self) -> str:
        return "2"

    def get_id(self) -> str:
        return str(self.sub_comment.id)

    def get_content(self) -> str:
        return self.sub_comment.content

    def mark_content_safe(self):
        self.sub_comment.safe()

    def mark_content_blocked(self):
        self.sub_comment.block()


class PaperAnnotationNew(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    paper = models.ForeignKey("Paper", on_delete=models.CASCADE)
    position = models.JSONField(null=True, blank=True)


class PaperAnnotationItem(Detectable):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    annotation = models.ForeignKey(PaperAnnotationNew, on_delete=models.CASCADE)
    content = models.TextField()
    author = models.ForeignKey("User", on_delete=models.CASCADE)
    liked_by_user = models.ManyToManyField(
        "User", related_name="liked_annotations_new", blank=True
    )
    last_modified = models.DateTimeField(auto_now=True)

    @staticmethod
    def get_content_name() -> str:
        return "文献批注"

    def insert_auto_delete(self, reason: str = None, title: str = None):
        AutoDeletedAnnotationNew.objects.create(
            annotation=self,
            reason=reason,
        )
        Notification.create(
            self.author,
            title,
            '您在 {} 的 {} 内容 "{}" 已被平台自动删除，原因为 {}'.format(
                self.check_date.strftime("%Y-%m-%d %H:%M:%S"),
                self.get_content_name(),
                self.content,
                reason,
            ),
        )


class PaperAnnotationComment(Detectable):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    annotation_item = models.ForeignKey(PaperAnnotationItem, on_delete=models.CASCADE)
    author = models.ForeignKey("User", on_delete=models.CASCADE)
    content = models.TextField()
    liked_by_user = models.ManyToManyField(
        "User", related_name="liked_comments_new", blank=True
    )
    last_modified = models.DateTimeField(auto_now=True)

    @staticmethod
    def get_content_name() -> str:
        return "批注一级评论"

    def insert_auto_delete(self, reason: str = None, title: str = None):
        AutoDeletedAnnotationCommentNew.objects.create(
            comment=self,
            reason=reason,
        )
        Notification.create(
            self.author,
            title,
            '您在 {} 的 {} 内容 "{}" 已被平台自动删除，原因为 {}'.format(
                self.check_date.strftime("%Y-%m-%d %H:%M:%S"),
                self.get_content_name(),
                self.content,
                reason,
            ),
        )


class PaperAnnotationSubComment(Detectable):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    parent_comment = models.ForeignKey(PaperAnnotationComment, on_delete=models.CASCADE)
    author = models.ForeignKey("User", on_delete=models.CASCADE)
    content = models.TextField()
    liked_by_user = models.ManyToManyField(
        "User", related_name="liked_sub_comments_new", blank=True
    )
    last_modified = models.DateTimeField(auto_now=True)

    @staticmethod
    def get_content_name() -> str:
        return "批注二级评论"

    def insert_auto_delete(self, reason: str = None, title: str = None):
        AutoDeletedAnnotationSubCommentNew.objects.create(
            sub_comment=self,
            reason=reason,
        )
        Notification.create(
            self.author,
            title,
            '您在 {} 的 {} 内容 "{}" 已被平台自动删除，原因为 {}'.format(
                self.check_date.strftime("%Y-%m-%d %H:%M:%S"),
                self.get_content_name(),
                self.content,
                reason,
            ),
        )
