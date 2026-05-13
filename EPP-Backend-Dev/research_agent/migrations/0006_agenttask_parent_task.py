# Generated manually for delegate subtasks + audit retention

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("research_agent", "0005_siteaccesspolicyconfig_siteaccessrule"),
    ]

    operations = [
        migrations.AddField(
            model_name="agenttask",
            name="parent_task",
            field=models.ForeignKey(
                blank=True,
                help_text="非空表示由父任务编排器派生的子任务（如工作区 delegate），保留以供审计与追溯。",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="child_tasks",
                to="research_agent.agenttask",
            ),
        ),
    ]
