import base64
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from business.models import Paper, Subclass
from business.utils.download_paper import download_paper


LEGACY_SUBCLASS_NAMES = [
    "边缘检测",
    "目标检测",
    "图像分类",
    "图像去噪",
    "图像分割",
    "人脸识别",
    "姿态估计",
    "动作识别",
    "人群计数",
    "医学影像",
    "三维重建",
    "对抗样本攻击",
]

DEFAULT_AVATAR_JPEG = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////////////"
    "////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/"
    "xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/ASP/xAAUEQEAAAAAAAAAAAAA"
    "AAAAAAAA/9oACAECAQE/ASP/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Aqf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/"
    "IaP/2gAMAwEAAgADAAAAEP/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8Q"
    "H//EABQQAQAAAAAAAAAAAAAAAAAAABD/2gAIAQEAAT8QH//Z"
)


class Command(BaseCommand):
    help = "Initialize legacy feature data required by the review server."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync-pdfs",
            action="store_true",
            help="Try to download PDFs whose local_path cannot be resolved.",
        )
        parser.add_argument(
            "--classify",
            action="store_true",
            help="Use the ChatGLM embedding service for precise subclass classification.",
        )

    def handle(self, *args, **options):
        self._ensure_avatar_assets()
        subclasses = self._ensure_subclasses()
        self._fix_paper_local_paths(sync_pdfs=options["sync_pdfs"])

        if options["classify"]:
            self._classify_with_embedding()
        else:
            self._fill_empty_paper_subclasses(subclasses)

        self.stdout.write(self.style.SUCCESS("Legacy server data initialized."))

    def _ensure_avatar_assets(self):
        avatar_dir = Path(settings.BASE_DIR) / settings.USER_AVATARS_PATH
        avatar_dir.mkdir(parents=True, exist_ok=True)
        default_avatar = avatar_dir / "default.jpg"
        if not default_avatar.exists():
            default_avatar.write_bytes(base64.b64decode(DEFAULT_AVATAR_JPEG))
            self.stdout.write(f"Created default avatar: {default_avatar}")

    def _ensure_subclasses(self):
        existing = {item.name: item for item in Subclass.objects.all()}
        for name in LEGACY_SUBCLASS_NAMES:
            if name not in existing:
                existing[name] = Subclass.objects.create(name=name)
        return [existing[name] for name in LEGACY_SUBCLASS_NAMES]

    def _fix_paper_local_paths(self, *, sync_pdfs: bool):
        papers_dir = Path(settings.BASE_DIR) / settings.PAPERS_PATH
        papers_dir.mkdir(parents=True, exist_ok=True)
        changed = 0

        for paper in Paper.objects.all():
            current = self._resolve_existing_path(paper.local_path)
            if current is None:
                current = self._find_existing_pdf(papers_dir, paper)
            if current is None and sync_pdfs:
                downloaded = download_paper(paper.original_url, str(paper.paper_id))
                current = self._resolve_existing_path(downloaded)
            if current is not None and paper.local_path != str(current):
                paper.local_path = str(current)
                paper.save(update_fields=["local_path"])
                changed += 1

        self.stdout.write(f"Fixed local_path for {changed} paper(s).")

    def _resolve_existing_path(self, raw_path):
        if not raw_path:
            return None
        path = Path(str(raw_path))
        candidates = [path]
        if not path.is_absolute():
            candidates.append(Path(settings.BASE_DIR) / path)
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _find_existing_pdf(self, papers_dir: Path, paper: Paper):
        candidates = [papers_dir / f"{paper.paper_id}.pdf"]
        if paper.local_path:
            candidates.append(papers_dir / Path(str(paper.local_path)).name)
        if paper.original_url:
            original_name = paper.original_url.rstrip("/").split("/")[-1]
            if original_name and not original_name.endswith(".pdf"):
                original_name += ".pdf"
            if original_name:
                candidates.append(papers_dir / original_name)
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _fill_empty_paper_subclasses(self, subclasses):
        if not subclasses:
            return
        filled = 0
        for index, paper in enumerate(Paper.objects.all().order_by("paper_id")):
            if paper.sub_classes.exists():
                continue
            paper.sub_classes.add(subclasses[index % len(subclasses)])
            filled += 1
        self.stdout.write(f"Filled subclass for {filled} paper(s).")

    def _classify_with_embedding(self):
        from business.utils.classification import classify

        for paper in Paper.objects.all():
            paper.sub_classes.clear()
        classify()
        self.stdout.write("Classified papers with embedding service.")
