"""
文献评论表：一级评论表、二级评论表
"""

from django.db import models
import uuid

from .notification import Notification
from .auto_deleted import AutoDeleted
from .detectable import Detectable
from .user import User
from .paper import Paper


class AutoDeletedFirstComment(AutoDeleted):
    """Field:
    - comment_id      评论ID
    """

    comment_id = models.ForeignKey("FirstLevelComment", on_delete=models.CASCADE)

    def get_author(self) -> User:
        return self.comment_id.user_id

    def get_level(self) -> str:
        return "1"

    def get_id(self) -> str:
        return str(self.comment_id.comment_id)

    def get_content(self) -> str:
        return self.comment_id.text

    def mark_content_safe(self):
        self.comment_id.safe()

    def mark_content_blocked(self):
        self.comment_id.block()


class AutoDeletedSecondComment(AutoDeleted):
    """Field:
    - comment_id      评论ID
    """

    comment_id = models.ForeignKey("SecondLevelComment", on_delete=models.CASCADE)

    def get_author(self) -> User:
        return self.comment_id.user_id

    def get_level(self) -> str:
        return "2"

    def get_id(self) -> str:
        return str(self.comment_id.comment_id)

    def get_content(self) -> str:
        return self.comment_id.text

    def mark_content_safe(self):
        self.comment_id.safe()

    def mark_content_blocked(self):
        self.comment_id.block()


class FirstLevelComment(Detectable):
    """
    Field:
        - comment_id         评论ID
        - user_id            用户ID
        - paper_id           文献ID
        - date               评论时间
        - text               评论内容
        - like_count         点赞数
        - liked_by_users     点赞用户
        - visibility         可见性
    """

    comment_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)
    paper_id = models.ForeignKey(Paper, on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now_add=True)
    text = models.TextField()
    like_count = models.IntegerField(default=0)
    liked_by_users = models.ManyToManyField(
        User, related_name="liked_first_level_comments", blank=True
    )

    @staticmethod
    def get_content_name() -> str:
        return "一级评论"

    def insert_auto_delete(self, reason: str = None, title: str = None):
        AutoDeletedFirstComment.objects.create(
            comment_id=self,
            reason=reason,
        )
        Notification.create(
            self.user_id,
            title,
            '您在 {} 的 {} 内容 "{}" 已被平台自动删除，原因为 {}'.format(
                self.check_date.strftime("%Y-%m-%d %H:%M:%S"),
                self.get_content_name(),
                self.text,
                reason,
            ),
        )


class SecondLevelComment(Detectable):
    """
    Field:
        - comment_id         评论ID
        - user_id            用户ID
        - paper_id           文献ID
        - date               评论时间
        - text               评论内容
        - like_count         点赞数
        - level1_comment     一级评论
        - reply_comment      回复评论(针对二级评论的回复才记录）
        - liked_by_users     点赞用户
        - visibility         可见性
    """

    comment_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)
    paper_id = models.ForeignKey(Paper, on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now_add=True)
    text = models.TextField()
    like_count = models.IntegerField(default=0)
    level1_comment = models.ForeignKey(FirstLevelComment, on_delete=models.CASCADE)
    reply_comment = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True
    )
    liked_by_users = models.ManyToManyField(
        User, related_name="liked_second_level_comments", blank=True
    )

    @staticmethod
    def get_content_name() -> str:
        return "二级评论"

    def insert_auto_delete(self, reason: str = None, title: str = None):
        AutoDeletedSecondComment.objects.create(
            comment_id=self,
            reason=reason,
        )
        Notification.create(
            self.user_id,
            title,
            '您在 {} 的 {} 内容 "{}" 已被平台自动删除，原因为 {}'.format(
                self.check_date.strftime("%Y-%m-%d %H:%M:%S"),
                self.get_content_name(),
                self.text,
                reason,
            ),
        )
