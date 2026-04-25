"""
本文件主要用于文献综述生成，包括单篇文献的综述生成和多篇文献的综述生成
path : /api/summary/...
"""

import datetime
import json
import queue
import re
import threading

import fitz

# import requests # Not adding, assuming it's available from other imports like business.api.search
from django.conf import settings
from django.views.decorators.http import require_http_methods

from business.api.search import (
    kb_ask_ai,
    extract_reference_info,
    answer2dict,
    answer2list,
    pdf_to_txt,
)
from business.models import (
    User,
    UserDocument,
    Paper,
    SummaryReport,
    SummaryDialogStorage,
)
from business.models.abstract_report import AbstractReport
from business.utils.authenticate import authenticate_user
from business.utils.chat_glm import query_glm
from business.utils.chat_r1 import query_r1
from business.utils.futures import deprecated
from business.utils.response import ok, fail
from business.utils.download_paper import cache_paper

##################################新建一个临时知识库，多问几次，然后通过一个模板生成综述#######################################

###################综述生成##########################


def _pdf_to_sections(pdf_stream) -> list[list] | None:
    """
    pdf切分，返回各章的文本内容。如果失败，返回None
    :param pdf_stream: pdf的二进制流
    :return: [['章标题1', '章内容1'], ['章标题2', '章内容2'], ...] OR None if error occurs
    """
    step = "PDF切分章节"
    print("[state]:", f"正在{step}......")
    with fitz.open(stream=pdf_stream, filetype="pdf") as doc:
        # toc = doc.get_toc()
        text = "\n".join(page.get_text() for page in doc)

    max_chunk = 8192
    overlap = 256
    buffer = text
    sections = []
    i = 1
    while len(buffer) > max_chunk:
        sections.append(["Section " + str(i), buffer[:max_chunk]])
        buffer = buffer[max_chunk - overlap :]
    if buffer:  # Add remaining buffer if not empty
        sections.append(
            [
                "Section "
                + str(i + (1 if len(sections) > 0 and len(buffer) < max_chunk else 0)),
                buffer,
            ]
        )

    # print('[toc]', toc)
    # print('text', text[:100])
    #
    # buffer = text
    # for header in toc:
    #     if header[0] != 1:
    #         continue
    #     sub_title = header[1]
    #     print('[subtitle]', sub_title)
    #     begin = buffer.find(sub_title + '\n')
    #     if begin < 0:
    #         print('Error')
    #         print('Error [subtitle]', sub_title, 'not found')
    #         # No specific "失败" print here as per strict instructions
    #         return None
    #     sections[-1].append(buffer[:begin])
    #     sections.append([header])
    #     buffer = buffer[begin:]
    #
    # sections[-1].append(buffer)
    print("[state]:", f"{step}完成")
    return sections


def _select_sections(prompt: str, sections: list[list] | None) -> str:
    """
    根据prompt选取相关的章，将该章的全文加入prompt
    :param prompt: 需求
    :param sections: [['章标题1', '章内容1', '章总结1'], ['章标题2', '章内容2', '章总结2'], ...]或者None表示<b>不选取</b>
    :return: 加入相关章的prompt
    """
    step = "根据Prompt选取相关章节"
    print("[state]:", f"正在{step}......")
    if not sections:
        print("[state]:", f"{step}完成 (无有效章节)")
        return ""
    section_infos = ""
    cnt = 1
    for section in sections:
        if len(section) > 2:  # Check if summary (section[2]) exists
            section_infos += f"{cnt} " + ": " + section[2] + "\n"
        elif len(section) > 1:  # Fallback to content if summary doesn't exist
            section_infos += (
                f"{cnt} "
                + ": "
                + (section[1][:100] + "..." if section[1] else "[内容为空]")
                + "\n"
            )  # Show partial content
        else:
            section_infos += f"{cnt} " + ": [章节信息不足]\n"
        cnt += 1

    select_prompt = (
        f"你是文献阅读助手。现在用户进行了一个关于文献的提问，并且给你提供了文献各部分的总结。你需要根据这些总结，筛选出哪些部分对"
        f"回答用户的提问有帮助。如果有多个答案，请选择最精确的两个。\n"
        f"用户的提问是：\n{prompt}\n"
        f"文献各部分的总结是：\n{section_infos}"
        f'你需要返回一个json数组，包含需要的章节标号。如："[1, 3]"'
    )
    ans, _ = query_r1(select_prompt)
    selected_sections_json_str_match = re.search(
        r"\[.*?]", ans
    )  # Try to find any list-like string
    selected_sections = []
    if selected_sections_json_str_match:
        try:
            selected_sections = json.loads(selected_sections_json_str_match.group(0))
        except json.JSONDecodeError:
            print(
                f"[warn][{step}]: LLM返回的章节标号部分不是有效的JSON: {selected_sections_json_str_match.group(0)}"
            )
            selected_sections = []  # Reset to empty if parsing fails
    else:
        print(f"[warn][{step}]: 未能在LLM回答中找到章节标号数组。LLM回答: {ans}")

    print("[selected_sections]: ", selected_sections)  # Original print

    result_content = []
    for i in selected_sections:
        if (
            isinstance(i, int) and 1 <= i <= len(sections) and len(sections[i - 1]) >= 2
        ):  # Ensure index is valid and section has at least title and content
            result_content.append(f"{sections[i - 1][0]}：{sections[i - 1][1]}")

    final_result = "\n".join(result_content)
    print("[state]:", f"{step}完成")
    return final_result


def _comprehend_by_query(query: str, paper_info: dict):
    """
    加上文章相关内容，回答你的提问
    :param query: 你的提问
    :param paper_info: 包含"title", "abstract", "sections"域。"sections"是_comprehend_papers后的
    """
    step = "理解查询并整合文章内容"
    print("[state]:", f"正在{step}......")
    additional_info = _select_sections(query, paper_info["sections"])
    comprehend_prompt = f"""{query}
论文信息：
标题：{paper_info["title"]}
摘要：{paper_info["abstract"]}
{additional_info}"""
    ans = query_glm(comprehend_prompt, [])
    print("[comprehend_by_query] ", ans)  # Original print
    print("[state]:", f"{step}完成")
    return ans


def preprocess_paper(paper_ids, report: SummaryReport):
    """
    从url下载，建立RAG；同时按章节切分，并理解每章节的内容，然后生成背景、创新点、局限性

              _download_papers (生产者)
              /             \
             /               \
     _comprehend_papers   _build_kb (消费者)

    """
    step_main_preprocess = "论文预处理"
    report.summarydialogstorage.add_ai_hint(f"正在启动 {step_main_preprocess} ......")

    kb_id = ""
    paper_list = []
    kb_queue = queue.Queue()
    cp_queue = queue.Queue()

    def _download_papers():
        inner_step_download = "下载论文原文"
        report.summarydialogstorage.add_ai_hint(
            f"[{step_main_preprocess}] 正在 {inner_step_download}......"
        )
        downloaded_count = 0
        for paper_id_item in paper_ids:
            p_obj = Paper.objects.filter(paper_id=paper_id_item).first()
            s_step_dl_indiv = f"下载论文 (Title: {p_obj.title if p_obj else '未知'})"
            if not p_obj:
                print(
                    f"[warn][{step_main_preprocess}][{inner_step_download}] 未找到Paper ID: {paper_id_item}，跳过。"
                )
                print(
                    f"[state]: [{step_main_preprocess}][{inner_step_download}] {s_step_dl_indiv}完成 (未找到记录)"
                )
                continue
            report.summarydialogstorage.add_ai_hint(
                f"[{step_main_preprocess}][{inner_step_download}] 正在 {s_step_dl_indiv}......"
            )
            url = p_obj.original_url.replace("arxiv.org", "export.arxiv.org").replace(
                "abs/", "pdf/"
            )
            print("[url] ", url)
            # 允许从 arXiv/HTTP 兜底下载；否则在 MinIO 未配置时会导致 KB 无法构建（kb_id 为空）
            pdf_content = cache_paper(url, from_arxiv=True)
            if pdf_content:
                print("[download] successfully via minio")
            else:
                print(f"[download] failed: {url}")
                continue
            kb_queue.put((p_obj, pdf_content))
            cp_queue.put((p_obj, pdf_content))
            downloaded_count += 1
            print(
                f"[state]: [{step_main_preprocess}][{inner_step_download}] {s_step_dl_indiv}完成 (已下载并入队)"
            )

        kb_queue.put(None)
        cp_queue.put(None)
        report.summarydialogstorage.add_ai_hint(
            f"[{step_main_preprocess}] {inner_step_download} 完成 (共处理 {downloaded_count} / {len(paper_ids)} 篇)"
        )

    def _comprehend_papers():
        nonlocal paper_list
        inner_step_comprehend = "理解论文内容"
        report.summarydialogstorage.add_ai_hint(
            f"[{step_main_preprocess}] 正在 {inner_step_comprehend} ......"
        )
        comprehended_count = 0
        situation_query = f"""请分析这篇论文的研究现状，包括：
        1. 该领域的主要研究方向和进展
        2. 存在的主要问题和挑战
        3. 研究方法和技术的演变
        4. 关键研究成果和突破"""

        innovation_query = f"""请分析这篇论文的创新点，包括：
                    1. 研究问题的创新性
                    2. 方法或技术的创新性
                    3. 实验设计的创新性
                    4. 结论或发现的创新性"""

        limitation_query = f"""请分析这篇论文的局限性，包括：
                    1. 方法或技术的局限性
                    2. 实验设计的局限性
                    3. 结论的局限性
                    4. 未来改进方向"""

        while True:
            item_cp = cp_queue.get()
            if item_cp is None:
                cp_queue.task_done()
                break

            paper_obj_cp, pdf_content_cp = item_cp
            s_step_comprehend_indiv = f"处理论文 {paper_obj_cp.title}"
            report.summarydialogstorage.add_ai_hint(
                f"[{step_main_preprocess}][{inner_step_comprehend}] 正在 {s_step_comprehend_indiv}......"
            )

            sections_cp = _pdf_to_sections(pdf_content_cp)
            report.summarydialogstorage.add_ai_hint(
                f"[{step_main_preprocess}][{inner_step_comprehend}][{s_step_comprehend_indiv}] PDF切分调用完成"
            )

            if sections_cp:
                for section_data_cp in sections_cp:
                    s_step_summarize_sec_cp = f"总结章节 {section_data_cp[0]}"
                    report.summarydialogstorage.add_ai_hint(
                        f"[{step_main_preprocess}][{inner_step_comprehend}][{s_step_comprehend_indiv}] 正在 {s_step_summarize_sec_cp}......"
                    )
                    comprehend_prompt_sec = (
                        f"你是文献助手，有一篇论文的摘要是{paper_obj_cp.abstract}。现在给你该篇论文{section_data_cp[0]}部分"
                        f"的原文，请你简要概括出这部分的内容。该部分原文如下：{section_data_cp[1]}"
                    )
                    comprehension_sec = query_glm(comprehend_prompt_sec)
                    if len(section_data_cp) > 2:
                        section_data_cp[2] = comprehension_sec
                    else:
                        section_data_cp.append(comprehension_sec)
                    print(
                        f"[state]: [{step_main_preprocess}][{inner_step_comprehend}][{s_step_comprehend_indiv}] {s_step_summarize_sec_cp}完成"
                    )

            authors_cp = paper_obj_cp.authors.split(",")
            if len(authors_cp) > 3:
                authors_cp = authors_cp[:3] + ["et al"]
            author_field_cp = ",".join(authors_cp)

            publication_date_cp = paper_obj_cp.publication_date
            if isinstance(
                publication_date_cp, str
            ):  # Ensure it's a date object for strftime
                try:
                    publication_date_cp = datetime.datetime.strptime(
                        publication_date_cp.split(" ")[0], "%Y-%m-%d"
                    ).date()
                except ValueError:
                    publication_date_cp = datetime.date.today()  # Fallback
            elif not isinstance(publication_date_cp, datetime.date):
                publication_date_cp = datetime.date.today()  # Fallback

            info_cp = {
                "title": paper_obj_cp.title,
                "abstract": paper_obj_cp.abstract,
                "content": (
                    paper_obj_cp.content if hasattr(paper_obj_cp, "content") else None
                ),
                "sections": sections_cp,
                "gb/t7714": f"{author_field_cp}.{paper_obj_cp.title}[EB/OL].({publication_date_cp.strftime('%Y-%m-%d')})[{datetime.date.today().strftime('%Y-%m-%d')}].{paper_obj_cp.original_url}",
            }
            s_step_analyze_parts_cp = "分析研究现状、创新点、局限性"
            report.summarydialogstorage.add_ai_hint(
                f"[{step_main_preprocess}][{inner_step_comprehend}][{s_step_comprehend_indiv}] 正在 {s_step_analyze_parts_cp} ......"
            )
            info_cp["situation"] = _comprehend_by_query(situation_query, info_cp)
            info_cp["innovation"] = _comprehend_by_query(innovation_query, info_cp)
            info_cp["limitation"] = _comprehend_by_query(limitation_query, info_cp)
            print(
                f"[state]: [{step_main_preprocess}][{inner_step_comprehend}][{s_step_comprehend_indiv}] {s_step_analyze_parts_cp}完成"
            )

            paper_list.append(info_cp)
            comprehended_count += 1
            print(
                f"[state]: [{step_main_preprocess}][{inner_step_comprehend}] {s_step_comprehend_indiv}完成 (已理解并入列)"
            )
            cp_queue.task_done()
        report.summarydialogstorage.add_ai_hint(
            f"[{step_main_preprocess}] {inner_step_comprehend} 完成 (共处理 {comprehended_count} 篇)"
        )

    def _build_kb():
        nonlocal kb_id
        inner_step_buildkb = "构建临时知识库"
        report.summarydialogstorage.add_ai_hint(
            f"[{step_main_preprocess}] 正在 {inner_step_buildkb} ......"
        )
        built_kb_count = 0
        upload_temp_docs_url = (
            f"{settings.REMOTE_MODEL_BASE_PATH}/knowledge_base/upload_temp_docs"
        )
        while True:
            print(
                f"[{step_main_preprocess}][{inner_step_buildkb}] 当前 kb_id 是: {kb_id}"
            )  # Original print
            data_field_kb = {"prev_id": kb_id} if kb_id else {}
            if not kb_id:  # If first time, need a kb_name
                data_field_kb["kb_name"] = (
                    f"summary_kb_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                )

            item_kb = kb_queue.get()
            if item_kb is None:
                kb_queue.task_done()
                break

            paper_obj_kb, pdf_content_kb = item_kb
            s_step_buildkb_indiv = f"处理论文 {paper_obj_kb.title} 以构建知识库"
            report.summarydialogstorage.add_ai_hint(
                f"[{step_main_preprocess}][{inner_step_buildkb}] 正在 {s_step_buildkb_indiv}......"
            )

            txt_file_kb = pdf_to_txt(pdf_content_kb, paper_obj_kb.title)
            print(
                f"[state]: [{step_main_preprocess}][{inner_step_buildkb}][{s_step_buildkb_indiv}] PDF转TXT完成"
            )

            # Assuming requests is available
            import requests as req_build_kb  # Local import for clarity

            response_kb = req_build_kb.post(
                upload_temp_docs_url, files=[txt_file_kb], data=data_field_kb
            )
            report.summarydialogstorage.add_ai_hint(
                f"[{step_main_preprocess}][{inner_step_buildkb}][{s_step_buildkb_indiv}] 上传至知识库服务HTTP请求完成"
            )

            if response_kb.status_code != 200:
                # Original code raises Exception, respecting "no logic changes"
                print(
                    f"[error][{step_main_preprocess}][{inner_step_buildkb}][{s_step_buildkb_indiv}] 连接模型服务器失败，错误代码{response_kb.status_code}"
                )
                # The original exception will propagate
                raise Exception(
                    f"连接模型服务器失败，错误代码{response_kb.status_code}"
                )

            response_json_kb = response_kb.json()
            kb_id = response_json_kb["data"][
                "id"
            ]  # Update kb_id with the one returned (could be same as prev_id or new)
            built_kb_count += 1
            print(
                f"[state]: [{step_main_preprocess}][{inner_step_buildkb}][{s_step_buildkb_indiv}] 完成 (新/当前KB ID: {kb_id})"
            )
            kb_queue.task_done()
        print(
            f"[state]: [{step_main_preprocess}] {inner_step_buildkb}完成 (共处理 {built_kb_count} 篇)"
        )

    threading.excepthook = lambda args: (_ for _ in ()).throw(  # Original excepthook
        Exception(
            f"Caught exception in thread {args.thread.name}: "
            f"{args.exc_type.__name__}: "
            f"{args.exc_value}"
        )
    )

    download_thread = threading.Thread(target=_download_papers)
    comprehend_thread = threading.Thread(target=_comprehend_papers)
    kb_thread = threading.Thread(target=_build_kb)

    s_step_start_threads = "启动预处理子线程"
    print(f"[state]: [{step_main_preprocess}] 正在{s_step_start_threads}......")
    download_thread.start()
    comprehend_thread.start()
    kb_thread.start()
    print(f"[state]: [{step_main_preprocess}] {s_step_start_threads}完成")

    s_step_join_threads = "等待预处理完成"
    report.summarydialogstorage.add_ai_hint(
        f"[{step_main_preprocess}] 正在 {s_step_join_threads}......"
    )
    download_thread.join()
    report.summarydialogstorage.add_ai_hint(
        f"[{step_main_preprocess}][{s_step_join_threads}] 下载完成"
    )
    comprehend_thread.join()
    report.summarydialogstorage.add_ai_hint(
        f"[{step_main_preprocess}][{s_step_join_threads}] 理解完成"
    )
    kb_thread.join()
    report.summarydialogstorage.add_ai_hint(
        f"[state]: [{step_main_preprocess}][{s_step_join_threads}] 知识库构建完成"
    )
    print(f"[state]: [{step_main_preprocess}] {s_step_join_threads}完成")

    print("[state]:", f"{step_main_preprocess}完成")
    return kb_id, paper_list


def validation(part, content, kb_id, ref_papers: list[str]) -> str:
    """
    对生成的综述使用RAG进行验证，实现交叉引用。
    :param part: 综述部分的名称，如"主体"，"引言"
    :param content: 该部分内容
    :param kb_id: 临时知识库id
    :param ref_papers: 参考文献列表
    """
    step_validation = f"验证和交叉引用综述的 '{part}' 部分"
    print("[state]:", f"正在{step_validation} (KB ID: {kb_id})......")
    payload_dict = {
        "query": f"这是一篇综述的{part}部分，请根据知识库对该部分进行扩充和校对，形成完整的段落。这部分内容是：\n{content}",
        "knowledge_id": kb_id,
        "knowledge_base_name": kb_id,  # Added for Chatchat compatibility
        "mode": "temp_kb",
        "kb_name": kb_id,
        "score_threshold": 0.5,
        "stream": True,  # kb_ask_ai handles stream and returns full text
    }
    print(f"[{step_validation}] Query: ", payload_dict["query"])  # Original print
    print(f"[{step_validation}] kb_id: ", kb_id)  # Original print

    s_step_rag_call = "调用kb_ask_ai进行RAG"
    print(f"[state]: [{step_validation}] 正在{s_step_rag_call}......")
    ai_reply, origin_docs = kb_ask_ai(
        json.dumps(payload_dict)
    )  # kb_ask_ai expects JSON string
    print(f"[state]: [{step_validation}] {s_step_rag_call}完成")

    ref_str = ""
    print(f"[{step_validation}] 共{len(origin_docs)}篇参考文献")  # Original print
    for origin_doc in origin_docs:
        print(f"[{step_validation}][origin_doc]: ", origin_doc)  # Original print
        title, content_from_doc = extract_reference_info(
            origin_doc
        )  # Renamed content to avoid conflict
        if title is None:
            print(
                f"[state]: [{step_validation}] 因匹配知识库失败，未进行交叉引用 (title is None)"
            )
            print("[state]:", f"{step_validation}完成")
            return ai_reply
        loc = len(ref_papers)
        for i in range(len(ref_papers)):
            if ref_papers[i].lower() == title.lower():
                loc = i
                break

        if loc == len(ref_papers):
            continue

        ref_str += f"参考文献[{loc + 1}]：标题：{title}；内容：{content_from_doc}\n"

    # ref_prompt = (
    #     f"请使用交叉引用的方式，在正文中合适的位置添加这些参考文献的引用，以印证正文的准确性。你不需要列出尾注，但是交叉引用的编号必须和提供的编号一致。\n"
    #     f"*正文*：\n{ai_reply}。*参考文献*：\n{ref_str}"
    # )
    # print(f"[{step_validation}] 校对后的{part}: ", ai_reply)  # Original print

    # s_step_crossref_call = "调用query_r1进行交叉引用文本生成"
    # print(f"[state]: [{step_validation}] 正在{s_step_crossref_call}......")
    # ai_reply_with_ref, _ = query_r1(
    #     ref_prompt
    # )  # Assuming query_r1 returns (text, other_info)
    # print(f"[state]: [{step_validation}] {s_step_crossref_call}完成")

    # print(
    #     f"[{step_validation}] 带参考文献的{part}: ", ai_reply_with_ref
    # )  # Original print
    # print("[state]:", f"{step_validation}完成")
    return ai_reply


def _parse_feedback(response: str) -> tuple[bool, str]:
    # No state prints for this utility function
    match = re.match(r"@([^@]+)@(.+)", response, re.DOTALL)  # Added re.DOTALL
    if match:
        option = match.group(1)
        return "REGEN" in option.upper(), match.group(2)  # .upper() for robustness
    else:
        # raise ValueError("Feedback doesn't match @xxx@yyy format: " + response) # Original
        return (
            False,
            response,
        )  # Keep original behavior on mismatch if it was not raising error


def get_summary_v2(paper_ids, report_id, **kwargs):
    step_getsummary_main = "综述生成"
    report = SummaryReport.objects.get(report_id=report_id)
    report.status = SummaryReport.STATUS_IN_PROGRESS

    try:
        report.summarydialogstorage.add_ai_hint(
            f"[{step_getsummary_main}] 正在 文献预处理 ......"
        )
        tmp_kb, paper_info = preprocess_paper(paper_ids, report)
        report.summarydialogstorage.tmp_kb_id = tmp_kb
        report.summarydialogstorage.paper_info = paper_info
        report.summarydialogstorage.steps = 0
        report.summarydialogstorage.save()

        # 生成大纲
        report.summarydialogstorage.add_ai_hint(
            f"[{step_getsummary_main}] 正在 生成大纲 ......"
        )
        abstracts = "\n".join(
            [
                f"论文《{info['title']}》的摘要：{info['abstract']}"
                for info in paper_info
            ]
        )

        outline_prompt = f"""你是文献调研助手。现在给出几篇论文的摘要，请你为这些论文生成一个综述的大纲。
大纲包括引言（introduction）、主体（body）和结论（conclusion）三部分。下面给出了一些参考内容，你需要根据论文的摘要进行细化和扩充。
# 引言部分的参考内容：
    1. 介绍研究领域的背景和重要性
    2. 说明综述的目的和范围
    3. 概述各篇论文的主要贡献
    4. 提出综述的结构安排
# 主体部分的参考内容
    1. 按照研究主题或方法对论文进行合理分类
    2. 分析各研究方向的发展脉络和趋势
    3. 比较不同方法的优缺点
    4. 指出研究中的共性和差异
    5. 分析研究中的不足和挑战
# 结论部分的参考内容
    1. 总结主要研究发现
    2. 指出研究趋势和未来方向
    3. 提出研究建议和展望
    4. 强调研究的实践意义
论文及摘要如下：
{abstracts}
你需要回复一个json，具体的格式如下：
{{
    "introduction": ["引言的第一条", "引言的第二条", ...],
    "body": {{
        "主题A": ["主题A的第一条"，"主题A的第二条", ...],
        "主题B": ["主题B的第一条"，"主题B的第二条", ...],
        ...
    }},
    "conclusion": ["结论的第一条", "结论的第二条", ...]
}}"""
        # Step 1：提取主题
        extract_topics_prompt = f"""
你是一位专业的文献调研助手。以下是若干篇论文的摘要，请你根据内容提取出这些研究的主要主题或研究方法。

要求：
1. 主题数量建议在3~6个之间
2. 每个主题应该能够作为综述的一个章节标题
3. 主题应该具有层次性和逻辑性，便于后续展开讨论
4. 主题应该反映研究领域的最新发展趋势
5. 可以参考以下CV领域的常见主题分类方式：
   - 任务类型：如目标检测、图像分割、图像分类等
   - 技术方法：如深度学习、传统方法、混合方法等
   - 应用场景：如医疗影像、自动驾驶、安防监控等
   - 模型架构：如CNN、Transformer、GAN等
   - 优化方向：如轻量化、鲁棒性、可解释性等

请你输出一个JSON数组，格式为["主题A", "主题B", "主题C"]，例如：
["基于深度学习的图像分割方法", "轻量级目标检测算法研究", "Transformer在计算机视觉中的应用"]

摘要如下：
{abstracts}
"""

        report.summarydialogstorage.conversation["outline_prompt"] = outline_prompt
        report.summarydialogstorage.save()

        topics_json, _ = query_r1(extract_topics_prompt)
        topics = answer2list(topics_json)
        print("[topic]", topics)

        # Step 2：生成引言大纲
        intro_prompt = f"""\
你是一位专业的文献综述写作助手。请根据以下论文摘要，生成一篇综述论文的引言部分大纲。

引言部分需要包含以下要素：
1. 研究背景与意义
   - 该研究领域的发展现状
   - 研究领域的重要性和应用价值
   - 当前面临的主要挑战和问题
2. 综述目的与范围
   - 本综述的主要目标
   - 研究范围界定
   - 预期达到的效果
3. 研究主题概述
   - 对已提取主题的简要说明
   - 各主题之间的关联性
   - 主题选择的理论依据
4. 文献贡献分析
   - 所选文献的主要创新点
   - 文献之间的互补性
   - 对研究领域的推动作用
5. 综述结构说明（可基于提取的主题）
   - 各章节的主要内容
   - 章节之间的逻辑关系
   - 阅读建议

请以JSON数组格式输出，["研究背景：...", "综述目的：...", "研究主题包括：...", "主要论文贡献：...", "综述结构安排：..."]，每个要素对应一个条目，例如：
["研究背景：计算机视觉领域近年来快速发展，在医疗、安防等领域有广泛应用，但仍面临精度、效率等挑战...",
 "综述目的：本文旨在系统梳理目标检测领域的最新进展，为研究者提供参考...",
 "研究主题：本文将从深度学习、传统方法和混合方法三个维度展开讨论...",
 "文献贡献：所选文献在算法创新、应用拓展等方面做出了重要贡献...",
 "结构安排：本文共分为5个章节，首先介绍研究背景，然后分别讨论三个主题，最后总结展望..."]

研究主题如下：
{json.dumps(topics, ensure_ascii=False)}
论文摘要如下：
{abstracts}
"""

        intro_json, _ = query_r1(intro_prompt)
        introduction = answer2list(intro_json)
        print("[introduction]", introduction)
        # Step 3：生成主体大纲
        body_prompt = f"""\
你是一位专业的文献综述写作助手。请根据以下研究主题和论文摘要，为综述的主体部分编写详细大纲。

对于每个主题，请从以下维度进行分析：
1. 研究现状与发展脉络
   - 该主题的研究历史与演进
   - 关键突破与里程碑
   - 当前研究热点
2. 方法学比较与分析
   - 主要研究方法概述
   - 方法间的优劣对比
   - 适用场景分析
3. 实验结论与分析
   - 实验设计与方法
   - 实验结果与发现
   - 实验结果的分析与展望
4. 未来发展方向
   - 潜在的研究机会
   - 可能的改进方向
   - 跨领域应用前景

请以JSON对象格式输出，结构如下：
{{
  "主题A": [
    "研究现状：...",
    "方法比较：...",
    "实验结论：...",
    "未来展望：..."
  ],
  "主题B": [...],
  ...
}}

研究主题如下：
{json.dumps(topics, ensure_ascii=False)}
论文摘要如下：
{abstracts}
"""

        body_json, _ = query_r1(body_prompt)
        body = answer2dict(body_json)
        print("[body]", json.dumps(body, ensure_ascii=False, indent=4), sep="\n")
        # Step 4：生成结论大纲
        conclusion_prompt = f"""\
你是一位专业的文献综述写作专家。请基于以下论文摘要，为综述论文的结论部分制定一个全面且结构清晰的大纲。

结论部分需要涵盖以下关键要素：
1. 研究现状总结
   - 主要研究发现与贡献
   - 研究结果的实践价值
2. 研究趋势分析
   - 当前研究热点与方向
   - 潜在的研究机会
3. 挑战与展望
   - 现有研究的局限性
   - 待解决的关键问题
   - 未来研究建议
4. 实践意义
   - 理论创新价值
   - 实际应用价值
   - 对相关领域的启示

请以JSON数组格式输出，每个元素对应一个主要部分：
[
    "研究现状：...",
    "研究趋势：...", 
    "挑战展望：...",
    "实践意义：..."
]

论文摘要如下：
{abstracts}
"""

        conclusion_json, _ = query_r1(conclusion_prompt)
        conclusion = answer2list(conclusion_json)
        print("[conclusion]", conclusion)
        # 最终结构化输出
        outline = {"introduction": introduction, "body": body, "conclusion": conclusion}
        print("[outline]", json.dumps(outline, ensure_ascii=False, indent=4))

        adjust_prompt = f"""
你是一位专业的文献综述写作专家。请对以下文献综述大纲进行全面优化，给出改进后的内容。重点关注以下几个方面：

1. 结构完整性
   - 引言、主体、结论三部分是否完整
   - 各部分内容是否均衡
   - 层次结构是否清晰

2. 逻辑连贯性
   - 各部分之间是否衔接自然
   - 主体部分的主题划分是否合理
   - 论述是否循序渐进

3. 内容一致性
   - 主题之间是否存在重复
   - 论述重点是否突出
   - 结论是否与主体呼应

4. 学术规范性
   - 是否符合学术写作规范
   - 术语使用是否准确
   - 论述是否客观严谨

请你仍以json格式输出，与输入格式一致，最顶层是以"introduction"，"body"和"conclusion"为键值的字典，"body"中是以各个主题为键值的字典。
{{
    "introduction": [...],
    "body": {{
        "主题A": [...],
        "主题B": [...],
        ...
    }},
    "conclusion": [...]
}}

当前大纲如下：
{json.dumps(outline, ensure_ascii=False)}
"""
        new_outline_json, _ = query_r1(adjust_prompt)
        outline = answer2dict(new_outline_json)
        report.summarydialogstorage.conversation["outline"] = outline
        report.summarydialogstorage.save()
        print("[new outline]", json.dumps(outline, ensure_ascii=False, indent=4))
        presented_result = ""
        # 整理成Markdown，反馈给用户
        part_map = {"introduction": "引言", "body": "主体", "conclusion": "结论"}
        for k, v in outline.items():
            presented_result += f"# {part_map[k.lower()]}\n" + "".join(
                [f"    - {point}\n" for point in v]
            )
        print("[outline]", presented_result)
        report.summarydialogstorage.add_ai_message(presented_result)
        report.summarydialogstorage.steps += 1
        report.summarydialogstorage.save()

    except Exception as e:
        print(e)
        report.delete()
        raise e


@authenticate_user
@require_http_methods(["GET"])
def get_summary_v2_get_status(request, user: User):
    report_id = request.GET.get("report_id")
    report = SummaryReport.objects.get(report_id=report_id, user_id=user)
    if report.status == SummaryReport.STATUS_COMPLETED:
        return ok(
            {
                "data": {
                    "type": "success",
                    "content": report.summarydialogstorage.get_last_message(),
                }
            }
        )
    if report.summarydialogstorage.is_last_ai_response():
        return ok(
            {
                "data": {
                    "type": "response",
                    "content": report.summarydialogstorage.get_last_message(),
                }
            }
        )
    if report.summarydialogstorage.is_last_ai_hint():
        return ok(
            {
                "data": {
                    "type": "hint",
                    "content": report.summarydialogstorage.get_last_message(),
                }
            }
        )
    # Unexpected state
    return ok(
        {
            "data": {
                "type": "hint",
                "content": "AI 正在处理您的请求，请稍等片刻。",
            }
        }
    )


def get_summary_v2_user_response(report_id):
    step_getsummary_main = "综述生成"
    report = SummaryReport.objects.get(report_id=report_id)
    feedback = report.summarydialogstorage.get_last_message()  # Assert to be User!
    need_revise, instruction = _parse_feedback(feedback)
    print("need-revise-outline: ", need_revise)

    now_step = report.summarydialogstorage.steps
    paper_info = report.summarydialogstorage.paper_info
    tmp_kb = report.summarydialogstorage.tmp_kb_id
    outline = report.summarydialogstorage.conversation["outline"]
    # 枚举当前步骤，采取不同的处理方式！
    match now_step:
        # vvvvvvvvvvvvvvvvvvvv 步骤 1 开始 vvvvvvvvvvvvvvvvvvvv
        case 1:
            report.summarydialogstorage.add_ai_hint(
                f"[{step_getsummary_main}] 正在 修订大纲 ......"
            )
            outline_prompt = report.summarydialogstorage.conversation["outline_prompt"]
            if need_revise:
                history = [
                    {"role": "user", "content": outline_prompt},
                    {
                        "role": "assistant",
                        "content": json.dumps(outline, ensure_ascii=False, indent=4),
                    },
                ]
                revise_prompt = f"""用户希望进行修改。他的意见是：{instruction}。别忘了修改后也要遵循json格式输出：
{{
    "introduction": ["引言的第一条", "引言的第二条", ...],
    "body": {{
        "主题A": ["主题A的第一条"，"主题A的第二条", ...],
        "主题B": ["主题B的第一条"，"主题B的第二条", ...],
        ...
    }},
    "conclusion": ["结论的第一条", "结论的第二条", ...]
}}
"""
                answer, _ = query_r1(revise_prompt, history)
                outline = answer2dict(answer)
            ref_paper_list = [p["title"] for p in paper_info]
            # 生成引言
            report.summarydialogstorage.add_ai_hint(
                f"[{step_getsummary_main}] 正在 生成引言 ......"
            )
            introduction_prompt = f"""请根据以下论文信息生成一篇综述的引言，需要包含如下内容。请使用交叉引用的方式，在正文中合适的位置添加这些参考文献的引用，以印证正文的准确性。你不需要列出尾注，但是交叉引用的编号必须和提供的编号一致。
注意：1. 你不需要提供尾注。2. 要生成成连贯的段落，不能是小标题的列举。3. 字数不得少于800字。
引言大纲如下：
{json.dumps(outline['introduction'], ensure_ascii=False)}
需要包含的内容：
论文信息（请在适当位置交叉引用）：
"""
            for i, info in enumerate(paper_info):
                introduction_prompt += f"\n参考论文[{i + 1}]标题：{info['title']}\n研究现状：{info['situation']}\n"
            introduction = query_r1(introduction_prompt, [])
            report.summarydialogstorage.add_ai_hint(
                f"[{step_getsummary_main}] 正在 验证引言 ......"
            )
            validated_introduction = validation(
                "引言",
                introduction,
                tmp_kb,
                ref_paper_list,
            )
            # 生成正文
            body_parts = {}
            report.summarydialogstorage.add_ai_hint(
                f"[{step_getsummary_main}] 正在 生成正文 ......"
            )
            for topic, sub_outline in outline["body"].items():
                body_prompt = f"""请根据以下论文信息生成综述的正文部分，包含如下内容。请使用交叉引用的方式，在正文中合适的位置添加这些参考文献的引用，以印证正文的准确性。你不需要列出尾注，但是交叉引用的编号必须和提供的编号一致。
注意：1. 你不需要提供尾注。2. 要生成成连贯的段落，不能是小标题的列举。3. 每篇论文有关信息不得低于800字，总字数不得少于3000字。
需要包含的内容：
{json.dumps(sub_outline, ensure_ascii=False)}
论文信息（请在适当位置交叉引用）：
"""
                for i, info in enumerate(paper_info):
                    body_prompt += f"\n参考论文[{i + 1}]标题：{info['title']}\n创新点：{info['innovation']}\n局限性：{info['limitation']}\n"
                body = query_r1(body_prompt, [])
                report.summarydialogstorage.add_ai_hint(
                    f"[{step_getsummary_main}] 正在 验证正文......"
                )
                body_parts[topic] = validation("主体", body, tmp_kb, ref_paper_list)

            # 生成结论
            report.summarydialogstorage.add_ai_hint(
                f"[{step_getsummary_main}] 正在 生成结论 ......"
            )
            conclusion_prompt = f"""请根据以下论文信息生成综述的结论部分，包含如下内容。请使用交叉引用的方式，在正文中合适的位置添加这些参考文献的引用，以印证正文的准确性。你不需要列出尾注，但是交叉引用的编号必须和提供的编号一致。
注意：1. 你不需要提供尾注。2. 要生成成连贯的段落，不能是小标题的列举。3.字数不得少于800字
需要包含的内容：
{outline['conclusion']}
论文信息（请在适当位置交叉引用）：
"""
            for i, info in enumerate(paper_info):
                conclusion_prompt += f"\n参考论文[{i + 1}]标题：{info['title']}\n创新点：{info['innovation']}\n局限性：{info['limitation']}\n"
            conclusion = query_r1(conclusion_prompt, [])
            report.summarydialogstorage.add_ai_hint(
                f"[{step_getsummary_main}] 正在 验证结论 ......"
            )
            validated_conclusion = validation(
                "结论", conclusion, tmp_kb, ref_paper_list
            )
            references = ""
            i = 1
            for p in paper_info:
                references += f"[{i}] {p['gb/t7714']}\n"
                i += 1

            # 生成完整的综述
            summary = (
                f"# 引言\n{validated_introduction}\n\n"
                + "".join(
                    [
                        f"# {topic}\n{body_part}\n\n"
                        for topic, body_part in body_parts.items()
                    ]
                )
                + f"# 结论\n{validated_conclusion}\n\n"
                + f"# 参考文献\n{references}"
            )

            # 生成完整综述
            organize_prompt = f"""有一篇markdown格式的文献综述，但是有一些格式和语法上的问题。你需要：
1. 删去无用的信息，如："修改后的文章如下"、"修改说明"等与综述无关的信息；
2. 使句子通顺、有条理，上下文连贯；
3. 使段落清晰。删去错误的换行符，统一使用首行缩进的方式分段。
4. 重新调整引用、正文和结论的内容，使它们有合适的篇幅比例。正文部分可以适当增加二级小标题。
5. 确保整体字数不低于{len(paper_info) * 1000}字，正文占据全文70%以上。
6. 对于文章中出现的交叉引用，请务必保留，结尾列出参考文献列表，保证编号与尾注一致。

你只需要输出你修改后的综述，不需要添加任何额外的信息。
修改前的综述是：{summary}
你修改后的综述是：
"""
            report.summarydialogstorage.add_ai_hint(
                f"[{step_getsummary_main}] 正在 生成优化综述内容 ......"
            )
            summary, _ = query_r1(organize_prompt)
            report.summarydialogstorage.add_ai_message(summary)
            report.summarydialogstorage.steps += 1
            report.summarydialogstorage.save()
        # vvvvvvvvvvvvvvvvvvvv 步骤 2 开始 vvvvvvvvvvvvvvvvvvvv
        case 2:
            if need_revise:
                print("[summary]: 用户需要修改。意见是：", instruction)
                revise_prompt = f"""用户希望修改一篇由LLM生成的综述，他的修改意见是：{instruction}。
    先前由LLM生成的综述是：{report.summarydialogstorage.conversation["conversition"][-2].get("content")}
    你现在已知："""
                for i, info in enumerate(paper_info):
                    revise_prompt += f"\n参考论文[{i + 1}]标题：{info['title']}\n创新点：{info['innovation']}\n局限性：{info['limitation']}\n"
                revise_prompt += "你只需要输出修改后的综述，不需要输出其他任何信息（比如修改说明）。你修改后的综述是：\n"
                report.summarydialogstorage.add_ai_hint(
                    f"[{step_getsummary_main}] 正在 修改综述 ......"
                )
                summary, _ = query_r1(revise_prompt)
            else:
                summary = report.summarydialogstorage.conversation["conversition"][
                    -2
                ].get("content")
                print("[summary]:", summary)
            report.summarydialogstorage.add_ai_message(summary)
            report.summarydialogstorage.steps += 1
            report.summarydialogstorage.save()
            report.summarydialogstorage.add_ai_hint(
                f"[{step_getsummary_main}] 就要完成了 ......"
            )
            # 保存综述
            md_path = settings.USER_REPORTS_PATH + "/" + str(report.report_id) + ".md"
            print("!!!!!综述生成即将完成!!!!!")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(summary)
            report.report_path = md_path
            report.status = SummaryReport.STATUS_COMPLETED
            report.save()
            report.summarydialogstorage.add_ai_hint("综述生成完成，进入个人中心查看！")
            print("!!!!!综述生成完成!!!!!")
        case _:
            raise ValueError("Invalid step number: " + str(now_step))


@authenticate_user
@require_http_methods(["POST"])
def get_summary_v2_set_user_response(request, user: User):
    report_id = request.GET.get("report_id")
    data = json.loads(request.body)
    req_type = data.get("type")
    user_response = data.get("content", "")
    if user_response == "":
        user_response = "Okay!"  # Avoid error in parse_feedback
    prefix = "@REGRN@" if req_type == "regen" else "@CONTINUE@"

    report = SummaryReport.objects.get(report_id=report_id, user_id=user)
    report.summarydialogstorage.add_user_message(prefix + user_response)

    threading.Thread(
        target=get_summary_v2_user_response,
        args=(report_id,),
    ).start()

    return ok(msg="AI 已经收到您的反馈。正在处理中，请稍等片刻。")


@require_http_methods(["GET"])
def get_summary_status(request):
    """
    查询综述生成状态
    """
    report_id_status = request.GET.get("report_id")
    step_status = f"查询综述生成状态 (Report ID: {report_id_status})"
    print(f"[state]: 正在{step_status}......")

    report_query = SummaryReport.objects.filter(report_id=report_id_status).first()
    if report_query is None:
        # No specific "失败" print here, original logic handles it
        print(f"[state]: {step_status}完成 (综述不存在)")
        return fail({"status": "综述不存在"})
    if (
        report_query.status == SummaryReport.STATUS_PENDING
        or report_query.status == SummaryReport.STATUS_IN_PROGRESS
    ):
        print(f"[state]: {step_status}完成 (正在生成中)")
        return fail({"status": "正在生成中"})  # Original uses fail here, keeping it

    print(f"[state]: {step_status}完成 (生成成功)")
    return ok({"status": "生成成功"})


@authenticate_user
@require_http_methods(["POST"])
def generate_summary(request, user: User):
    """
    生成综述
    """
    step_gensum_entry = f"generate_summary入口 (User: {user.username})"
    print(f"[state]: 正在{step_gensum_entry}......")
    data = json.loads(request.body)
    paper_ids_req = data.get("paper_id_list")

    s_step_create_report_rec = "创建SummaryReport记录"
    print(f"[state]: [{step_gensum_entry}] 正在{s_step_create_report_rec}......")
    report_obj = SummaryReport.objects.create(
        user_id=user, status=SummaryReport.STATUS_PENDING
    )
    report_obj.title = "综述" + str(report_obj.report_id)

    # Ensure USER_REPORTS_PATH directory exists
    reports_dir_path_gs = settings.USER_REPORTS_PATH
    if not os.path.exists(reports_dir_path_gs):
        os.makedirs(reports_dir_path_gs, exist_ok=True)
    p_path = os.path.join(
        reports_dir_path_gs, str(report_obj.report_id) + ".md"
    )  # Use os.path.join

    report_obj.report_path = p_path
    report_obj.summarydialogstorage = SummaryDialogStorage.objects.create(
        report=report_obj,
        conversation=dict(),
    )
    report_obj.save()
    print(
        f"[state]: [{step_gensum_entry}] {s_step_create_report_rec}完成 (Report ID: {report_obj.report_id})"
    )

    try:
        print(report_obj.report_id)  # Original print
        if len(paper_ids_req) > 20:
            # No specific "失败" print here
            print(f"[state]: [{step_gensum_entry}]完成 (因文章数目过多而失败)")
            return fail(msg="综述生成输入文章数目过多")

        s_step_start_thread_gs = "启动get_summary后台线程"
        print(f"[state]: [{step_gensum_entry}] 正在{s_step_start_thread_gs}......")
        threading.Thread(
            target=get_summary_v2, args=(paper_ids_req, report_obj.report_id)
        ).start()
        print(f"[state]: [{step_gensum_entry}] {s_step_start_thread_gs}完成")

        print(f"[state]: {step_gensum_entry}完成 (任务已提交)")
        return ok(
            {"message": "综述生成成功", "report_id": report_obj.report_id}
        )  # "成功" here means successfully started
    except Exception as e:
        print(e)  # Original print
        report_obj.delete()
        # No specific "失败" print here
        print(f"[state]: {step_gensum_entry}完成 (因异常而失败)")
        return fail({"message": "综述生成失败"})


##################################单篇摘要生成##############################

import os
import requests
from business.utils.download_paper import download_paper


@deprecated("Cannot find usage")
def create_tmp_knowledge_base(directory: str) -> str | None:
    """
    将cache中的所有文件全部上传到远端服务器，创建一个临时知识库
    """
    step_createtmpkb_dep = f"create_tmp_knowledge_base (已废弃) for dir: {directory}"
    print(f"[state]: 正在{step_createtmpkb_dep}......")
    upload_temp_docs_url = (
        f"{settings.REMOTE_MODEL_BASE_PATH}/knowledge_base/upload_temp_docs"
    )
    payload = {}  # Original payload

    res_files = []
    # import os # Already at top

    s_step_walk_dir_dep = "遍历目录文件"
    print(f"[state]: [{step_createtmpkb_dep}] 正在{s_step_walk_dir_dep}......")
    for root, dirs, files in os.walk(directory):
        for file_loop_item in files:  # Renamed file to avoid conflict
            file_path = os.path.join(root, file_loop_item)
            res_files.append(
                (
                    "files",
                    (
                        file_loop_item,  # Use file_loop_item
                        open(file_path, "rb"),
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # Original MIME
                    ),
                )
            )
    print(
        f"[state]: [{step_createtmpkb_dep}] {s_step_walk_dir_dep}完成 (找到 {len(res_files)} 个文件)"
    )

    s_step_upload_dep = "上传文件到临时知识库 (deprecated)"
    print(f"[state]: [{step_createtmpkb_dep}] 正在{s_step_upload_dep}......")
    # Assuming requests is available
    import requests as req_dep_kb  # local import for clarity

    response_dep = req_dep_kb.request(
        "POST", upload_temp_docs_url, files=res_files, data=payload
    )  # Added data=payload
    print(response_dep)  # Original print
    print(f"[state]: [{step_createtmpkb_dep}] {s_step_upload_dep} HTTP请求完成")

    for k, v_tuple in res_files:  # Renamed v to v_tuple
        v_tuple[1].close()  # v_tuple is (filename, fileobj, mime)

    tmp_kb_id_dep = None
    if response_dep.status_code == 200:
        tmp_kb_id_dep = response_dep.json()["data"]["id"]
        print(f"[state]: {step_createtmpkb_dep}完成 (KB ID: {tmp_kb_id_dep})")
    else:
        print(
            f"[state]: {step_createtmpkb_dep}完成 (失败，状态码: {response_dep.status_code})"
        )
    return tmp_kb_id_dep


def ask_ai_single_paper(payload):  # Payload is JSON string
    step_askai_single = "ask_ai_single_paper"
    print(f"[state]: 正在{step_askai_single}......")
    file_chat_url = f"{settings.REMOTE_MODEL_BASE_PATH}/chat/kb_chat"
    headers = {"Content-Type": "application/json"}

    s_step_call_model_askai = "调用模型 (单篇文献)"
    print(f"[state]: [{step_askai_single}] 正在{s_step_call_model_askai}......")
    import requests as req_ask_ai
    print(f"payload={payload}")
    response = req_ask_ai.request(
        "POST",
        file_chat_url,
        data=payload,
        headers=headers,
        stream=True,  # Ensure stream=True for iter_lines
    )
    print(response)
    print(f"[state]: [{step_askai_single}] {s_step_call_model_askai} HTTP请求完成")

    ai_reply = ""
    origin_docs = []
    print(response)
    print("Response status code:", response.status_code)
    print("Response headers:", response.headers)
    print("Response content type:", response.headers.get("content-type"))
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode("utf-8").strip()
            if decoded_line.startswith("data:"):
                json_payload_str = decoded_line[len("data:") :].strip()
                if json_payload_str == "[DONE]":
                    print(
                        f"[state]: [{step_askai_single}] Stream finished with [DONE]."
                    )
                    break  # End of stream

                if not json_payload_str:  # Skip empty data lines
                    continue

                try:
                    data_json = json.loads(json_payload_str)

                    # Extract content based on typical OpenAI-like streaming structure
                    choices = data_json.get("choices")
                    if isinstance(choices, list) and choices:
                        delta = choices[0].get("delta")
                        if isinstance(delta, dict):
                            content_chunk = delta.get("content")
                            if content_chunk:  # Append if content is not None or empty
                                ai_reply += content_chunk

                    # Safely extract documents
                    retrieved_docs = data_json.get("docs", [])
                    if isinstance(retrieved_docs, list):
                        for doc_content in retrieved_docs:
                            doc_cleaned = (
                                str(doc_content)
                                .replace(
                                    "\n", " "
                                )  # Corrected from  to \n for string literal
                                .replace("<span style='color:red'>", "")
                                .replace("</span>", "")
                            )
                            origin_docs.append(doc_cleaned)
                except json.JSONDecodeError:
                    print(
                        f"[state]: [{step_askai_single}] Error decoding JSON: '{json_payload_str}'"
                    )
            elif decoded_line:  # Log other non-empty lines if necessary
                print(
                    f"[state]: [{step_askai_single}] Received non-data line: {decoded_line}"
                )

    print(f"[state]: {step_askai_single}完成")
    return ai_reply, origin_docs


@authenticate_user
def create_abstract_report(request, user: User):
    step_create_abs_main = "create_abstract_report入口"
    print(f"[state]: 正在{step_create_abs_main}......")
    request_data = json.loads(request.body)
    document_id = request_data.get("document_id")
    paper_id = request_data.get("paper_id")

    s_step_get_file_info_abs = "获取文档/论文信息 (摘要)"
    print(f"[state]: [{step_create_abs_main}] 正在{s_step_get_file_info_abs}......")
    local_path = ""
    content_type = ""
    title = ""
    if len(document_id) != 0:
        document = UserDocument.objects.get(document_id=document_id)
        local_path = document.local_path
        content_type = document.format
        title = document.title
        p_id = document.title
        abstract = ""
    elif len(paper_id) != 0:
        p = Paper.objects.filter(paper_id=paper_id).first()
        pdf_url = p.original_url.replace("abs/", "pdf/") + ".pdf"
        # Ensure PAPERS_URL directory exists
        papers_url_dir = settings.PAPERS_URL
        if not os.path.exists(papers_url_dir):
            os.makedirs(papers_url_dir, exist_ok=True)
        local_path = os.path.join(
            papers_url_dir, str(p.paper_id) + ".pdf"
        )  # Use os.path.join

        print(local_path)  # Original print
        print(pdf_url)  # Original print
        if not os.path.exists(local_path):
            s_step_dl_abs_report_paper = f"下载论文 {p.paper_id} (摘要)"
            print(
                f"[state]: [{step_create_abs_main}][{s_step_get_file_info_abs}] 正在{s_step_dl_abs_report_paper}......"
            )
            download_paper(url=pdf_url, filename=str(p.paper_id))  # Original call
            print(
                f"[state]: [{step_create_abs_main}][{s_step_get_file_info_abs}] {s_step_dl_abs_report_paper}完成"
            )
        content_type = ".pdf"
        p_id = str(p.paper_id)
        title = p.title
        abstract = p.abstract
    # else: # Original has no else for title initialization here, keeping it
    #     title = ""
    #     local_path = ""
    #     content_type = ""
    print("下载完毕")  # Original print
    print(f"[state]: [{step_create_abs_main}] {s_step_get_file_info_abs}完成")

    # from business.models.abstract_report import AbstractReport # Already imported at top

    # Ensure USER_REPORTS_PATH directory exists
    user_reports_dir_car = settings.USER_REPORTS_PATH
    if not os.path.exists(user_reports_dir_car):
        os.makedirs(user_reports_dir_car, exist_ok=True)
    report_path = os.path.join(
        user_reports_dir_car, str(p_id) + ".md"
    )  # Use os.path.join
    print(report_path)  # Original print

    # FIXME: Sort out the logic of assignment of `ar` here, may need to save the object assigned in the first branch
    ar = AbstractReport.objects.filter(file_local_path=local_path).first()

    # 不存在
    if ar is None:
        s_step_create_new_abs_report = "创建新摘要报告记录和知识库"
        print(
            f"[state]: [{step_create_abs_main}] 正在{s_step_create_new_abs_report}......"
        )
        ar = AbstractReport.objects.create(
            file_local_path=local_path,
            report_path=report_path,
            # user=user,  # Added user to create  -- 太麻烦了，不加了
        )
        print(
            f"[state]: [{step_create_abs_main}][{s_step_create_new_abs_report}] AbstractReport记录创建完成 (ID: {ar.id})"
        )

        upload_temp_docs_url_abs = (
            f"{settings.REMOTE_MODEL_BASE_PATH}/knowledge_base/upload_temp_docs"
        )
        # local_path might start with '/', adjust if necessary for open()
        # The original code `local_path[1:] if local_path.startswith("/") else local_path`
        # is a logic change. Per instructions, I will not add it. Assuming original local_path is fine.
        print(local_path)  # Original print

        # Ensure file name for upload is just the basename + extension
        upload_filename = os.path.basename(local_path)
        if (
            not os.path.splitext(upload_filename)[1] and content_type
        ):  # If basename has no ext, add from content_type
            if not content_type.startswith("."):
                content_type = "." + content_type
            upload_filename += content_type

        files = [
            (
                "files",
                (
                    # str(title) + content_type, # Original, might create weird names if title has special chars or path
                    upload_filename,  # Use cleaned filename
                    open(local_path, "rb"),
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # Original MIME
                ),
            )
        ]
        # Assuming requests is available
        import requests as req_create_abs_kb  # local import for clarity

        # Chatchat requires kb_name for new KB
        kb_name_abs = f"abs_report_kb_{ar.id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        response_abs_kb = req_create_abs_kb.post(
            upload_temp_docs_url_abs, files=files, data={"kb_name": kb_name_abs}
        )
        print(
            f"[state]: [{step_create_abs_main}][{s_step_create_new_abs_report}] 上传文件创建知识库HTTP请求完成"
        )

        for k_file, v_file_tuple in files:  # Renamed k,v
            v_file_tuple[1].close()
        if response_abs_kb.status_code != 200:
            print(f"[state]: {step_create_abs_main}完成 (因连接模型服务器失败而中止)")
            return fail(msg="连接模型服务器失败")
        tmp_kb_id = response_abs_kb.json()["data"]["id"]
        print(tmp_kb_id, report_path, local_path)  # Original print
        print(
            f"[state]: [{step_create_abs_main}][{s_step_create_new_abs_report}] 知识库创建完成 (ID: {tmp_kb_id})"
        )

        s_step_start_abs_thread_car = "启动摘要生成控制线程"
        print(
            f"[state]: [{step_create_abs_main}] 正在{s_step_start_abs_thread_car}......"
        )
        print(f"title={title}, abstract={abstract}")
        AbsControlThread(  # Pass report_id instead of paths for consistency if AbsControlThread is updated
            tmp_kb_id=tmp_kb_id,
            report_path=report_path,
            local_path=local_path,
            title=title,
            abstract=abstract,
        ).start()
        print(f"[state]: [{step_create_abs_main}] {s_step_start_abs_thread_car}完成")
        print(f"[state]: {step_create_abs_main}完成 (新报告流程，正在生成)")
        return ok(msg="正在生成中，请稍后查看")
    elif (
        ar is not None  # ar already exists
        and ar.status == AbstractReport.STATUS_PENDING
        or ar.status
        == AbstractReport.STATUS_IN_PROGRESS  # status is actually int, direct comparison is fine
    ):
        print(f"[state]: {step_create_abs_main}完成 (报告已存在，正在生成中)")
        return ok(msg="正在生成中，请稍后查看")
    elif ar is not None and ar.status == AbstractReport.STATUS_COMPLETED:
        s_step_read_completed_abs = "读取已完成的摘要报告"
        print(
            f"[state]: [{step_create_abs_main}] 正在{s_step_read_completed_abs}......"
        )
        # Ensure report_path exists before opening
        if os.path.exists(ar.report_path):
            with open(ar.report_path, "r", encoding="utf-8") as f_arc:  # Added encoding
                summary_text = f_arc.read()
            print(f"[state]: [{step_create_abs_main}] {s_step_read_completed_abs}完成")
        else:
            summary_text = "摘要报告文件未找到，请重新生成。"
            print(
                f"[warn][{step_create_abs_main}][{s_step_read_completed_abs}] 文件 {ar.report_path} 未找到！"
            )
            print(
                f"[state]: [{step_create_abs_main}] {s_step_read_completed_abs}完成 (文件未找到)"
            )

        print(f"[state]: {step_create_abs_main}完成 (报告已存在并完成)")
        return ok({"summary": summary_text}, msg="生成摘要成功")  # Original return
    else:  # Must be TIMEOUT or other FAILED state
        # assert ar.status == AbstractReport.STATUS_TIMEOUT # Original assert
        s_step_delete_failed_abs = "删除失败/超时的旧摘要报告记录"
        print(
            f"[state]: [{step_create_abs_main}] 正在{s_step_delete_failed_abs} (Status: {ar.status})......"
        )
        ar.delete()  # Original logic
        print(f"[state]: [{step_create_abs_main}] {s_step_delete_failed_abs}完成")
        print(f"[state]: {step_create_abs_main}完成 (旧报告失败，已删除)")
        return fail(msg="生成摘要失败")  # Original return


class AbsControlThread(threading.Thread):
    def __init__(
        self, tmp_kb_id, report_path, local_path, title, abstract
    ):  # Original signature
        threading.Thread.__init__(self)
        self.tmp_kb_id = tmp_kb_id
        self.report_path = report_path
        self.local_path = local_path  # Used to fetch AbstractReport by file_local_path
        self.title = title
        self.abstract = abstract
        self.ttl = 300  # 5分钟
        self.daemon = True
        # self.name = f"AbsControlThread-ForFile-{os.path.basename(local_path)}" # Optional: name for debugging

    def run(self):
        step_absctrl = f"AbsControlThread.run (File: {self.local_path})"
        print(f"[state]: 正在{step_absctrl}......")
        import time  # Local import as per original

        cur = 0
        s_step_start_absgen_in_ctrl = "启动AbsGenThread"
        print(f"[state]: [{step_absctrl}] 正在{s_step_start_absgen_in_ctrl}......")
        a_gen_thread = AbsGenThread(
            self.tmp_kb_id, self.report_path, self.local_path, self.title, self.abstract
        )  # Original args
        a_gen_thread.start()
        print(f"[state]: [{step_absctrl}] {s_step_start_absgen_in_ctrl}完成")

        s_step_monitor_absgen = "监控AbsGenThread"
        print(
            f"[state]: [{step_absctrl}] 正在{s_step_monitor_absgen} (TTL: {self.ttl}s)......"
        )
        while cur < self.ttl:
            # This query can be frequent, consider if AbstractReport ID could be passed and used
            ar_ctrl_loop = AbstractReport.objects.filter(
                file_local_path=self.local_path
            ).first()
            if not ar_ctrl_loop:  # Report might have been deleted
                print(
                    f"[warn][{step_absctrl}][{s_step_monitor_absgen}] AbstractReport for {self.local_path} not found during monitoring. Exiting."
                )
                break
            if ar_ctrl_loop.status == AbstractReport.STATUS_COMPLETED:
                print(
                    f"[state]: [{step_absctrl}][{s_step_monitor_absgen}] AbsGenThread完成 (状态: COMPLETED)"
                )
                print(f"[state]: {step_absctrl}完成")
                return
            cur += 1
            time.sleep(1)

        # If loop finishes, it's a timeout
        print(
            f"[state]: [{step_absctrl}][{s_step_monitor_absgen}] 监控超时或AbsGenThread未在TTL内完成"
        )
        s_step_handle_timeout_ctrl = "处理超时调用a_gen_thread.stop()"
        print(f"[state]: [{step_absctrl}] 正在{s_step_handle_timeout_ctrl}......")
        a_gen_thread.stop()  # Original call
        print(f"[state]: [{step_absctrl}] {s_step_handle_timeout_ctrl}完成")
        print(f"[state]: {step_absctrl}完成 (超时处理完毕)")


class AbsGenThread(threading.Thread):
    def __init__(
        self, tmp_kb_id, report_path, local_path, title, abstract
    ):  # Original signature
        threading.Thread.__init__(self)
        self.tmp_kb_id = tmp_kb_id
        self.report_path = report_path
        self.local_path = local_path
        self.title = title
        self.abstract = abstract
        self.isend = False  # Original flag
        self.daemon = True
        # self.name = f"AbsGenThread-ForFile-{os.path.basename(local_path)}" # Optional

    def run(self):
        # ar_gen might not be available if .get fails, so step name needs care
        step_absgen_run = f"AbsGenThread.run (File: {self.local_path})"
        print(f"[state]: 正在{step_absgen_run}......")

        ar_gen = AbstractReport.objects.filter(
            file_local_path=self.local_path
        ).first()  # Use filter().first() for safety
        if not ar_gen:
            print(
                f"[error][{step_absgen_run}] AbstractReport for {self.local_path} not found. Thread cannot proceed."
            )
            print(f"[state]: {step_absgen_run}完成 (因记录不存在而中止)")
            return

        s_step_set_inprogress = "设置报告状态为IN_PROGRESS"
        print(f"[state]: [{step_absgen_run}] 正在{s_step_set_inprogress}......")
        ar_gen.status = AbstractReport.STATUS_IN_PROGRESS
        # ar_gen.save() # Original does not save here, it saves at the end or on timeout in self.isend
        print(
            f"[state]: [{step_absgen_run}] {s_step_set_inprogress}完成 (内存中状态已更新)"
        )

        summary = ""
        summary += "# 摘要报告\n"  # Initial part

        sections_to_gen = [
            ("研究现状", "请讲述这篇论文研究现状部分\n"),
            ("解决问题", "请讲讲这篇论文解决的问题\n"),
            ("解决方法", "请讲讲这篇论文提出的解决方法\n"),
            ("实验结果", "请讲讲这篇论文实验得到的结果\n"),
            ("结论", "请讲讲这篇论文得出的结论\n"),
        ]

        for i_part, (part_title, part_query) in enumerate(sections_to_gen):
            if self.isend:  # Check before processing each part
                # ar_gen.status = AbstractReport.STATUS_TIMEOUT # Original logic
                # ar_gen.save() # Original logic
                print(
                    f"[state]: [{step_absgen_run}] 因isend=True在生成 '{part_title}' 前中止"
                )
                print(f"[state]: {step_absgen_run}完成 (提前中止)")
                return

            s_step_gen_abs_part = f"生成摘要部分: {part_title}"
            print(f"[state]: [{step_absgen_run}] 正在{s_step_gen_abs_part}......")

            prompt = f"请根据《{self.title}》这篇文章以及它的摘要：{self.abstract}\n分析{part_title}\n。如果搜索不到这部分相关内容，则只输出No。"

            payload_part = json.dumps(
                {
                    "query": prompt + part_query,
                    "mode": "temp_kb",
                    "kb_name": self.tmp_kb_id,  # Original key
                    # "prompt_name": "default",
                }
            )
            response_part_text, docs_part = ask_ai_single_paper(payload=payload_part)
            print(docs_part)  # Original print for docs
            if "No" not in response_part_text:
                summary += f"## {part_title}\n{response_part_text}\n"
            print(f"[state]: [{step_absgen_run}] {s_step_gen_abs_part}完成")

            if self.isend:  # Check again after AI call, as it might take time
                # ar_gen.status = AbstractReport.STATUS_TIMEOUT # Original logic
                # ar_gen.save() # Original logic
                print(
                    f"[state]: [{step_absgen_run}] 因isend=True在生成 '{part_title}' 后中止"
                )
                print(f"[state]: {step_absgen_run}完成 (提前中止)")
                return

        s_step_finalize_summary_abs = "最终化摘要内容"
        print(f"[state]: [{step_absgen_run}] 正在{s_step_finalize_summary_abs}......")
        print(summary)  # Original print of full summary before assigning to response
        response = summary  # Original assignment
        print(response)  # Original print of response (which is summary)
        print(f"[state]: [{step_absgen_run}] {s_step_finalize_summary_abs}完成")

        s_step_save_abs_to_file_db = "保存摘要到文件并更新数据库"
        print(f"[state]: [{step_absgen_run}] 正在{s_step_save_abs_to_file_db}......")
        # Ensure report directory exists before writing
        report_dir_final = os.path.dirname(self.report_path)
        if not os.path.exists(report_dir_final):
            os.makedirs(report_dir_final, exist_ok=True)
        with open(self.report_path, "w", encoding="utf-8") as f_final_abs:
            f_final_abs.write(response)
        ar_gen.report_path = self.report_path  # Already set, but good to be explicit
        ar_gen.status = AbstractReport.STATUS_COMPLETED
        ar_gen.save()
        print(f"[state]: [{step_absgen_run}] {s_step_save_abs_to_file_db}完成")
        print(f"[state]: {step_absgen_run}完成")

    def stop(self):
        step_stop_absgen = f"AbsGenThread.stop (File: {self.local_path})"
        print(f"[state]: 正在{step_stop_absgen}......")
        self.isend = True
        # After setting isend, update status if it's still IN_PROGRESS
        # This is what the original `if self.isend: ar.status = AbstractReport.STATUS_TIMEOUT; return`
        # effectively does if stop() is called and then run() checks isend.
        # To be more direct, if stop is called, the report should reflect that it was interrupted.
        ar_on_stop = AbstractReport.objects.filter(
            file_local_path=self.local_path
        ).first()
        if ar_on_stop and ar_on_stop.status == AbstractReport.STATUS_IN_PROGRESS:
            s_step_update_status_on_stop = "更新报告状态为TIMEOUT (on stop)"
            print(
                f"[state]: [{step_stop_absgen}] 正在{s_step_update_status_on_stop}......"
            )
            ar_on_stop.status = AbstractReport.STATUS_TIMEOUT
            ar_on_stop.error_message = "生成被手动停止或超时中止。"  # Add a message
            ar_on_stop.save()
            print(f"[state]: [{step_stop_absgen}] {s_step_update_status_on_stop}完成")
        print(f"[state]: {step_stop_absgen}完成 (isend设为True)")
