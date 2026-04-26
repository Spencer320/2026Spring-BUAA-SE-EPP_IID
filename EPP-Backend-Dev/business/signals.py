from django.db.models.signals import post_save
from django.dispatch import receiver

from business.models.deep_research_task import DeepResearchStep, DeepResearchTask
from business.utils.deep_research_archive import (
    AUTO_ARCHIVE_TERMINAL_STATUSES,
    archive_task,
)
from business.utils.deep_research_compliance import audit_report_async, audit_step_async


@receiver(post_save, sender=DeepResearchStep)
def deep_research_step_created(sender, instance: DeepResearchStep, created: bool, **kwargs):
    if not created:
        return
    audit_step_async(instance.pk)


@receiver(post_save, sender=DeepResearchTask)
def deep_research_report_updated(
    sender,
    instance: DeepResearchTask,
    created: bool,
    update_fields=None,
    **kwargs,
):
    if instance.report is None:
        return
    if update_fields is not None and "report" not in set(update_fields):
        return
    if created or update_fields is None or "report" in set(update_fields):
        audit_report_async(str(instance.task_id), instance.report)
    if instance.status == DeepResearchTask.STATUS_COMPLETED:
        archive_task(str(instance.task_id))


@receiver(post_save, sender=DeepResearchTask)
def deep_research_task_terminal_auto_archive(
    sender,
    instance: DeepResearchTask,
    created: bool,
    update_fields=None,
    **kwargs,
):
    if instance.status == DeepResearchTask.STATUS_ARCHIVED:
        return

    if instance.status not in AUTO_ARCHIVE_TERMINAL_STATUSES:
        return

    # 降低无关字段更新触发归档开销
    if update_fields is not None and "status" not in set(update_fields):
        return

    archive_task(str(instance.task_id))
