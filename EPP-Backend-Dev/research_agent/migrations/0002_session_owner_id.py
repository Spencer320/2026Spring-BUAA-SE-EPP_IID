from django.db import migrations, models


def copy_owner_id(apps, schema_editor):
    ResearchSession = apps.get_model("research_agent", "ResearchSession")
    for session in ResearchSession.objects.all().iterator():
        legacy_user_id = getattr(session, "user_id", None)
        session.owner_id = str(legacy_user_id or "")
        session.save(update_fields=["owner_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("research_agent", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="researchsession",
            name="owner_id",
            field=models.CharField(db_index=True, default="", max_length=128),
            preserve_default=False,
        ),
        migrations.RunPython(copy_owner_id, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="researchsession",
            name="user",
        ),
    ]
