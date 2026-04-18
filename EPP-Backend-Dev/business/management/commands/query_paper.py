import json
import re
from time import sleep
from urllib import parse as urllib
from datetime import datetime, timedelta
from xml.etree import ElementTree

import requests
from django.core.management import BaseCommand

from business.api.paper_recommend import ArxivPaper
from business.models import Paper

XMLNS = "{http://www.w3.org/2005/Atom}"


def build_arxiv_url(
    start_time: datetime, end_time: datetime, field: str, max_results: int = 200
):
    """
    Build the arXiv API URL for querying papers based on field.
    """
    base_url = "http://export.arxiv.org/api/query?"
    query = f"all:{urllib.quote(field)}+AND+submittedDate:[{start_time.strftime('%Y%m%d0000')}+TO+{end_time.strftime('%Y%m%d2359')}]"
    return f"{base_url}search_query={query}&id_list=&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"


def replace_new_line(text):
    """
    Replace new line characters with spaces.
    """
    return re.sub(r"\s+", " ", text)


class Command(BaseCommand):
    help = """Query papers from arXiv based on a keyword and time range.
    The json file should be like:
    [
      {
        "keyword": "computer vision",
        "recent-days": 7,
        "max-count": 30
      },
      {
        "keyword": "machine learning",
        "recent-days": 7,
        "max-count": 30
      }
    ]
    The "recent-days" field is optional and defaults to 7 days. And the "max-count" field is optional and defaults to 200.
    The date range is from the current date minus "recent-days" to the current date.
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help="The json file to specify the query strategy.",
        )

    def handle(self, *args, **options):
        json_file = options["json_file"]
        query_strategy = json.load(open(json_file, "r", encoding="utf-8"))
        now_date = datetime.now()
        for i, strategy in enumerate(query_strategy):
            print(f"===== Processing strategy {i + 1} =====")

            recent_days = strategy.get("recent-days", 7)
            start_date = now_date - timedelta(days=recent_days)
            keyword = strategy["keyword"]
            max_results = strategy.get("max-count", 200)

            url = build_arxiv_url(start_date, now_date, keyword, max_results)
            print(f"Querying ArXiv with URL: {url}...", end=" ", flush=True)
            response = requests.get(url)
            print(f"Done.")

            if response.status_code != 200:
                print(f"Failed to fetch data. Status code: {response.status_code}")
                continue
            else:
                print(f"Successfully fetched data.")

            print("====== Parsing results =====")
            root = ElementTree.fromstring(response.content)
            papers = []
            for entry in root.findall(f".//{XMLNS}entry"):
                title = replace_new_line(entry.find(XMLNS + "title").text)
                summary = replace_new_line(entry.find(XMLNS + "summary").text)
                published = entry.find(XMLNS + "published").text
                url = entry.find(XMLNS + "id").text
                authors = [
                    node.find(XMLNS + "name").text
                    for node in entry.findall(XMLNS + "author")
                ]
                paper_instance = ArxivPaper(title, summary, published, url, authors)
                papers.append(paper_instance)

            print("====== Query Result =====")
            print(f"Total Results: {len(papers)}")

            print("====== Saving results =====")
            origin_count = Paper.objects.count()
            for paper in papers:
                if Paper.objects.filter(title=paper.title).exists():
                    print(f"Paper '{paper.title}' already exists. Skipping...")
                    continue
                Paper.objects.create(
                    title=paper.title,
                    authors=",".join(paper.authors),
                    abstract=paper.summary,
                    publication_date=datetime.strptime(
                        paper.published, "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    journal=None,
                    citation_count=0,  # TODO
                    original_url=paper.url,
                    read_count=0,
                    like_count=0,
                    collect_count=0,
                    comment_count=0,
                    download_count=0,
                    local_path="",
                )
            new_count = Paper.objects.count()
            print(
                f"Inserted {new_count - origin_count} new papers. ({origin_count} -> {new_count})"
            )

            print("====== Done =====\n")
            sleep(1)
