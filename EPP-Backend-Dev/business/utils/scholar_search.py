from difflib import SequenceMatcher
import requests

from business.utils.chat_glm import query_glm
from business.utils.chat_r1 import query_r1


def fuzzy_match(query, choice, threshold=0.8):
    if not query:
        return True
    return SequenceMatcher(None, query, choice).ratio() >= threshold


def search_author(
    author_name: str, affiliation: str, chinese_name: str | None = None
) -> tuple[bool, str]:
    name = author_name.strip().replace(" ", "%20")
    print(f"[search_author] author_name {author_name}; affiliation {affiliation}")
    url = f"https://api.openalex.org/authors?filter=display_name.search:{name}"
    print("[search_author] 查询网址：", url)
    response = requests.get(url)
    if response.status_code != 200:
        return False, "Network Error"
    authors = response.json()["results"]

    target_author = {}

    for author in authors:
        if not fuzzy_match(author_name, author["display_name"]):
            continue
        for aff in author["last_known_institutions"]:
            print("aff: ", aff["display_name"])
            if isinstance(aff, dict) and fuzzy_match(affiliation, aff["display_name"]):
                target_author = author
                break
        if target_author:
            break

    if not target_author:
        print("[search_author] 结果：", False)
        return False, "Could not get information about the author."

    source_represent = "以下数据由openalex统计"
    standard_name = target_author["display_name"]
    name_represent = (
        (chinese_name + f"（{standard_name}）") if chinese_name else standard_name
    )
    institutions = target_author.get("last_known_institutions", [])
    current_affiliation = [institution["display_name"] for institution in institutions]
    affiliation_represent = (
        ("现任职于" + "、".join(current_affiliation) + "机构")
        if current_affiliation
        else ""
    )

    try:
        total_represent = (
            "发表论文数量"
            + str(target_author["works_count"])
            + "，引用量"
            + str(target_author["cited_by_count"])
            + "。"
        )
    except:
        total_represent = ""

    try:
        influence_represent = (
            f"过去两年文章平均被引用数："
            + str(target_author["summary_stats"]["2yr_mean_citedness"])
            + "；H指数"
            + str(target_author["summary_stats"]["h_index"])
            + "；i10指数"
            + str(target_author["summary_stats"]["i10_index"])
        )
    except:
        influence_represent = ""

    concepts = target_author.get("x_concepts", [])

    core_concepts = [
        c for c in concepts if c.get("score", 0) > 60 and c.get("level", 0) == 0
    ]
    if len(core_concepts) > 2:
        core_concepts = core_concepts[:2]
    concepts_represent = (
        "是" + "、".join([c["display_name"] for c in core_concepts]) + "领域的专家"
        if core_concepts
        else ""
    )

    topics = target_author.get("topics", [])
    if len(topics) > 5:
        topics = topics[:5]
    topic_names = [t["display_name"] for t in topics]
    topic_represent = ("其研究领域包括" + "、".join(topic_names)) if topic_names else ""

    represent = (
        source_represent
        + "："
        + (chinese_name if chinese_name else name_represent)
        + "，"
        + affiliation_represent
        + "，"
        + concepts_represent
        + "，"
        + topic_represent
        + "，"
        + total_represent
        + "，"
        + influence_represent
    )
    print("[search_author] raw：", represent)
    revise_prompt = f"请将这段话组织成一个连贯的中文段落：{represent}"
    result = query_glm(revise_prompt)
    print("[search_author] 润色结果：", result)
    return True, result


def search_entity(
    entity_name: str, chinese_name: str | None = None
) -> tuple[bool, str]:
    name = entity_name.strip().replace(" ", "%20")
    url = f"https://api.openalex.org/autocomplete/institutions?q={name}"
    print("[search_author] 查询网址：", url)
    response = requests.get(url)
    if response.status_code != 200:
        return False, "Network Error"
    entity = response.json()["results"][0]
    standard_name = entity["display_name"]
    name_represent = (
        (chinese_name + f"（{standard_name}）") if chinese_name else standard_name
    )
    info = (
        f"类型："
        + str(entity.get("entity_type", ""))
        + f"，信息："
        + str(entity.get("hint", ""))
        + f"，论文数量："
        + str(entity.get("works_count", ""))
        + f"，引用量："
        + str(entity.get("cited_by_count", ""))
    )

    raw = "以下内容来自openalex：" + name_represent + "：" + info
    revise_prompt = f"请将这段话组织成一个连贯的中文段落：{raw}"
    result, _ = query_r1(revise_prompt)
    return True, result


if __name__ == "__main__":
    pass
