import uuid

from django.db import models

from .user import User
from .paper import Paper
from .paper_position import PaperPosition


class AnnotationType(models.IntegerChoices):
    UNDERLINE = 1, "Underline"
    POSTIL = 2, "Postil"

    @staticmethod
    def from_str(s: str):
        if s.lower() == "underline":
            return AnnotationType.UNDERLINE
        elif s.lower() == "postil":
            return AnnotationType.POSTIL
        else:
            raise ValueError(f"Invalid annotation type: {s}")


class PaperAnnotation(models.Model):
    """Field:
    - id              注释ID
    - annotation_type 注释类型
    - position        注释位置
    - content         内容
    - date            创建时间
    - author_id       作者 User 关联
    - paper_id        文献 ID
    - liked_by_user   点赞的用户
    - visibility      可见性
    """

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    annotation_type = models.IntegerField(choices=AnnotationType.choices)
    position = models.ManyToManyField(
        PaperPosition,
        related_name="annotations_position",
        blank=True,
    )
    content = models.TextField(null=True)
    date = models.DateTimeField(auto_now_add=True)
    author_id = models.ForeignKey(User, on_delete=models.CASCADE)
    paper_id = models.ForeignKey(Paper, on_delete=models.CASCADE)
    liked_by_user = models.ManyToManyField(
        User, related_name="liked_annotations", blank=True
    )
    visibility = models.BooleanField(default=True)


class PaperAnnotationCommentFirstLevel(models.Model):
    """Field:
    - comment_id      评论ID
    - author_id       作者 User 关联
    - annotation_id   批注 ID
    - date            创建时间
    - text            评论内容
    - like_by_user    点赞的用户
    - visibility      可见性
    """

    comment_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    author_id = models.ForeignKey(User, on_delete=models.CASCADE)
    annotation_id = models.ForeignKey(PaperAnnotation, on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now_add=True)
    text = models.TextField()
    like_by_user = models.ManyToManyField(
        User, related_name="annotation_liked_first_comments", blank=True
    )
    visibility = models.BooleanField(default=True)


class PaperAnnotationCommentSecondLevel(models.Model):
    """Field:
    - comment_id      评论ID
    - author_id       作者 User 关联
    - annotation_id   批注 ID
    - date            创建时间
    - text            评论内容
    - like_by_user    点赞的用户
    - parent_comment  一级评论
    - reply_comment   回复的二级评论评论
    - visibility      可见性
    """

    comment_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    author_id = models.ForeignKey(User, on_delete=models.CASCADE)
    annotation_id = models.ForeignKey(PaperAnnotation, on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now_add=True)
    text = models.TextField()
    like_by_user = models.ManyToManyField(
        User, related_name="annotation_liked_second_comments", blank=True
    )
    parent_comment = models.ForeignKey(
        PaperAnnotationCommentFirstLevel, on_delete=models.CASCADE
    )
    reply_comment = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True
    )
    visibility = models.BooleanField(default=True)
