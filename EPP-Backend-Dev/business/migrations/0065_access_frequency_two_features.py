# Generated manually: 访问频次功能类型收敛为「深度研究」「科研助手」

from django.db import migrations, models


FEATURE_CHOICES = [
    ("deep_research", "深度研究"),
    ("research_assistant", "科研助手"),
]

LEGACY_FEATURES = ("ai_chat", "summary", "export")


def purge_legacy_feature_rows(apps, schema_editor):
    for model_name in (
        "AccessFrequencyRule",
        "UserAccessQuotaOverride",
        "AccessConcurrencyRule",
        "UserAccessConcurrencyOverride",
        "FeatureAccessLog",
    ):
        Model = apps.get_model("business", model_name)
        Model.objects.filter(feature__in=LEGACY_FEATURES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("business", "0064_remove_business_deep_research"),
    ]

    operations = [
        migrations.RunPython(purge_legacy_feature_rows, migrations.RunPython.noop),
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
