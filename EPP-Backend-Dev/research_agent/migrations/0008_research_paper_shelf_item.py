# 会话论文展示区：ResearchPaperShelfItem

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("research_agent", "0007_split_orchestration_runs"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResearchPaperShelfItem",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "source_kind",
                    models.CharField(
                        choices=[
                            ("external_link", "external_link"),
                            ("workspace_file", "workspace_file"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("display_title", models.CharField(max_length=512)),
                ("authors", models.TextField(blank=True, default="")),
                ("abstract", models.TextField(blank=True, default="")),
                ("primary_url", models.CharField(blank=True, default="", max_length=2048)),
                ("workspace_rel_path", models.CharField(blank=True, default="", max_length=1024)),
                ("file_extension", models.CharField(blank=True, default="", max_length=32)),
                (
                    "context_tier",
                    models.CharField(
                        choices=[
                            ("abstract_only", "abstract_only"),
                            ("link_only", "link_only"),
                            ("full_text_available", "full_text_available"),
                            ("workspace_opaque", "workspace_opaque"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("dedupe_key", models.CharField(db_index=True, max_length=512)),
                ("added_via", models.CharField(blank=True, default="", max_length=32)),
                ("search_query", models.CharField(blank=True, default="", max_length=512)),
                ("source_detail", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="paper_shelf_items",
                        to="research_agent.researchsession",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="researchpapershelfitem",
            constraint=models.UniqueConstraint(
                fields=("session", "dedupe_key"),
                name="ra_paper_shelf_session_dedupe",
            ),
        ),
    ]
