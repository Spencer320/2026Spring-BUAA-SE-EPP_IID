import uuid

from django.db import models

from .user import User
from .paper_position import PaperPosition
from .paper import Paper
from .user_document import UserDocument


class PaperNoteType(models.IntegerChoices):
    HIGHLIGHT = 1, "Highlight"
    NOTES = 2, "Notes"
    SUMMARY = 3, "Summary"

    @staticmethod
    def from_str(s: str):
        if s.lower() == "highlight":
            return PaperNoteType.HIGHLIGHT
        elif s.lower() == "notes":
            return PaperNoteType.NOTES
        elif s.lower() == "summary":
            return PaperNoteType.SUMMARY
        else:
            raise ValueError(f"Invalid note type: {s}")


class NoteCore(models.Model):
    """Do not include this model directly in the database

    Field:
        - note_id         笔记ID
        - contents        笔记内容
        - author_id       作者 User 关联
        - date            创建时间
    """

    note_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    author_id = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, null=True)
    date = models.DateTimeField(auto_now_add=True)
    contents = models.JSONField(null=True)
    markdown = models.TextField(null=True, default="")

    class Meta:
        abstract = True


class PaperNote(NoteCore):
    paper_id = models.ForeignKey(Paper, on_delete=models.CASCADE)


class UserDocumentNote(NoteCore):
    user_document_id = models.ForeignKey(UserDocument, on_delete=models.CASCADE)
