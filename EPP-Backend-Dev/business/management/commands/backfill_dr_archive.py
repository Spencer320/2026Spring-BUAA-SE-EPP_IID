from collections import Counter

from django.core.management.base import BaseCommand

from business.models import DeepResearchTask
from business.utils.deep_research_archive import archive_task


class Command(BaseCommand):
    help = "回填历史 Deep Research 任务归档（completed/aborted/admin_stopped）"

    TARGET_STATUSES = [
        DeepResearchTask.STATUS_COMPLETED,
        DeepResearchTask.STATUS_ABORTED,
        DeepResearchTask.STATUS_ADMIN_STOPPED,
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅统计将要归档的任务，不执行写入",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="最多处理多少条，0 表示不限制",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        limit = int(options.get("limit", 0) or 0)

        queryset = DeepResearchTask.objects.filter(status__in=self.TARGET_STATUSES).order_by(
            "created_at"
        )
        if limit > 0:
            queryset = queryset[:limit]

        candidates = list(queryset.values_list("task_id", "status", "report"))
        total_candidates = len(candidates)
        if total_candidates == 0:
            self.stdout.write(self.style.SUCCESS("没有需要回填归档的历史任务"))
            return

        status_counter = Counter(status for _, status, _ in candidates)
        completed_without_report = sum(
            1
            for _, status, report in candidates
            if status == DeepResearchTask.STATUS_COMPLETED and report is None
        )

        self.stdout.write(
            "检测到待处理任务："
            f" total={total_candidates}, "
            f"completed={status_counter.get(DeepResearchTask.STATUS_COMPLETED, 0)}, "
            f"aborted={status_counter.get(DeepResearchTask.STATUS_ABORTED, 0)}, "
            f"admin_stopped={status_counter.get(DeepResearchTask.STATUS_ADMIN_STOPPED, 0)}"
        )

        if completed_without_report > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"其中 completed 且 report 为空的任务有 {completed_without_report} 条，将跳过"
                )
            )

        if dry_run:
            self.stdout.write(self.style.SUCCESS("dry-run 完成，未执行归档写入"))
            return

        archived_count = 0
        skipped_no_report = 0
        skipped_other = 0

        for task_id, status, report in candidates:
            if status == DeepResearchTask.STATUS_COMPLETED and report is None:
                skipped_no_report += 1
                continue
            ok = archive_task(str(task_id))
            if ok:
                archived_count += 1
            else:
                skipped_other += 1

        self.stdout.write(
            self.style.SUCCESS(
                "回填归档完成："
                f" archived={archived_count}, "
                f"skipped_no_report={skipped_no_report}, "
                f"skipped_other={skipped_other}"
            )
        )
