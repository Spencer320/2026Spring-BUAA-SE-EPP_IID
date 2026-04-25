"""
本文件主要处理搜索功能，包括向量化检索和对话检索
API格式如下：
api/serach/...
"""

import json
import os
import queue
import re
import io
from urllib.parse import unquote
import threading
from concurrent.futures import ThreadPoolExecutor

import Levenshtein
import requests
from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.cache import cache
from translate import Translator

from business.models import VectorSearchStorage
from business.models.ai_dialog_storage import DialogSearchStorage, AIDialogStorage
from business.models.paper import Paper
from business.models.search_record import SearchRecord, User
from business.utils.authenticate import authenticate_user
from business.utils.chat_glm import query_glm
from business.utils.chat_r1 import query_r1
from business.utils.chat_tavily import query_tavily
from business.utils.knowledge_base import delete_tmp_kb, build_abs_kb_by_paper_ids
from business.utils.paper_vdb_init import get_filtered_paper
from business.utils.response import ok, fail
from business.utils.scholar_search import search_author, search_entity


def search_papers_by_keywords(keywords):
    # 初始化查询条件，此时没有任何条件，查询将返回所有Paper对象
    query = Q()
    print("keywords:", keywords)
    # 为每个关键词添加搜索条件
    for keyword in keywords:
        query |= Q(title__icontains=keyword) | Q(abstract__icontains=keyword)

    # 使用累积的查询条件执行查询
    result = Paper.objects.filter(query)
    
    filtered_paper_list = []
    for paper in result:
        filtered_paper_list.append(paper)
    return filtered_paper_list


def update_search_record_2_paper(search_record, filtered_papers):
    search_record.related_papers.clear()
    for paper in filtered_papers:
        search_record.related_papers.add(paper)


def vector_query_v2_main(search_content, search_type, search_record: SearchRecord):
    """
    本函数用于处理向量化检索的请求，search_record含不存在则创建，存在（需传参数）则恢复两种情况
    此类检索不包含上下文信息，仅用当前提问对本地知识库检索即可

    得到一个json对象，其中为一个列表，列表中的每个元素为一个文献的信息
    {
        [
            {
                "paper_id": 文献id,
                "title": 文献标题,
                "authors": 作者,
                "abstract": 摘要,
                "time": 发布时间,
                "journal": 期刊,
                "ref_cnt": 引用次数,
                "original_url": 原文地址,
                "read_count": 阅读次数
            }
        ]
    }

    TODO:
        1. 从Request中获取user_id和search_content
        2. 将search_content存入数据库
        3. 使用向量检索从数据库中获取文献信息
        4. 返回文献信息
    """
    conversation_path = search_record.conversation_path

    if not os.path.exists(settings.USER_SEARCH_CONSERVATION_PATH):
        os.makedirs(settings.USER_SEARCH_CONSERVATION_PATH)

    chat_chat_url = f"{settings.REMOTE_MODEL_BASE_PATH}/chat/chat/completions"
    headers = {"Content-Type": "application/json"}

    if search_type == "dialogue":
        search_record.vectorsearchstorage.add_ai_hint("[Dialog] 发起对话检索")
        filtered_papers = do_dialogue_search(
            search_content, chat_chat_url, headers, search_record.vectorsearchstorage
        )
    else:
        search_record.vectorsearchstorage.add_ai_hint("[Pattern] 发起字符检索")
        filtered_papers = do_string_search(search_content)
        if len(filtered_papers) == 0:
            search_record.vectorsearchstorage.terminate([], "很遗憾未能检索出相关论文")
            return

    if len(filtered_papers) == 0:
        ai_reply = (
            f"根据您的需求，Epp论文助手检索到了【{len(filtered_papers)}】篇论文\n"
        )
        print(ai_reply)
    else:
        start_year = min([paper.publication_date.year for paper in filtered_papers])
        end_year = max([paper.publication_date.year for paper in filtered_papers])

        # 发表数量最多的年份
        most_year = max(
            set([paper.publication_date.year for paper in filtered_papers]),
            key=[paper.publication_date.year for paper in filtered_papers].count,
        )

        cnt = len(
            [1 for paper in filtered_papers if paper.publication_date.year == most_year]
        )

        ai_reply = (
            f"根据您的需求，Epp论文助手检索到了【{len(filtered_papers)}】篇论文，其主要分布在【{start_year}】"
            f"到【{end_year}】之间，其中【{most_year}】这一年的论文数量最多，有【{cnt}】篇论文,"
            f"显示出近几年在该领域的研究活跃度较高。\n"
        )
    # return success({"keyword": keyword, 'papers': filtered_paper})

    # return success({"data": "成功", "content": content})
    # 进行总结， 输入标题/摘要
    # papers_summary = f"关键词："
    # papers_summary = "下述论文与主题"
    # for keyword in keywords:
    #     papers_summary += keyword + "，"
    # papers_summary += "密切相关\n"
    papers_summary = ""
    for paper in filtered_papers[:20]:
        papers_summary += f"{paper.title}\n"
        # papers_summary += f'摘要为：{paper.abstract}\n'

    print("papers_summary:", papers_summary)

    payload = json.dumps(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "帮我从这些论文标题中写一份总结:" + papers_summary,
                }
            ],
            "model": settings.CHATCHAT_CHAT_MODEL,
            "prompt_name": "query_summary",
            "temperature": 0.3,
        }
    )

    search_record.vectorsearchstorage.add_ai_hint("[Dialog] 正在进行摘要总结")

    response = requests.request(
        "POST", chat_chat_url, data=payload, headers=headers, stream=False
    )

    if response.status_code == 200:
        lines = response.iter_lines()
        for line in lines:
            decoded_line = line.decode("utf-8")
            print(decoded_line)
            if decoded_line.startswith("data"):
                data = json.loads(decoded_line.replace("data: ", ""))
                ai_reply += data["text"]
            print(f"ai_reply: {ai_reply}")
    else:
        search_record.vectorsearchstorage.terminate(
            [], "检索总结失败，请检查网络并重新尝试"
        )
        return

    update_search_record_2_paper(search_record, filtered_papers)

    # 处理历史记录部分, 无需向前端传递历史记录, 仅需对话文件中添加
    with open(conversation_path, "r") as f:
        conversation_history = json.load(f)

    conversation_history = list(conversation_history.get("conversation"))
    conversation_history.extend(
        [
            {"role": "user", "content": search_content},
            {"role": "assistant", "content": ai_reply},
        ]
    )

    with open(conversation_path, "w") as f:
        # noinspection PyTypeChecker
        json.dump({"conversation": conversation_history}, f, indent=4)

    ### 构建知识库 ###

    search_record.vectorsearchstorage.add_ai_hint("[Knowledge] 正在构建知识库")

    try:
        tmp_kb_id = build_abs_kb_by_paper_ids(
            [paper.paper_id for paper in filtered_papers],
            search_record.search_record_id,
        )
        print(tmp_kb_id)
        insert_search_record_2_kb(search_record.search_record_id, tmp_kb_id)
    except Exception as e:
        search_record.vectorsearchstorage.terminate([], "构建知识库失败")
        print("构建知识库失败:", repr(e))
        return

    print("查询成功")

    # 'keywords': keywords
    search_record.vectorsearchstorage.terminate(filtered_papers, ai_reply)


@authenticate_user
@require_http_methods(["POST"])
def vector_query_v2(request, user: User):
    request_data = json.loads(request.body)
    search_content = request_data.get("search_content")
    search_record_id = request_data.get("search_record_id")
    search_type = request_data.get("search_type")

    if search_record_id is None:
        search_record = SearchRecord(
            user_id=user, keyword=search_content, conversation_path=None
        )
        search_record.save()
        
        conversation_path = os.path.join(
            settings.USER_SEARCH_CONSERVATION_PATH,
            str(search_record.search_record_id) + ".json",
        )
        if os.path.exists(conversation_path):
            os.remove(conversation_path)
        os.makedirs(os.path.dirname(conversation_path), exist_ok=True)
        with open(conversation_path, "w") as f:
            # noinspection PyTypeChecker
            json.dump({"conversation": []}, f, indent=4)
        search_record.conversation_path = conversation_path
        search_record.vectorsearchstorage = VectorSearchStorage.objects.create(
            search_record=search_record,
            conversation=dict(),
        )

        search_record.save()
    else:
        search_record = SearchRecord.objects.get(search_record_id=search_record_id)

    threading.Thread(
        target=vector_query_v2_main,
        args=(search_content, search_type, search_record),
    ).start()

    return ok(
        data={"data": {"search_record_id": search_record.search_record_id}},
        msg="检索已开始，请稍后查看结果",
    )


@authenticate_user
@require_http_methods(["GET"])
def vector_query_v2_get_status(request, user: User):
    search_record = SearchRecord.objects.filter(
        user_id=user, search_record_id=request.GET.get("search_record_id")
    ).first()
    if search_record is None:
        return ok({"data": {"type": "success", "content": "未找到检索记录"}})
    if search_record.vectorsearchstorage.has_terminate():
        return ok({"data": {"type": "success", "content": "检索已完成"}})
    else:
        last = search_record.vectorsearchstorage.get_last_message()
        if not last:
            last = "检索进行中"
        return ok({"data": {"type": "hint", "content": str(last)}})


@authenticate_user
@require_http_methods(["GET"])
def vector_query_v2_get_result(request, user: User):
    search_record_id = request.GET.get("search_record_id")
    search_record = SearchRecord.objects.filter(
        user_id=user, search_record_id=search_record_id
    ).first()

    if search_record is None:
        return ok(
            {
                "data": {
                    "paper_infos": [],
                    "ai_reply": "未找到检索记录",
                    "search_record_id": search_record_id,
                }
            }
        )

    if search_record.vectorsearchstorage.has_terminate():
        content = search_record.vectorsearchstorage.get_terminate()
        papers = []
        for p in content["papers"]:
            paper = Paper.objects.filter(paper_id=p).first()
            if paper is not None:
                papers.append(paper.to_dict())
        return ok(
            {
                "data": {
                    "paper_infos": papers,
                    "ai_reply": content["reply"],
                    "search_record_id": search_record_id,
                }
            }
        )
    else:
        return ok(
            {
                "data": {
                    {
                        "paper_infos": [],
                        "ai_reply": "检索未完成！",
                        "search_record_id": search_record_id,
                    }
                }
            }
        )


@authenticate_user
@require_http_methods(["GET"])
def restore_search_record(request, _: User):
    search_record_id = request.GET.get("search_record_id")
    search_record = SearchRecord.objects.get(search_record_id=search_record_id)
    conversation_path = search_record.conversation_path
    with open(conversation_path, "r") as f:
        history = json.load(f)

    # 取出全部对应论文
    paper_infos = []
    papers = search_record.related_papers.all()
    for paper in papers:
        paper_infos.append(paper.to_dict())
    history["paper_infos"] = paper_infos
    print("history:", paper_infos)
    try:
        kb_id = build_abs_kb_by_paper_ids(
            [paper.paper_id for paper in papers], search_record.search_record_id
        )
        insert_search_record_2_kb(search_record_id, kb_id)
        # history['kb_id'] = kb_id
    except Exception:
        return fail(msg="构建知识库失败")

    return ok(history)


@authenticate_user
@require_http_methods(["GET"])
def get_user_search_history(_, user: User):
    search_records = SearchRecord.objects.filter(user_id=user).order_by("-date")
    keywords = []
    for item in search_records:
        keywords.append(item.keyword)

    return ok({"keywords": list(set(keywords))[:10]})


def kb_ask_ai(payload):
    """
    payload = json.dumps({
        "query": query,
        "knowledge_id": tmp_kb_id,
        "history": conversation_history[-10:],
        "prompt_name": "text"  # 使用历史记录对话模式
    })
    payload = json.dumps({
        "query": query,
        "knowledge_id": tmp_kb_id,
        "prompt_name": "default"  # 使用普通对话模式
    })
    """
    file_chat_url = f"{settings.REMOTE_MODEL_BASE_PATH}/chat/kb_chat"
    headers = {"Content-Type": "application/json"}
    ai_reply = ""
    origin_docs = []
    response = None
    try:
        # 这里服务端通常以 SSE/分块方式返回（data: {...} + [DONE]）。
        # 使用 stream=True 才能稳定消费 iter_lines；并设置超时避免长期挂起。
        timeout_s = float(getattr(settings, "RA_HTTP_TIMEOUT", 15.0) or 15.0)
        response = requests.request(
            "POST",
            file_chat_url,
            data=payload,
            headers=headers,
            stream=True,
            timeout=(2.0, timeout_s),
        )
        print("response from file_chat", response)

        for line in response.iter_lines():
            if not line:
                continue
            decoded_line = line.decode("utf-8", errors="ignore").strip()
            if not decoded_line:
                continue
            if decoded_line.startswith("data:"):
                json_payload_str = decoded_line[len("data:") :].strip()
                if json_payload_str == "[DONE]":
                    break
                if not json_payload_str:
                    continue
                try:
                    data = json.loads(json_payload_str)
                except json.JSONDecodeError:
                    # 服务端偶发输出非完整 JSON，跳过该 chunk
                    continue

                # 流式增量内容
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                    if isinstance(delta, dict):
                        chunk = delta.get("content")
                        if chunk:
                            ai_reply += chunk

                for doc in data.get("docs", []) or []:
                    doc = (
                        str(doc)
                        .replace("\n", " ")
                        .replace("<span style='color:red'>", "")
                        .replace("</span>", "")
                    )
                    origin_docs.append(doc)
    except requests.exceptions.ChunkedEncodingError as e:
        # 典型原因：服务端提前断开/代理中断导致 chunked 响应不完整。
        # 这里直接返回已累计的部分结果，避免把整个线程打崩。
        print(f"[kb_ask_ai][warn] ChunkedEncodingError: {e}")
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
        print(f"[kb_ask_ai][warn] Timeout: {e}")
    except requests.exceptions.RequestException as e:
        print(f"[kb_ask_ai][warn] RequestException: {e}")
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
    return ai_reply, origin_docs


def dialog_query_v2_main(search_record_id, message):
    kb_id = get_tmp_kb_id(search_record_id)

    try:
        ai_dialog_db = SearchRecord.objects.get(
            search_record_id=search_record_id
        ).dialogsearchstorage
    except SearchRecord.DoesNotExist:
        ai_dialog_db = None
    if ai_dialog_db is None:
        return

    search_record = SearchRecord.objects.filter(
        search_record_id=search_record_id
    ).first()
    conversation_path = (
        settings.USER_SEARCH_CONSERVATION_PATH
        + "/"
        + str(search_record.search_record_id)
        + ".json"
    )
    history = {}
    if os.path.exists(conversation_path):
        c = json.loads(open(conversation_path).read())
        history = c
    # 先判断下是不是要查询论文
    prompt = f"""
    想象你是一个科研助手，你手上有一些论文，你判断用户的需求是不是要求你去搜索新的论文而不需要帮你回答某些问题，你的回答只能是"yes"，"no"或"maybe"。
    如果你不确定，请回答"maybe"。如果用户需求包含"分析"、"总结"、"说明"等词语，请回答"no"。
    例如：
    1. Q：帮我写一个去上海的旅游计划。A：no
    2. Q：帮我寻找一些关于强化学习的论文。A：yes
    3. Q：帮我搜索关于对抗攻击的相关研究。A：yes
    4. Q：循环神经网络和卷积神经网络的区别是什么？A：no
    5. Q：查询王德庆教授的信息？A：no
    6. Q：关于图像识别的最新研究有哪些？A：maybe
    他的需求是：
    {message}
    """
    ai_dialog_db.add_ai_hint("[PreCheck] 判断用户需求 ......")
    response_type = query_glm(prompt)
    print("response from glm:", response_type)
    if "yes" in response_type:  # 担心可能有句号等等
        ai_dialog_db.add_ai_hint("[Query] 启动查询论文 ......")
        # 查询论文，TODO:接入向量化检索
        # filtered_paper = query_with_vector(message) # 旧版的接口，换掉了 2024.4.28
        # filtered_paper = get_filtered_paper(text=message, k=5)
        chat_chat_url = f"{settings.REMOTE_MODEL_BASE_PATH}/chat/chat/completions"
        headers = {"Content-Type": "application/json"}
        filtered_paper = do_dialogue_search(
            message, chat_chat_url, headers, ai_dialog_db
        )
        dialog_type = "query"
        papers = []
        for paper in filtered_paper:
            # search_record.related_papers.add(paper)
            # search_record.save()
            papers.append(paper)
        print(papers)

        step = "搜索文献列表"
        print("[state]:", f"正在{step}......")

        content = "根据您的需求，我们检索到了一些论文信息"
        # for i in range(len(papers)):
        #     content += '\n' + f'第{i}篇：'
        #     # TODO: 这里需要把papers的信息整理到content里面
        #     content += f'标题为：{papers[i]["title"]}\n'
        #     content += f'摘要为：{papers[i]["abstract"]}\n'
        history["conversation"].extend([{"role": "user", "content": message}])
        history["conversation"].extend([{"role": "assistant", "content": content}])

        ai_dialog_db.add_ai_hint("[Query] 检索即将完成 ......")
    else:
        ai_dialog_db.add_ai_hint("[Dialog] 启动文献内容对话 ......")

        ############################################################

        ## 这部分重新重构了，按照方法是通过将左侧的文章重构成为一个知识库进行检索

        ###########################################################
        # 对话，保存3轮最多了，担心吃不下
        input_history = (
            history["conversation"].copy()[-5:]
            if len(history["conversation"]) > 5
            else history["conversation"].copy()
        )
        print("input_history:", input_history)
        print("kb_id:", kb_id)
        print("message:", message)
        dispatch_prompt = f"""
        现在用户提出了一个问题，请你判断：这个问题是否涉及学术领域的知识，回答"yes"或者"no"，不要输出其他内容。
        例如：
        1. Q：帮我写一个去上海的旅游计划。A：no
        2. Q：什么是强化学习的蒙特卡洛算法。A：yes
        3. Q：针对乳腺癌的靶向治疗研究进展。A：yes
        4. Q：给出几个词：上班、指南针、狐狸，用这些词写出一个故事。A：no
        5. Q：查询王德庆教授的信息？A：yes
        现在，对于问题{message}，请给出你的判断结果。
        """

        ai_dialog_db.add_ai_hint("[Dialog] 正在判断问题类型 ......")
        dispatch_res = query_r1(dispatch_prompt)
        need_additional_knowledge = "yes" in dispatch_res
        print(f"[info] 对于问题{message}， 需要分发：{need_additional_knowledge}")

        if need_additional_knowledge:
            ai_reply = solve_recursively(ai_dialog_db, input_history, kb_id, message, 0)
        else:
            ai_dialog_db.add_ai_hint("[Dialog] 调研助手正在思考 ......")
            ai_reply = query_glm(message, input_history)

        ai_dialog_db.add_ai_hint("[Dialog] 即将完成 ......")
        print(ai_reply)
        dialog_type = "dialog"
        papers = []
        # 转述效果不好
        # content = query_glm(
        #     "你叫epp论文助手，以你的视角重新转述这段话：" + ai_reply, []
        # )
        content = ai_reply
        history["conversation"].extend([{"role": "user", "content": message}])
        history["conversation"].extend([{"role": "assistant", "content": content}])
    with open(conversation_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(history))
    # res = {"dialog_type": dialog_type, "papers": papers, "content": content}
    ai_dialog_db.terminate(papers, dialog_type, content)


@authenticate_user
@require_http_methods(["POST"])
def dialog_query_v2(request, _: User):
    """
    本函数用于处理对话检索的请求
    :param request: 请求，类型为POST
        内容包含：{
            message: string
            ,
            paper_ids:[
                string, //很多个paper_id
            ]
            ,
            tmp_kb_id : string // 临时知识库id
        }
    :param _: 发起当前请求的用户对象
    :return: 返回一个json对象，格式为：
    {
        dialog_type: 'dialog' or 'query',
        papers:[
            {//只有在dialog_type为'query'时才有，这时需要前端对文献卡片进行渲染。
                "paper_id": 文献id,
                "title": 文献标题,
                "authors": 作者,
                "abstract": 摘要,
                "publication_date": 发布时间,
                "journal": 期刊,
                "citation_count": 引用次数,
                "original_url": 原文地址,
                "read_count": 阅读次数
            },
        ],
        content: '回复内容'
    }
    """
    data = json.loads(request.body)
    message = data.get("message")
    search_record_id = data.get("search_record_id")

    search_record = SearchRecord.objects.filter(
        search_record_id=search_record_id
    ).first()
    if search_record is None:
        return fail(msg="未找到检索记录")
    try:
        _ = search_record.dialogsearchstorage
    except SearchRecord.dialogsearchstorage.RelatedObjectDoesNotExist:
        search_record.dialogsearchstorage = DialogSearchStorage.objects.create(
            search_record=search_record,
            conversation=dict(),
        )
        search_record.save()

    search_record.dialogsearchstorage.add_user_message(message)

    threading.Thread(
        target=dialog_query_v2_main,
        args=(search_record_id, message),
    ).start()

    return ok(msg="对话检索已开始，请稍后查看结果")


@authenticate_user
@require_http_methods(["GET"])
def dialog_query_v2_get_status(request, user: User):
    search_record_id = request.GET.get("search_record_id")
    search_record = SearchRecord.objects.filter(
        user_id=user, search_record_id=search_record_id
    ).first()
    if search_record is None:
        return ok({"data": {"type": "success", "content": "未找到检索记录"}})

    if search_record.dialogsearchstorage.has_result():
        return ok({"data": {"type": "success", "content": "检索已完成"}})
    else:
        last = search_record.dialogsearchstorage.get_hint()
        return ok({"data": {"type": "hint", "content": str(last)}})


@authenticate_user
@require_http_methods(["GET"])
def dialog_query_v2_get_result(request, user: User):
    search_record_id = request.GET.get("search_record_id")
    search_record = SearchRecord.objects.filter(
        user_id=user, search_record_id=search_record_id
    ).first()

    if search_record is None:
        return ok(
            {
                "dialog_type": "dialog",
                "papers": [],
                "content": "抱歉你的操作可能有误",
            }
        )

    if search_record.dialogsearchstorage.has_result():
        content = search_record.dialogsearchstorage.get_last_message()
        papers = []
        for p in content["papers"]:
            paper = Paper.objects.filter(paper_id=p).first()
            if paper is not None:
                papers.append(paper.to_dict())
        return ok(
            {
                "dialog_type": content["dialog_type"],
                "papers": papers,
                "content": content["content"],
            }
        )
    else:
        return ok(
            {
                "dialog_type": "dialog",
                "papers": [],
                "content": "检索未完成！",
            }
        )


# Feedback
def _extract_feedback(response):
    """
    解析反馈结果的正则表达式
    """
    pattern = (
        r"Feedback: (.*?)(?:Question: (.*?))?(?=\nFeedback: |\n\[Response_End\]|$)"
    )
    return re.findall(pattern, response, re.DOTALL)


def generate_feedback(question, answer, tmp_kb_id):
    """生成改进反馈"""
    # 反馈生成提示词
    feedback_prompt = """
    根据基于最新科学文献的科学问题回答，列出反馈清单。请优先列出最关键的改进建议。内容改进建议通常可以包括：要求提供不同任务的结果/应用示例、详细阐述关键方法细节、建议包含其他流行方法。
    风格改进可包括更好的组织结构或文字润色。对于每个需要文献中未讨论的额外信息的改进建议，请提出一个问题来指导缺失细节的搜索。
    如果反馈主要涉及风格或组织结构的改变，则无需提出额外问题。回答需标记[Response_Start]和[Response_End]。
    每个反馈前标注'Feedback: '，额外问题前标注'Question: '。你的问题将用于搜索额外上下文，应自成一体且无需额外背景即可理解。
    示例：
    ##
    问题: {example_question}
    回答: {example_answer}
    [Response_Start]{example_feedback}[Response_End]
    现在请生成针对以下问题的反馈：
    ##
    """
    prompt = feedback_prompt.format(
        example_question="检索增强语言模型的优势是什么？",
        example_answer="检索增强模型可以减少幻觉",
        example_feedback="Feedback: 回答缺少具体示例\nQuestion: 检索增强模型有哪些成功应用案例？",
    )

    message = f"{prompt}\n问题： {question}\n回答： {answer}"

    payload = {
        "query": message,
        "knowledge_id": tmp_kb_id,
        "mode": "temp_kb",
        "kb_name": tmp_kb_id,
        "score_threshold": 0.8,
        "stream": True,
    }

    payload = json.dumps(payload)

    feedback_answer, origin_docs = kb_ask_ai(payload)
    print("feedback_answer:", feedback_answer)
    return feedback_answer


def revise_answer(question, origin_answer, feedback, references, kb_name, expert: str):
    """根据反馈修订答案"""
    # 答案修订提示词
    editing_prompt = """
    根据提供的科学问题、语言模型的回答以及反馈意见，改进原始回答。仅修改反馈指出的需要改进的部分，保留其他未提及的句子。
    除非反馈明确指出应删除错误句子，否则不得省略原始回答中的关键信息。新增段落或讨论时，确保不与原有内容重复。
    使用参考文献列表中已有的引用支持新讨论（使用引用编号）。除非反馈要求删除错误句子或重组段落，否则不得删除原始回答中的换行或段落。
    回答需标记[Response_Start]和[Response_End]。

    参考文献：
    {passages}

    问题: {question}
    原始回答: {answer}
    反馈意见: {feedback}
    请给出修订后的回答：
    """

    prompt = editing_prompt.format(
        passages="\n".join([f"[{i}] {ref}" for i, ref in enumerate(references)]),
        question=question,
        answer=origin_answer,
        feedback=feedback,
    )

    if expert == "search":
        ai_reply_with_ref = query_tavily(prompt)
    elif expert == "api" or expert == "llm":
        payload = json.dumps(
            {
                "query": prompt,
                "mode": "temp_kb",
                "score_threshold": 0.5,
                "kb_name": kb_name,
            }
        )
        ai_reply, origin_docs = kb_ask_ai(payload)
        origin_docs = list(set(origin_docs).union(set(references)))
        ref_str = ""
        i = 1
        print(f"共{len(origin_docs)}篇参考文献")
        for origin_doc in origin_docs:
            title, content = extract_reference_info(origin_doc)
            ref_str += f"参考文献[{i}]：标题：{title}；内容：{content}\n"
            i += 1

        ref_prompt = (
            f"请按照尾注+交叉引用的方式，在正文中添加这些参考文献的引用。尾注只需要列举参考文献序号和标题，不需要列出具体内容。"
            f"不需要的参考文献不用再列举，但是要重新整理序号。*正文*：\n{ai_reply}。*参考文献*：\n{ref_str}"
        )
        ai_reply_with_ref = query_glm(ref_prompt)
    else:
        ai_reply_with_ref = "出现错误，无法回答"

    return ai_reply_with_ref


def feedback(message, answer, ref, kb_name, expert: str):
    """
    实现Feedback
    """

    feedback_answer = generate_feedback(message, answer, kb_name)
    revise = revise_answer(
        message, answer, feedback_answer, ref, kb_name, expert=expert
    )

    print("origin answer:", answer)
    print("feedback:", feedback_answer)
    print("revise answer:", revise)

    return revise


def answer2dict(raw: str) -> dict | None:
    """
    如果要求以json格式回答，可以用本函数提取dict
    """
    formatted = re.findall(r"{.*}", raw, flags=re.S)[0]
    while True:
        try:
            ans = json.loads(formatted)
            return ans
        except:
            revise_prompt = f"有一个json，它的格式有点问题，请你调整一下。你只用输出修改后的json，不要输出多余内容。要修改的json是：\n{formatted}"
            raw, _ = query_r1(revise_prompt)
            formatted = re.findall(r"{.*}", raw, flags=re.S)[0]


def answer2list(raw: str) -> list | None:
    formatted = re.findall(r"\[.*]", raw, flags=re.S)[0]
    while True:
        try:
            ans = json.loads(formatted)
            return ans
        except:
            revise_prompt = f"有一个json，它的格式有点问题，请你调整一下。你只用输出修改后的json，不要输出多余内容。要修改的json是：\n{formatted}"
            raw, _ = query_r1(revise_prompt)
            formatted = re.findall(r"\[.*]", raw, flags=re.S)[0]


def solve_recursively(
    ai_dialog_db: DialogSearchStorage,
    history: list,
    kb_id,
    message,
    sub_id,
    depth=0,
    max_depth=1,
) -> str:
    """
    学术问答，拆解子问题并递归整合
    :param ai_dialog_db: 对话数据库对象
    :param history: 对话历史，[{'role': 'xx', content: 'xx'}]
    :param kb_id: 临时数据库id，用于原生大模型的知识库
    :param message: 当前对话
    :param sub_id: 子问题ID
    :param depth: 当前深度，不用管
    :param max_depth: 最大深度，复杂的O(4^{max_depth})，建议==1
    :return: 整合结果
    """
    # 拆解
    if depth >= max_depth:
        return solve_multi_agent(ai_dialog_db, history, kb_id, message, sub_id)

    split_prompt = f"""
    请分析用户的问题类型，并决定是否需要拆分成子问题。

    问题类型判断标准：
    1. 简单查询类：如查询学者信息、论文信息、会议信息等，这类问题不需要拆分
    2. 复杂分析类：如技术发展趋势、方法比较、综述类问题等，这类问题需要拆分

    请以json格式回答：
    如果不需要拆分，直接返回原问题：
    {{
        "sub_queries": ["原问题"]
    }}

    如果需要拆分，返回2-3个子问题：
    {{
        "sub_queries": ["子问题1", "子问题2", ...]
    }}

    示例1 - 简单查询：
    问题："查询学者张三的研究成果"
    回答：
    {{
        "sub_queries": ["查询学者张三的研究成果"]
    }}

    示例2 - 复杂分析：
    问题："我想学习大模型强化学习技术"
    回答：
    {{
        "sub_queries": [
            "强化学习的理论基础",
            "强化学习对大模型微调的作用",
            "大模型强化学习技术的最新进展",
            "未来大模型强化学习技术的发展趋势"
        ]
    }}

    对于问题"{message}"，请给出你的回答
    """

    ai_dialog_db.add_ai_hint("[Dialog] 正在拆解子问题 ......")
    split_res = query_r1(split_prompt, r1_model="deepseek-reasoner")
    sub_queries = answer2dict(split_res[0])["sub_queries"]
    print("[sub_queries]: ", sub_queries)

    print("[state]:", f"拆解子问题完成，有{len(sub_queries)}个子问题待思考")

    sub_answers = []
    for sub_id, sub_query in enumerate(sub_queries):
        step = f"子问题[{sub_id + 1} / {len(sub_queries)}]"
        ai_dialog_db.add_ai_hint(f"[Dialog] 正在思考 {step} ......")
        sub_answers.append(
            solve_recursively(
                ai_dialog_db, history, kb_id, sub_query, sub_id, depth=depth + 1
            )
        )

    step = "文献调研助手"
    print("[state]:", f"子问题思考完成，{step}正在整合回答......")

    merge_prompt = f"""
    用户提出了一个问题，这个问题被拆解成了如下几个子问题并分别得到了回答。请把他们汇总整合，回答用户提出的原问题。
    要求保留相关证据来源（如网页链接、文献链接、论文题目等），并去掉没有意义的部分。
    原问题：{message}；
    """ + "\n".join(
        [
            f"子问题{i}：{sub_queries[i]}；回答：{sub_answers[i]}"
            for i in range(len(sub_queries))
        ]
    )
    ai_dialog_db.add_ai_hint(f"[Dialog] 整合子问题回答 ......")
    print(f"[solve_recursively] 深度{depth}，提示词：\n{merge_prompt}")
    return query_r1(merge_prompt)[0]


def pdf_to_txt(pdf_byte_content, title):
    """
    如果chatchat的OCR太慢，直接转换成纯文本加速上传
    """
    import fitz  # PyMuPDF

    def extract_text_from_pdf_bytes(pdf_bytes):
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
        return text

    pdf_text = extract_text_from_pdf_bytes(pdf_byte_content)
    # 构造内存中文件对象（模拟 txt 文件）
    text_file = io.StringIO(pdf_text)

    file = (
        "files",
        (title + ".txt", text_file, "text/plain"),
    )
    return file


def build_kb_by_queries(queries: list[str], max_results=4):
    import arxiv

    kb_id = None
    paper_list = queue.Queue()
    arxiv_client = arxiv.Client()
    domains = []
    for query in queries:
        search = arxiv.Search(
            query=query, max_results=max_results, sort_by=arxiv.SortCriterion.Relevance
        )
        domains.append(arxiv_client.results(search))

    def _update_tmp_kb():
        nonlocal kb_id
        upload_temp_docs_url = (
            f"{settings.REMOTE_MODEL_BASE_PATH}/knowledge_base/upload_temp_docs"
        )
        while True:
            print("[update-tmp-kb] kb_id is: ", kb_id)
            data_field = {"prev_id": kb_id} if kb_id else None
            file_tuple = paper_list.get()
            if file_tuple is None:  # 遇到结束信号则退出
                paper_list.task_done()
                break
            response = requests.post(
                upload_temp_docs_url, files=[file_tuple], data=data_field
            )
            if response.status_code != 200:
                raise Exception(f"连接模型服务器失败，错误代码{response.status_code}")
            kb_id = response.json()["data"]["id"]
            paper_list.task_done()

    def _download_paper():
        for results in domains:
            for result in results:
                print("[result]: ", result.title)
                file = cache.get(result.pdf_url)
                if not file:
                    try:
                        rsp = requests.get(
                            result.pdf_url.replace("arxiv.org", "export.arxiv.org"),
                            timeout=(5, 30),
                        )
                    except requests.exceptions.Timeout:
                        print("[timeout]")
                        continue
                    pdf_content = rsp.content
                    file = pdf_to_txt(pdf_content, result.title)
                    cache.set(result.pdf_url, file, timeout=1800)
                print("[done]: ", result.title)
                paper_list.put(file)

        paper_list.put(None)

    prod_thread = threading.Thread(target=_download_paper)
    cons_thread = threading.Thread(target=_update_tmp_kb)

    prod_thread.start()
    cons_thread.start()

    prod_thread.join()
    cons_thread.join()
    return kb_id


def extract_reference_info(s):
    # 1. 提取文件名（从括号内的 URL 中解析）
    # 匹配方括号内的链接部分（例如 [...] 中的内容）
    url_match = re.search(r"\((.*?\.txt)\)", s)
    if not url_match:
        return None, None

    url_path = url_match.group(1)
    # 解码 URL 特殊字符（如 %2F → /，%20 → 空格）
    decoded_path = unquote(url_path)
    # 提取最后一个 / 后的文件名（去掉 .txt）
    filename = decoded_path.split("/")[-1].replace(".txt", "").replace("+", " ")

    # 2. 提取文献内容（括号后的文本）
    content = s.split(")")[-1].strip()

    return filename, content


def local_expert_dispatch(message: str, history=None, state_queue=None) -> str:
    dispatch_prompt = f"""你是科研助手，用户问了一个问题，你需要判断这个问题的类型是：
1. 查询某个学者
2. 查询某个研究机构
3. 其他
你只需要回答相应序号
例如：
- 问题：我想了解一下Stanford的Jure Leskovec
- 回答：1

- 问题：介绍一下北京航空航天大学
- 回答：2

- 问题：什么是深度学习？
- 回答：3

现在，对于用户的问题，做出你的回答：
- 问题：{message}
- 回答："""

    answer, _ = query_r1(dispatch_prompt)
    if "1" in answer:
        print("本地api：使用学者查询")
        if state_queue:
            state_queue.put((3, "[Dialog] API专家 启动学者查询 ......"))
        return do_scholar_search(message, history, state_queue=state_queue)
    elif "2" in answer:
        print("本地api：使用机构查询")
        if state_queue:
            state_queue.put((3, "[Dialog] API专家 启动科研机构查询 ......"))
        return do_search_entity(message, history, state_queue=state_queue)
    else:
        print("本地api：使用arXiv检索查询")
        if state_queue:
            state_queue.put((3, "[Dialog] API专家 启动文献知识库查询 ......"))
        return solve_api_expert(message, history, state_queue=state_queue)


def do_scholar_search(message, history=None, state_queue=None) -> str:
    extract_prompt = f"""你是科研助手，用户希望查找某个学者，请从用户的提问中获取作者的姓名和工作单位，转换成英文的标准形式。
请以json格式回答：
{{
    "name_CN": "The Chinese name of the scholar if exists, else return an empty string",
    "name": "The scholar's English name",
    "affiliation": "The scholar's affiliation (return an empty string if unknown)"
}}

例如：
- 问题："我想了解一下北京航空航天大学的王德庆老师"
- 回答：
{{
    "name_CN": "王德庆",
    "name": "Deqing Wang",
    "affiliation": "Beihang University"
}}

- 问题："请介绍Jure Leskovec的相关信息"
- 回答：
{{
    "name_CN": "", 
    "name": "Jure Leskovec",
    "affiliation": ""
}}

现在，对于用户的提问，给出你的回答。
- 问题："{message}"
- 回答："""
    answer, _ = query_r1(extract_prompt)
    dict_res = answer2dict(answer)
    flag, result = search_author(
        dict_res["name"], dict_res["affiliation"], dict_res["name_CN"]
    )
    if state_queue:
        state_queue.put((3, "[Dialog] API专家 完成学者查询 ......"))
    return result


def do_search_entity(message, history=None, state_queue=None) -> str:
    extract_prompt = f"""你是科研助手，用户希望查找某个研究机构，请从用户的提问中获取机构的名称，转换成英文的标准形式。
请以json格式回答：
{{
    "name_CN": "The Chinese name of the institute if exists, else return an empty string",
    "name": "The institute's English name"
}}

例如：
- 问题：我想了解一下上海人工智能实验室
- 回答：
{{
    "name_CN": "上海人工智能实验室",
    "name": "Shanghai AI Lab"
}}

- 问题：我想了解一下OpenAI
- 回答：
{{
    "name_CN": "",
    "name": "OpenAI"
}}

现在，对于用户的问题，给出你的回答：
- 问题：{message}
- 回答："""
    answer, _ = query_r1(extract_prompt)
    answer_dict = answer2dict(answer)
    flag, result = search_entity(answer_dict["name"], answer_dict["name_CN"])
    if state_queue:
        state_queue.put((3, "[Dialog] API专家 完成机构查询 ......"))
    return result


def solve_api_expert(message, history=None, max_domain=1, *, state_queue) -> str:
    decompose_prompt = f"""
你是文献调研助手，用户问了一个问题，你需要判断解决这个问题需要参考哪些直接相关的领域的文献，并用英文回答，以json形式返回：
{{
    domains: ["domain1", "domain2", ...]
}}
示例：用户询问"请比较YOLO算法和DETR算法的优劣"，你需要回答：
{{
    domains: ["YOLO (you only look once) algorithm", "DETR (DEtection TRansformer) model"]
}}

注意：可以有一个或多个并列的领域，你不要进行引申和泛化。如果领域1是"YOLO"，那么后面的领域就不能是："Computer Vision"或"Deep Learning",
这些都是"YOLO"的泛化。

现在，对于问题{message}，你的回答是：
"""
    raw_answer = query_r1(decompose_prompt)[0]
    print("[solve_api_expert]: answer is " + raw_answer)
    dict_answer = answer2dict(raw_answer)
    domains = dict_answer["domains"][:max_domain]
    if state_queue:
        state_queue.put((3, f"[Dialog] API专家 正在下载参考文献 ......"))
    tmp_kb_id = build_kb_by_queries(domains)
    payload_dict = {
        "query": message,
        "knowledge_id": tmp_kb_id,
        "mode": "temp_kb",
        "kb_name": tmp_kb_id,
        "score_threshold": 0.8,
        "stream": True,
    }
    if history:
        payload_dict["history"] = list(history)
    payload = json.dumps(payload_dict)
    if state_queue:
        state_queue.put((3, f"[Dialog] API专家 正在依据参考文献推理 ......"))
    ai_reply, origin_docs = kb_ask_ai(payload)
    ref_str = ""
    i = 1
    print(f"共{len(origin_docs)}篇参考文献")
    for origin_doc in origin_docs:
        title, content = extract_reference_info(origin_doc)
        ref_str += f"参考文献[{i}]：标题：{title}；内容：{content}\n"
        i += 1

    ref_prompt = (
        f"请按照尾注+交叉引用的方式，在正文中添加这些参考文献的引用。尾注只需要列举参考文献序号和标题，不需要列出具体内容。"
        f"不需要的参考文献不用再列举，但是要重新整理序号。*正文*：\n{ai_reply}。*参考文献*：\n{ref_str}"
    )
    ai_reply_with_ref = query_glm(ref_prompt)
    if state_queue:
        state_queue.put((3, f"[Dialog] API专家 正在自反思 ......"))
    # feedback
    ai_reply_with_ref = feedback(
        message, ai_reply_with_ref, ref=origin_docs, expert="api", kb_name=tmp_kb_id
    )
    if state_queue:
        state_queue.put((3, f"[Dialog] API专家 完成回答 ......"))
    return ai_reply_with_ref


def solve_multi_agent(
    ai_dialog_db: DialogSearchStorage,
    history,
    kb_id,
    message,
    sub_id,
    depth=0,
    max_depth=0,
) -> str:
    """
    多智能体回答
    :param ai_dialog_db: 对话数据库对象
    :param history: 对话历史，[{'role': 'xx', content: 'xx'}]
    :param kb_id: 临时数据库id，用于原生大模型的知识库
    :param message: 当前对话
    :param sub_id: 子问题ID
    :param depth: 当前深度，不用管
    :param max_depth: 最大深度，复杂的O(4^{max_depth})，建议==1
    :return: 结果
    """
    # TODO 可以考虑原生LLM置信度，进行评价
    payload = json.dumps(
        {
            "query": message,
            "mode": "temp_kb",
            "kb_name": kb_id,
            "history": list(history),
        }
    )

    state_queue = queue.Queue()

    def hint_daemon(queue):
        hint_map = {}
        while True:
            hint = queue.get()  # 阻塞直到有内容
            if hint is None:
                break  # 如果接收到 None，说明要退出
            hint_map[hint[0]] = hint[1]
            result = "\n".join(list(hint_map.values()))
            ai_dialog_db.add_ai_hint(result)

    # 守护线程启动
    daemon_thread = threading.Thread(
        target=hint_daemon, args=(state_queue,), daemon=True
    )
    daemon_thread.start()

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_kb = executor.submit(kb_ask_ai, payload)
        future_tavily = executor.submit(query_tavily, message)
        future_api = executor.submit(
            local_expert_dispatch, message, history, state_queue
        )
        try:
            step = "原生LLM专家"
            ai_dialog_db.add_ai_hint(
                f"[Dialog] {step} 正在思考子问题 [{sub_id}] ......"
            )
            ori_reply, _ = future_kb.result()
            state_queue.put((1, f"[Dialog] {step} 思考子问题 [{sub_id}] 完成 ......"))
            print("[state]:", f"{step}思考子问题[{sub_id}]完成")
        except Exception as e:
            step = "原生LLM专家"
            ori_reply = "出现异常，无法回答"
            print("[state]:", f"{step}{ori_reply}", repr(e))

        try:
            step = "搜索引擎专家"

            ai_dialog_db.add_ai_hint(
                f"[Dialog] {step} 正在思考子问题 [{sub_id}] ......"
            )
            travily_result = future_tavily.result()
            state_queue.put((2, f"[Dialog] {step} 思考子问题 [{sub_id}] 完成 ......"))
            print("[state]:", f"{step}思考子问题[{sub_id}]完成")
        except Exception as e:
            step = "搜索引擎专家"
            travily_result = "出现异常，无法回答"
            print("[state]:", f"{step}{travily_result}", repr(e))

        try:
            api_result = future_api.result()

        except Exception as e:
            step = "API专家"
            api_result = "出现异常，无法回答"
            print("[state]:", f"{step}{api_result}", repr(e))

    state_queue.put(None)  # 发送退出信号
    daemon_thread.join()
    collect_prompt = f"""
    你是EPP论文助手，你的任务是整合来自三个专家伙伴（"API专家"、"搜索引擎专家"、"原生LLM专家"）的回答，以回复用户的问题："{message}"

    整合要求：
    1.  可信度分析：简要评估各专家回答的可信度。如果存在冲突，请指出并给出你的判断。
    2.  核心内容整合：提取各专家回答中的核心信息，融合成一个全面、连贯且逻辑清晰的答案。
    3.  简洁明了：你的回答应直接切入主题，避免冗余客套话（例如，不要使用"根据提供的信息..."、"综上所述..."等开头）。
    4.  保留并整合证据：
          所有来源：必须清晰展示并整合所有专家提供的证据，包括网页链接、论文ID/标题、以及"API专家"提供的详细参考文献。
          交叉引用：如果原始回答中包含如 `[1]`, `[2]` 这样的交叉引用标记，务必在整合后的正文中保留它们，并确保它们指向正确的参考文献。
          "API专家"的参考文献："API专家"的回答通常包含一个"*参考文献*"部分，其中列有详细文献条目。这部分内容必须完整地、准确地呈现在最终答案的末尾。如果其他专家也提供了类似格式的参考文献，也请一并整合。
          统一的参考文献列表：在整个回答的最后，提供一个统一、清晰的参考文献列表。如果可能，对来自不同专家的文献进行去重和重新编号，并确保正文中的引用标记与最终列表中的编号一致对应。
    5.  无法回答：如果所有专家的回答都不可信或信息不足，请直接回复"很抱歉无法回答"。

    可信度分析标准（供你内部参考）：
    -   证据支持度（40%）：引用文献数量/质量，与问题相关性。
    -   来源权威性（30%）：顶级期刊/机构，权威/专业网页。
    -   时效性（20%）：5年内最新数据。
    -   内部一致性（10%）：陈述是否自相矛盾。

    专家们的回答：

    "API专家"的回答：
    '''{api_result}'''

    "搜索引擎专家"的回答：
    '''{travily_result}'''

    "原生LLM专家"的回答：
    '''{ori_reply}'''

    请严格按照上述要求，给出你的最终整合回答。
    """
    step = "多智能体"
    ai_dialog_db.add_ai_hint(f"[Dialog] 多智能体回答整合中 ......")
    ai_reply = query_glm(collect_prompt)

    # 如果深度小于最大深度，并且回答是"很抱歉无法回答，请重新提问"，则启动模型反思
    if depth < max_depth:
        if "很抱歉无法回答" in ai_reply:
            print("[state]:", f"{step}正在反思并尝试重新给出回答......")
            ai_dialog_db.add_ai_hint(f"[Dialog] 多智能体反思中 ......")
            ai_reply = solve_multi_agent(
                ai_dialog_db, history, kb_id, message, sub_id, depth=depth + 1
            )
    print("[state]:", f"{step}思考完成")
    print(f"[info] 问题{message}的最终结果：{ai_reply}")
    return ai_reply


@require_http_methods(["POST"])
def build_kb(request):
    """'
    这个方法是论文循证
    输入为paper_id_list，重新构建一个知识库
    """
    data = json.loads(request.body)
    paper_id_list = data.get("paper_id_list")
    try:
        tmp_kb_id = build_abs_kb_by_paper_ids(paper_id_list, "tmp_kb")
    except Exception as e:
        print(e)
        return fail(msg="构建知识库失败")
    return ok({"kb_id": tmp_kb_id})


@authenticate_user
def change_record_papers(request, _: User):
    """
    本函数用于修改搜索记录的论文
    """
    data = json.loads(request.body)
    search_record_id = data.get("search_record_id")
    paper_id_list = data.get("paper_id_list")
    search_record = SearchRecord.objects.get(search_record_id=search_record_id)
    papers = []
    for paper_id in paper_id_list:
        paper = Paper.objects.get(paper_id=paper_id)
        papers.append(paper)
    search_record.related_papers.clear()
    for paper in papers:
        search_record.related_papers.add(paper)

    print("new paper", papers)

    ### 修改知识库
    try:
        kb_id = build_abs_kb_by_paper_ids(paper_id_list, search_record_id)
        insert_search_record_2_kb(search_record_id, kb_id)
    except Exception:
        return fail(msg="构建知识库失败")

    return JsonResponse({"msg": "修改成功"}, status=200)


@authenticate_user
@require_http_methods(["DELETE"])
def flush(request, _: User):
    """
    这是用来清空对话记录的函数
    :param request: 请求，类型为DEL
        内容包含：{
            search_record_id : string
        }
    :param _: 发起当前请求的用户对象
    """
    data = json.loads(request.body)
    sr = SearchRecord.objects.get(search_record_id=data.get("search_record_id"))
    if sr is None:
        return JsonResponse({"error": "搜索记录不存在"}, status=404)
    else:
        conversation_path = sr.conversation_path
        import os

        if os.path.exists(conversation_path):
            os.remove(conversation_path)
        sr.delete()
        return JsonResponse("清空成功", status=200)


def insert_search_record_2_kb(search_record_id, tmp_kb_id):
    search_record_id = str(search_record_id)
    os.makedirs(os.path.dirname(settings.USER_SEARCH_MAP_PATH), exist_ok=True)

    if not os.path.exists(settings.USER_SEARCH_MAP_PATH):
        with open(settings.USER_SEARCH_MAP_PATH, "w") as f:
            # noinspection PyTypeChecker
            json.dump({}, f)  # 初始化空字典
    with open(settings.USER_SEARCH_MAP_PATH, "r", encoding="utf-8") as f:
        s_2_kb_map = json.load(f)
    print(s_2_kb_map)
    s_2_kb_map = {str(k): v for k, v in s_2_kb_map.items()}
    if search_record_id in s_2_kb_map.keys():
        if delete_tmp_kb(s_2_kb_map[search_record_id]):
            print("删除TmpKb成功")
        else:
            print("删除TmpKb失败")

    s_2_kb_map[search_record_id] = tmp_kb_id
    with open(settings.USER_SEARCH_MAP_PATH, "w") as f:
        # noinspection PyTypeChecker
        json.dump(s_2_kb_map, f, indent=4)


def get_tmp_kb_id(search_record_id):
    with open(settings.USER_SEARCH_MAP_PATH, "r") as f:
        s_2_kb_map = json.load(f)
    # print(f_2_kb_map)
    if str(search_record_id) in s_2_kb_map:
        return s_2_kb_map[str(search_record_id)]
    else:
        return None


def do_dialogue_search(
    search_content, chat_chat_url, headers, ai_dialog_db: AIDialogStorage
):
    # filtered_paper = search_paper_with_query(search_content, limit=200) 从这里改为使用服务器的查询接口
    ai_dialog_db.add_ai_hint("[Query] 正在检索文献 ......")
    vector_filtered_papers = get_filtered_paper(
        search_content, k=100, threshold=0.3
    )  # 这是新版的调用服务器模型的接口

    print("vector_filtered_papers:", vector_filtered_papers)

    # 进行二次关键词检索
    # 首先获取关键词, 同样使用chatglm6b的普通对话
    prompt = (
        "你是一个文献调研助手，帮我从这些关键词中提取出来十个关键词，用英文回答关键词:"
    )
    payload = json.dumps(
        {
            "messages": [{"role": "user", "content": prompt + search_content}],
            "model": settings.CHATCHAT_CHAT_MODEL,
            "prompt_name": "keyword",
            "temperature": 0.3,
        }
    )
    print("payload:", payload)
    print("chat_chat_url:", chat_chat_url)
    print("headers:", headers)
    ai_dialog_db.add_ai_hint("[Query] 正在进行关键词拆解 ......")
    response = requests.request(
        "POST", chat_chat_url, data=payload, headers=headers, stream=False
    )
    print(response)
    keyword = ""

    decoded_line = response.content.decode("utf-8")
    # print(decoded_line)
    print("chatchat do dialogue_search finish:", decoded_line)
    if decoded_line:
        data = json.loads(decoded_line)
        keyword = data["choices"][0]["message"]["content"]

    keywords = [
        k.strip() for k in keyword.split("\n") if k.strip()
    ]  # 按换行分割并去除序号和空格
    keywords = [
        k[k.find(".") + 1 :].strip() if "." in k else k for k in keywords
    ]  # 去除序号
    not_keywords = ["paper", "research", "article"]
    for not_keyword in not_keywords:
        keywords = [keyword for keyword in keywords if not_keyword not in keyword]

    print("keyword:", keyword)

    ai_dialog_db.add_ai_hint("[Query] 正在进行关键词检索 ......")
    keywords[0] = search_content
    keyword_filtered_papers = search_papers_by_keywords(keywords=keywords)

    if len(keyword_filtered_papers) > 20:
        keyword_filtered_papers = keyword_filtered_papers[:20]

    s1 = set(vector_filtered_papers)
    s2 = set(keyword_filtered_papers)
    filtered_papers = list(s1.union(s2))
    return filtered_papers


def search_my_model(query_string):
    # 将字符串按空格切割
    search_terms = query_string.split()

    # 构造一个 Q 对象，用于模糊查询
    query = Q()
    for term in search_terms:
        query |= Q(x__icontains=term)

    # 执行查询，获取并集结果
    results = Paper.objects.filter(query)

    return results


def do_string_search(search_content):
    # 使用百度翻译API将中文搜索内容翻译成英文
    translator = Translator(to_lang="en", from_lang="zh")
    try:
        # 尝试翻译,如果是中文则翻译成英文,如果是英文则保持不变
        translated_content = translator.translate(search_content)
        search_content = translated_content
    except:
        # 如果翻译失败则使用原始内容
        pass

    pattern = r"[,\s!?.]+"
    search_terms = re.split(pattern, search_content)
    search_terms = [token for token in search_terms if token]

    query = Q()
    for term in search_terms:
        query |= Q(title__icontains=term)
    # 执行查询，获取字符串检索的并集结果
    results = Paper.objects.filter(query)
    print("do_string_search:", results)
    # 计算编辑距离并排序
    results_with_distance = []
    for result in results:
        distance = Levenshtein.distance(result.title, search_content)
        results_with_distance.append((distance, result))

    # 按编辑距离排序
    results_with_distance.sort(key=lambda x: x[0])

    # 返回排序后的结果
    sorted_results = [result for distance, result in results_with_distance]
    return sorted_results[:10]  # 返回前10篇相似度最高的文章


@authenticate_user
@require_http_methods(["POST"])
def vector_query(*_):
    return fail(err="该功能已下线，请使用新的搜索功能")
