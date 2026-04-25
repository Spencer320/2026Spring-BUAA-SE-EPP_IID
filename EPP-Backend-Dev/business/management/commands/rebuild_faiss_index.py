from django.core.management import BaseCommand


class Command(BaseCommand):
    help = "Rebuild local FAISS index (paper_index.faiss + paper_metadata.pkl)."

    def handle(self, *args, **options):
        from business.utils.paper_vdb_init import build_local_faiss_index

        self.stdout.write("Rebuilding local FAISS index...")
        info = build_local_faiss_index()
        self.stdout.write(self.style.SUCCESS(f"Done. {info}"))
