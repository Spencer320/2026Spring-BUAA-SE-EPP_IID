# Generated manually: remove obsolete business Deep Research models and tables.

from django.db import migrations, models


FEATURE_CHOICES = [
    ("ai_chat", "AI 对话（研读/调研助手）"),
    ("summary", "综述报告生成"),
    ("export", "报告批量导出"),
]


def purge_deep_research_feature_rows(apps, schema_editor):
    for model_name in (
        "AccessFrequencyRule",
        "UserAccessQuotaOverride",
        "AccessConcurrencyRule",
        "UserAccessConcurrencyOverride",
        "FeatureAccessLog",
    ):
        Model = apps.get_model("business", model_name)
        Model.objects.filter(feature="deep_research").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("business", "0063_accessconcurrencyrule_useraccessconcurrencyoverride"),
    ]

    operations = [
        migrations.RunPython(purge_deep_research_feature_rows, migrations.RunPython.noop),
        migrations.DeleteModel(
            name="DeepResearchTaskArchive",
        ),
        migrations.DeleteModel(
            name="DeepResearchAuditLog",
        ),
        migrations.DeleteModel(
            name="DeepResearchStep",
        ),
        migrations.DeleteModel(
            name="DeepResearchTask",
        ),
        migrations.AlterField(
            model_name="accessfrequencyrule",
            name="feature",
            field=models.CharField(
                choices=FEATURE_CHOICES,
                max_length=32,
                unique=True,
                verbose_name="功能类型",
            ),
        ),
        migrations.AlterField(
            model_name="useraccessquotaoverride",
            name="feature",
            field=models.CharField(
                choices=FEATURE_CHOICES,
                max_length=32,
                verbose_name="功能类型",
            ),
        ),
        migrations.AlterField(
            model_name="accessconcurrencyrule",
            name="feature",
            field=models.CharField(
                choices=FEATURE_CHOICES,
                max_length=32,
                unique=True,
                verbose_name="功能类型",
            ),
        ),
        migrations.AlterField(
            model_name="useraccessconcurrencyoverride",
            name="feature",
            field=models.CharField(
                choices=FEATURE_CHOICES,
                max_length=32,
                verbose_name="功能类型",
            ),
        ),
    ]
