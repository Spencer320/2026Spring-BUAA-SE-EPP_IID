import json
import os.path
import random
from datetime import datetime

from django.core.management import BaseCommand

from business.models import Paper


class Command(BaseCommand):
    help = """Insert paper into the database. Need a json file to specify the paper information.
    The json file should be like:
    [
        {
            "title": "paper title",
            "authors": ["author1", "author2", ...],
            "abstract": "paper abstract",
            "publication_date": "2022-01-01T00:00:00Z",
            "citation_count": 0,
            "original_url": "https://arxiv.org/abs/xxxx.xxxxx",
            "local_path": "/path/to/paper.pdf"
        },
        ...
    ]
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help="The json file to specify the paper information.",
        )
        parser.add_argument(
            "--deletion",
            action="store_true",
            help="Delete all papers before inserting.",
            default=False,
        )

    def handle(self, *args, **options):
        deletion = options["deletion"]
        json_file = options["json_file"]

        inserted = 0
        if deletion:
            Paper.objects.all().delete()
            print("All papers have been deleted.")

        with open(json_file, "r", encoding="utf-8") as f:
            papers = json.load(f)
            for paper in papers:
                print("Inserting paper: " + paper["title"])
                # 将字符串日期转换为 datetime 对象
                publication_date = datetime.strptime(
                    paper["publication_date"], "%Y-%m-%dT%H:%M:%SZ"
                ).date()
                Paper.objects.create(
                    title=paper["title"],
                    authors=",".join(paper["authors"]),
                    abstract=paper["abstract"],
                    publication_date=publication_date,
                    journal=None,  # 期刊允许为空，arXiv没有
                    citation_count=paper["citation_count"],
                    original_url=paper["original_url"],
                    read_count=random.randint(0, 1000),
                    like_count=0,
                    collect_count=0,
                    comment_count=0,
                    download_count=random.randint(0, 1000),
                    local_path=os.path.abspath(paper["local_path"]),
                )
                inserted += 1

        # 默认策略：只要发生新增或删除，就重建本地 FAISS 索引
        if deletion or inserted > 0:
            from business.utils.paper_vdb_init import build_local_faiss_index

            print("[FAISS] Rebuilding local index...")
            info = build_local_faiss_index()
            print(f"[FAISS] Done. {info}")
