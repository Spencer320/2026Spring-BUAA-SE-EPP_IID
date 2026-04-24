from collections import Counter
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from business.models import DeepResearchTask, DeepResearchTaskArchive, User
from business.tests.helper_user import insert_user


class TestBackfillDrArchiveCommand(TestCase):
    def setUp(self):
        self.username, _ = insert_user()
        self.user = User.objects.get(username=self.username)

    def _create_pending_task(self, query: str) -> DeepResearchTask:
        return DeepResearchTask.objects.create(
            user=self.user,
            query=query,
            status=DeepResearchTask.STATUS_PENDING,
        )

    def test_backfill_archive_for_supported_terminal_statuses(self):
        completed_task = self._create_pending_task("completed")
        aborted_task = self._create_pending_task("aborted")
        admin_stopped_task = self._create_pending_task("admin_stopped")

        now = timezone.now()
        DeepResearchTask.objects.filter(task_id=completed_task.task_id).update(
            status=DeepResearchTask.STATUS_COMPLETED,
            report={"title": "completed report", "citations": [{"name": "ref-1"}]},
            finished_at=now,
            token_used_total=99,
        )
        DeepResearchTask.objects.filter(task_id=aborted_task.task_id).update(
            status=DeepResearchTask.STATUS_ABORTED,
            finished_at=now,
        )
        DeepResearchTask.objects.filter(task_id=admin_stopped_task.task_id).update(
            status=DeepResearchTask.STATUS_ADMIN_STOPPED,
            finished_at=now,
        )

        stdout = StringIO()
        call_command("backfill_dr_archive", stdout=stdout)

        completed_task.refresh_from_db()
        aborted_task.refresh_from_db()
        admin_stopped_task.refresh_from_db()

        self.assertEqual(completed_task.status, DeepResearchTask.STATUS_ARCHIVED)
        self.assertEqual(aborted_task.status, DeepResearchTask.STATUS_ARCHIVED)
        self.assertEqual(admin_stopped_task.status, DeepResearchTask.STATUS_ARCHIVED)

        archives = DeepResearchTaskArchive.objects.all()
        self.assertEqual(archives.count(), 3)

        status_counter = Counter(archives.values_list("terminal_status", flat=True))
        self.assertEqual(status_counter[DeepResearchTask.STATUS_COMPLETED], 1)
        self.assertEqual(status_counter[DeepResearchTask.STATUS_ABORTED], 1)
        self.assertEqual(status_counter[DeepResearchTask.STATUS_ADMIN_STOPPED], 1)

        self.assertIn("archived=3", stdout.getvalue())

    def test_backfill_dry_run_does_not_write(self):
        task = self._create_pending_task("dry-run aborted")
        DeepResearchTask.objects.filter(task_id=task.task_id).update(
            status=DeepResearchTask.STATUS_ABORTED,
            finished_at=timezone.now(),
        )

        stdout = StringIO()
        call_command("backfill_dr_archive", dry_run=True, stdout=stdout)

        task.refresh_from_db()
        self.assertEqual(task.status, DeepResearchTask.STATUS_ABORTED)
        self.assertFalse(
            DeepResearchTaskArchive.objects.filter(task=task).exists()
        )
        self.assertIn("dry-run 完成", stdout.getvalue())
