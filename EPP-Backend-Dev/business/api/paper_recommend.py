"""
用于热门文献推荐，热门文献推荐基于用户的搜索历史，点赞历史，收藏历史

几乎所有推荐系统都是有着前后顺序的，但是我们的没有这些，这也就意味着我们的推荐系统是一个无状态的推荐系统
所以我选择了从arXiv上爬取最近一周的cv的每天10篇论文，然后通过总结这些论文的关键词，来进行推荐
"""

import re
from typing import Tuple, List

from django.views.decorators.http import require_http_methods

from business.utils.authenticate import authenticate_user
from business.utils.container_helper import truncate_dict_keys, unique_list
from business.utils.paper_vdb_init import get_filtered_paper

# 定时调用这个接口
# yourappname/tasks.py

from business.utils.response import ok
from business.models import Paper, User
import random
import requests

from xml.etree import ElementTree

from business.utils.chat_glm import query_glm


class ArxivPaper:
    def __init__(self, title, summary, published, url, authors):
        self.title = title
        self.summary = summary
        self.published = published
        self.url = url
        self.authors = authors

    def __str__(self):
        return f"Title: {self.title}\nSummary: {self.summary}\nPublished: {self.published}\nURL: {self.url}\nAuthor: {self.authors}\n"

    def __dict__(self):
        author_str = ""
        for author in self.authors:
            author_str += author + ","
        return {
            "title": self.title,
            "summary": self.summary,
            "published": self.published,
            "url": self.url,
            "author": author_str,
        }


def get_authors(entry):
    authors = []
    author_nodes = entry.findall("{http://www.w3.org/2005/Atom}author")
    for author_node in author_nodes:
        author_name = author_node.find("{http://www.w3.org/2005/Atom}name").text
        authors.append(author_name)
    return authors


def query_arxiv_by_date_and_field(
    start_date=None, end_date=None, field="computer vision", max_results=20
) -> list[ArxivPaper]:
    query = f"all:{field}"
    if start_date and end_date:
        query = f"submittedDate:[{start_date} TO {end_date}] AND " + query
    url = (
        f"http://arxiv.org/api/query?search_query={query}&id_list=&start=0&max_results={max_results}&"
        f"sortBy=lastUpdatedDate&sortOrder=descending"
    )
    print("query url: ", url)
    response = requests.get(url)
    papers = []
    if response.status_code == 200:
        root = ElementTree.fromstring(response.content)
        total_results = root.find(
            ".//{http://a9.com/-/spec/opensearch/1.1/}totalResults"
        ).text
        print(f"Total Results: {total_results}")
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = entry.find("{http://www.w3.org/2005/Atom}title").text
            summary = entry.find("{http://www.w3.org/2005/Atom}summary").text
            published = entry.find("{http://www.w3.org/2005/Atom}published").text
            url = entry.find("{http://www.w3.org/2005/Atom}id").text
            authors = get_authors(entry)
            print("author:", authors)
            paper_instance = ArxivPaper(title, summary, published, url, authors)
            papers.append(paper_instance)
    else:
        print("Failed to fetch data.")
    return papers


def refresh_cache():
    # 获取前一周的所有论文 -> 改成：获取最新的20篇论文
    papers = query_arxiv_by_date_and_field()
    # 从中提取关键词
    keywords = []
    for paper in papers:
        msg = (
            "这是一段关于"
            + paper.title
            + "的摘要，帮我总结三个关键词：\n"
            + paper.summary
            + '\n输出格式：每行一个关键词，使用"1."，"2."等标号'
        )
        rsp = query_glm(msg).split("\n")
        keywords += map(lambda s: re.sub("\\d+\\.", "", s).strip(), rsp)

    # 从关键词中提取论文
    key = query_glm(
        msg="帮我从这些关键词中提取出来十个关键词：" + ",".join(keywords),
        history=[],
    )
    from business.utils.paper_vdb_init import get_filtered_paper

    papers = get_filtered_paper(key, k=10)
    # 将推荐数据缓存一天
    info = []
    for paper in papers:
        info.append(paper.paper_id)
    cache.set("recommended_papers", info, timeout=86400)


from django.core.cache import cache


@authenticate_user
@require_http_methods(["GET"])
def get_recommendation(request, user: User):
    # 尝试从缓存中获取推荐数据
    cached_papers = cache.get("recommended_papers")
    if cached_papers:
        return ok(
            data={
                "papers": [
                    Paper.objects.get(paper_id=paper_id).to_dict()
                    for paper_id in cached_papers
                ]
            },
            msg="success",
        )
    else:
        # 挂一个线程去刷新缓存
        import threading

        t = threading.Thread(target=refresh_cache)
        t.start()
    # 从数据库中获取所有 Paper 对象的 ID
    papers_ids = list(Paper.objects.values_list("paper_id", flat=True))
    # 随机选择五篇论文的 ID
    selected_paper_ids = random.sample(papers_ids, min(10, len(papers_ids)))
    # 获取选中论文的详细信息
    selected_papers = []
    for paper_id in selected_paper_ids:
        paper = Paper.objects.get(paper_id=paper_id)
        selected_papers.append(paper)
    # 将选中的论文对象转换为字典
    papers = [paper.to_dict() for paper in selected_papers]
    # 将推荐数据缓存一天
    cache.set(
        "recommended_papers",
        [paper.paper_id for paper in selected_papers],
        timeout=86400,
    )

    return ok(data={"papers": papers}, msg="success")


@authenticate_user
@require_http_methods(["GET"])
def individuation_recommend(request, user: User):
    cached_papers = cache.get("individuation_recommend")
    if (
        cached_papers
        and str(user.user_id) in cached_papers
        and len(cached_papers[str(user.user_id)]) > 0
    ):
        return ok(data={"papers": cached_papers[str(user.user_id)]}, msg="success")

    recommend_papers = []
    # 收藏的论文
    like_papers = list(user.liked_papers.all())
    random.shuffle(like_papers)
    if len(like_papers) > 4:
        like_papers = like_papers[:4]

    recommend_papers += _recommend_paper_by_semantic(like_papers, "你点赞的论文")
    recommend_papers += _recommend_paper_by_author(like_papers, "你点赞的论文")

    # 收集的论文
    collect_papers = list(user.collected_papers.all())
    random.shuffle(collect_papers)
    if len(collect_papers) > 4:
        collect_papers = collect_papers[:4]
    recommend_papers += _recommend_paper_by_semantic(collect_papers, "你收藏的论文")
    recommend_papers += _recommend_paper_by_author(collect_papers, "你收藏的论文")

    # 这里去重，因为在不同时调用 _recommend_* 函数时，可能有重复的论文
    recommend_papers = unique_list(recommend_papers, key=lambda x: str(x[0].paper_id))
    # 还有研读记录？
    random.shuffle(recommend_papers)
    if len(recommend_papers) > 20:
        recommend_papers = recommend_papers[:20]
    papers = [
        truncate_dict_keys(paper.to_dict(), ["paper_id", "title"])
        | {"reason": reason, "sub_classes": ["热门推荐"]}
        for paper, reason in recommend_papers
    ]

    # 将推荐数据缓存一天
    if cached_papers:
        cached_papers[str(user.user_id)] = papers
    else:
        cached_papers = {str(user.user_id): papers}
    cache.set("individuation_recommend", cached_papers, timeout=86400)

    return ok(data={"papers": papers}, msg="success")


def _recommend_paper_by_author(
    ref_papers: List[Paper], origin, limits=4
) -> List[Tuple[Paper, str]]:
    recommend_papers: List[Tuple[Paper, str]] = []
    exclude_id = [p.paper_id for p in ref_papers]
    for ref_paper in ref_papers:
        authors = list(map(str.strip, str(ref_paper.authors).split(",")))[:2]
        for author in authors:
            papers = Paper.objects.filter(authors__icontains=author).order_by(
                "-citation_count"
            )[:2]
            recommend_papers += [
                (paper, f"这是{origin}：{ref_paper}的作者{author}发表的论文")
                for paper in papers
            ]
    filtered_recommend_papers = [
        (paper, reason)
        for paper, reason in recommend_papers
        if paper.paper_id not in exclude_id
    ]
    random.shuffle(filtered_recommend_papers)
    return filtered_recommend_papers[:limits]


def _recommend_paper_by_semantic(
    ref_papers: List[Paper], origin: str, limits=4
) -> List[Tuple[Paper, str]]:
    recommend_papers: List[Tuple[Paper, str]] = []
    for ref_paper in ref_papers:
        papers = get_filtered_paper(ref_paper.abstract, 5, 0.5)
        recommend_papers += [
            (paper, f"该论文与{origin}：{ref_paper}相似") for paper in papers
        ]

    exclude_id = [paper.paper_id for paper in ref_papers]
    filtered_recommend_papers = [
        (paper, reason)
        for paper, reason in recommend_papers
        if paper.paper_id not in exclude_id
    ]
    random.shuffle(filtered_recommend_papers)
    return filtered_recommend_papers[:limits]
