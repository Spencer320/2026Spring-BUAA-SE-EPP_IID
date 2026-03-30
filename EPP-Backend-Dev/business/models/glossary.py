import uuid

from django.db import models


class GlossaryTerm(models.Model):
    term_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    term = models.CharField(max_length=255)
    translation = models.CharField(max_length=255)
    parent_glossary = models.ForeignKey(
        "Glossary", on_delete=models.CASCADE, related_name="terms"
    )


class Glossary(models.Model):
    glossary_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    name = models.CharField(max_length=255)
