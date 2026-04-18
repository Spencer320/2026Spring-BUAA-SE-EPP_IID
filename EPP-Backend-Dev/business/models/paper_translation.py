import uuid

from django.db import models

from . import User
from .glossary import Glossary
from .paper import Paper
from .user_document import UserDocument


class TranslationStatus(models.IntegerChoices):
    Working = 0, "Working"
    Success = 1, "Success"
    Failed = 2, "Failed"


class TranslationCore(models.Model):
    translation_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    date = models.DateTimeField(auto_now_add=True)
    result_path = models.CharField(max_length=255, null=True)
    glossary = models.ForeignKey(Glossary, on_delete=models.CASCADE, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    task_id = models.CharField(max_length=255, null=True)
    task_status = models.IntegerField(
        choices=TranslationStatus.choices, default=TranslationStatus.Working
    )

    class Meta:
        abstract = True


class PaperTranslation(TranslationCore):
    paper = models.ForeignKey(
        Paper, on_delete=models.CASCADE, related_name="paper_translations"
    )


class UserDocumentTranslation(TranslationCore):
    user_document = models.ForeignKey(
        UserDocument,
        on_delete=models.CASCADE,
        related_name="user_document_translations",
    )


def query_one_translation(
    **kwargs,
) -> PaperTranslation | UserDocumentTranslation | None:
    translate = PaperTranslation.objects.filter(**kwargs).first()
    if translate is None:
        translate = UserDocumentTranslation.objects.filter(**kwargs).first()
    return translate
