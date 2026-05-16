# ResearchMessage.metadata：工作区引用等每消息扩展字段

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("research_agent", "0008_research_paper_shelf_item"),
    ]

    operations = [
        migrations.AddField(
            model_name="researchmessage",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
