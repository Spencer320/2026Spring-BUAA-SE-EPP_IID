import json
import os.path
import random
from datetime import datetime

from django.core.management import BaseCommand

from business.models import Paper, Glossary, GlossaryTerm


class Command(BaseCommand):
    help = """Insert glossaries into the database. Need a json file to specify the glossary information.
    The json file should be like:
    [
        {
            "name": "glossary table title",
            "glossary": [
                {
                    "term": "glossary term",
                    "translation": "glossary translation",
                }
            ]
        },
        ...
    ]
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help="The json file to specify the glossary information.",
        )
        parser.add_argument(
            "--deletion",
            action="store_true",
            help="Delete all glossaries before inserting.",
            default=False,
        )

    def handle(self, *args, **options):
        deletion = options["deletion"]
        json_file = options["json_file"]

        if deletion:
            Glossary.objects.all().delete()
            print("All glossaries have been deleted.")

        with open(json_file, "r", encoding="utf-8") as f:
            for glossary in json.load(f):
                name = glossary["name"]
                glossary_terms = glossary["glossary"]
                glossary_obj = Glossary.objects.create(name=name)
                for term in glossary_terms:
                    term_obj = GlossaryTerm.objects.create(
                        parent_glossary=glossary_obj,
                        term=term["term"],
                        translation=term["translation"],
                    )
                    glossary_obj.terms.add(term_obj)
