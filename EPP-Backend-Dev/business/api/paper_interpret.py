"""
本文件的功能是文献阅读助手，给定一篇文章进行阅读，根据问题的答案进行回答。
API格式如下：
api/peper_interpret/...
"""

import asyncio
import json
import os
import pathlib
import re
from urllib.parse import quote
import requests
from django.views.decorators.http import require_http_methods

from django.conf import settings
from business.models import UserDocument, FileReading, Paper, User, PaperVisitRecent
from business.utils.authenticate import authenticate_user
from business.utils.chat_glm import query_glm
from business.utils.chat_r1 import query_r1
from business.utils.chat_tavily import query_tavily
from business.utils.response import ok, fail

from business.utils.download_paper import download_paper

# 论文研读模块

"""
    创建文献研读对话：
        上传一个文件，开启一个研读对话，返回 tmp_kb_id
    
    对话记录方式为: [
        {"role": "user", "content": "我们来玩成语接龙，我先来，生龙活虎"},
        {"role": "assistant", "content": "虎头虎脑"},
    ]
"""


def create_content_disposition(filename):
    """构建适用于Content-Disposition的filename和filename*参数"""
    # URL 编码文件名
    safe_filename = quote(filename)
    # 构建Content-Disposition头部
    disposition = f'form-data; name="file"; filename="{filename}"; filename*=UTF-8\'\'{safe_filename}'
    return disposition


# 删除Tmp_kb的缓存，用于某tmp_kb_id再也不被使用时，避免内存爆炸
def delete_tmp_kb(tmp_kb_id):
    delete_tmp_kb_url = (
        f"{settings.REMOTE_MODEL_BASE_PATH}/knowledge_base/delete_temp_docs"
    )
    # headers = {
    #     'Content-Type': 'application/x-www-form-urlencoded'
    # }
    payload = {"knowledge_id": tmp_kb_id}
    response = requests.post(delete_tmp_kb_url, data=payload)  # data默认是form形式
    if response.status_code == 200:
        return True
    else:
        return False


# 建立file_reading和tmp_kb的映射
def insert_file_2_kb(file_reading_id, tmp_kb_id):
    if not os.path.exists(settings.USER_READ_MAP_PATH):
        with open(settings.USER_READ_MAP_PATH, "w") as f:
            json.dump({}, f)
    with open(settings.USER_READ_MAP_PATH, "r") as f:
        f_2_kb_map = json.load(f)
    if file_reading_id in f_2_kb_map:
        if delete_tmp_kb(f_2_kb_map[file_reading_id]):
            print("删除TmpKb成功")
        else:
            print("删除TmpKb失败")

    f_2_kb_map[file_reading_id] = tmp_kb_id
    with open(settings.USER_READ_MAP_PATH, "w") as f:
        # noinspection PyTypeChecker
        json.dump(f_2_kb_map, f, indent=4)


def get_tmp_kb_id(file_reading_id):
    with open(settings.USER_READ_MAP_PATH, "r") as f:
        f_2_kb_map = json.load(f)
    # print(f_2_kb_map)
    if str(file_reading_id) in f_2_kb_map:
        return f_2_kb_map[str(file_reading_id)]
    else:
        return None


def filter_history(history: list) -> list:
    return [h for h in history if h["role"] != "system"]


@authenticate_user
@require_http_methods(["POST"])
def create_paper_study(request, user: User):
    # 处理请求头
    request_data = json.loads(request.body)
    file_type = request_data.get("file_type")  # 1代表上传文献研读, 2代表已有文件研读
    additional_info = ""
    if file_type == 1:
        document_id = request_data.get("document_id")
        # 获取文件, 后续支持直接对8k篇论文进行检索
        document = UserDocument.objects.get(document_id=document_id)
        # 获取服务器本地的path
        local_path = document.local_path
        content_type = document.format
        title = document.title
        # 先查找数据库是否有对应的Filereading
        file_readings = FileReading.objects.filter(document_id=document_id)
        if file_readings.count() == 0:
            # 创建一段新的filereading对话, 并设置conversation对话路径，创建json文件
            file_reading = FileReading(
                user_id=user,
                document_id=document,
                title="上传论文研读",
                conversation_path=None,
            )
        elif file_readings.count() >= 1:
            file_reading = file_readings.first()
        else:
            return fail(msg="一个用户上传文件存在多个文献研读文件，逻辑有误")
    elif file_type == 2:
        paper_id = request_data.get("paper_id")
        paper = Paper.objects.get(paper_id=paper_id)
        title = paper.title
        additional_info = f"该论文于{paper.publication_date}发表在arXiv上，作者是{paper.authors}。论文的摘要是{paper.abstract}"
        content_type = ".pdf"
        local_path = get_paper_local_url(paper)
        if local_path is None:
            return fail(msg="论文无法下载，请联系管理员/换一篇文章研读")
        file_reading = FileReading(
            user_id=user, paper_id=paper, title="数据库论文研读", conversation_path=None
        )
        PaperVisitRecent.record(paper)
    else:
        return fail(msg="类型有误")

    file_reading.save()
    conversation_path = os.path.join(
        settings.USER_READ_CONSERVATION_PATH, str(file_reading.id) + ".json"
    )
    file_reading.conversation_path = conversation_path
    file_reading.save()
    # if os.path.exists(conversation_path):
    #     os.remove(conversation_path)

    # 此时不存在记录，创建新的
    forward = f"欢迎使用论文研读助手，这篇文章的题目是《{title}》。你可以向我提问有关这篇文章的问题。"
    if not os.path.exists(conversation_path):
        with open(conversation_path, "w") as f:
            # noinspection PyTypeChecker
            json.dump(
                {
                    "conversation": [
                        {
                            "role": "system",
                            "content": f"你是文献研读助手。用户研读的文献是《{title}》。{additional_info}",
                        },
                        {"role": "assistant", "content": forward},
                    ]
                },
                f,
                indent=4,
            )

    # 上传到远端服务器, 创建新的临时知识库
    upload_temp_docs_url = (
        f"{settings.REMOTE_MODEL_BASE_PATH}/knowledge_base/upload_temp_docs"
    )

    print(open(local_path, "rb"))
    files = [
        (
            "files",
            (
                title + content_type,
                open(local_path, "rb"),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
        )
    ]

    # headers = {
    #     'Content-Type': 'multipart/form-data'
    # }

    response = requests.request("POST", upload_temp_docs_url, files=files)
    # 关闭文件，防止内存泄露
    for k, v in files:
        v[1].close()

    if response.status_code == 200:
        tmp_kb_id = response.json()["data"]["id"]
        insert_file_2_kb(str(file_reading.id), tmp_kb_id)
        with open(conversation_path, "r") as f:
            history = json.load(f)
        print("history:", history)
        history = {"conversation": filter_history(history["conversation"])}
        return ok(
            {"file_reading_id": file_reading.id, "conversation_history": history},
            msg="开启文献研读对话成功",
        )
    else:
        print(f"{upload_temp_docs_url} Returned: {response.status_code}")
        return fail(msg="连接模型服务器失败")


@authenticate_user
@require_http_methods(["POST"])
def restore_paper_study(request, _: User):
    """恢复文献研读对话：
    传入文献研读对话id即可
    """
    # 获取filereading与文件路径，重新上传给服务器开启对话
    request_data = json.loads(request.body)
    file_reading_id = request_data.get("file_reading_id")
    fr = FileReading.objects.get(id=file_reading_id)
    additional_info = ""
    if not fr.document_id:
        paper = Paper.objects.get(paper_id=fr.paper_id.get_paper_id())
        additional_info = f"该论文于{paper.publication_date}发表在arXiv上，作者是{paper.authors}。论文的摘要是{paper.abstract}"
        local_path = get_paper_local_url(paper)
        title = paper.title
        content_type = ".pdf"
    else:
        document = UserDocument.objects.get(
            document_id=fr.document_id.get_document_id()
        )
        local_path = document.local_path
        title = document.title
        content_type = document.format

    if local_path is None or title is None:
        return fail(msg="服务器内无本地文件, 请检查")

    # 上传到远端服务器, 创建新的临时知识库
    upload_temp_docs_url = (
        f"{settings.REMOTE_MODEL_BASE_PATH}/knowledge_base/upload_temp_docs"
    )
    files = [
        (
            "files",
            (
                title + content_type,
                open(local_path, "rb"),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
        )
    ]

    # headers = {
    #     'Content-Type': 'multipart/form-data'
    # }

    response = requests.request("POST", upload_temp_docs_url, files=files)
    # 关闭文件，防止内存泄露
    for k, v in files:
        v[1].close()

    # 返回结果, 需要将历史对话一起返回
    if response.status_code == 200:
        tmp_kb_id = response.json()["data"]["id"]
        insert_file_2_kb(str(file_reading_id), tmp_kb_id)
        # 若删除过历史对话, 则再创建一个文件
        if not os.path.exists(fr.conversation_path):
            forward = f"欢迎使用论文研读助手，这篇文章的题目是《{title}》。你可以向我提问有关这篇文章的问题。"
            with open(fr.conversation_path, "w") as f:
                # noinspection PyTypeChecker
                json.dump(
                    {
                        "conversation": [
                            {
                                "role": "system",
                                "content": f"你是文献研读助手。用户研读的文献是《{title}》。{additional_info}",
                            },
                            {"role": "assistant", "content": forward},
                        ]
                    },
                    f,
                    indent=4,
                )

        # 读取历史对话记录
        with open(fr.conversation_path, "r") as f:
            conversation_history = json.load(
                f
            )  # 使用 json.load() 方法将 JSON 数据转换为字典
        conversation_history = {
            "conversation": filter_history(conversation_history["conversation"])
        }
        return ok(
            {
                "file_reading_id": file_reading_id,
                "conversation_history": conversation_history,
            },
            msg="恢复文献研读对话成功",
        )
    else:
        return fail(msg="连接模型服务器失败")


@require_http_methods(["POST"])
async def async_test(_):
    """
    异步测试
    """
    print("Task started.")
    await asyncio.sleep(5)  # 模拟异步操作，例如等待 I/O
    print("Task completed.")


def get_paper_local_url(paper):
    """
    获取本地url
    """
    local_path = paper.local_path
    if not local_path or not pathlib.Path(local_path).exists():
        original_url = paper.original_url
        # 将路径中的abs修改为pdf
        original_url = original_url.replace("abs", "pdf")
        # 访问url，下载文献到服务器
        filename = str(paper.paper_id)
        local_path = download_paper(original_url, filename)
        paper.local_path = local_path
        paper.save()
    return local_path


@authenticate_user
def get_paper_url(request, _: User):
    """
    获取文献本地url, 无则下载
    """
    paper_id = request.GET.get("paper_id")
    paper = Paper.objects.get(paper_id=paper_id)
    paper_local_url = get_paper_local_url(paper)
    if paper_local_url is None:
        return fail(msg="文献下载失败，请检查网络或联系管理员")
    return ok({"local_url": "/" + paper_local_url}, msg="success")


def do_file_chat(conversation_history, query, tmp_kb_id):
    # 将历史记录与本次对话发送给服务器, 获取对话结果
    file_chat_url = f"{settings.REMOTE_MODEL_BASE_PATH}/chat/kb_chat"
    headers = {"Content-Type": "application/json"}

    step = "文献研读助手"
    print("[state]:", f"{step}正在思考......")

    judge_prompt = f"""
    你是一个文献研读助手，你的数据库只有一篇论文，用户向你提问了一个问题，你需要判断该问题是否只跟数据库中的那一篇论文有关。
    如果是请直接回答"yes"，表明只需要当前论文的结果就可以解答；如果不是请直接回答"no"，表明需要额外的文献支持。如果提问内容与论文研读无关则回答“yes”。
    例如：
    1. Q：这篇文章主要内容是什么。A：yes
    2. Q：文章中使用了什么技术。A：yes
    3. Q：什么是强化学习。A：no
    4. Q：当前领域的先进技术有哪些。A：no
    现在对于问题：
    {query}
    给出你的判断结果（yes / no）:
    """
    judge_answer = query_glm(judge_prompt)
    print("judge:", judge_answer)
    if len(conversation_history) != 0:
        history = conversation_history[-10:]
        if conversation_history[0] not in history:
            history = [conversation_history[0]] + history
        payload = json.dumps(
            {
                "query": query,
                "mode": "temp_kb",
                "kb_name": tmp_kb_id,
                "history": list(history),  # 传1 + 10条历史记录
                "score_threshold": 0.8,
                # "prompt_name": "text",  # 使用历史记录对话模式
            }
        )

    else:
        payload = json.dumps(
            {
                "query": query,
                "mode": "temp_kb",
                "kb_name": tmp_kb_id,
                "score_threshold": 0.8,
                # "prompt_name": "default",  # 使用普通对话模式
            }
        )
        # print(payload)

    def _get_ai_reply(payload):
        response = requests.request(
            "POST", file_chat_url, data=payload, headers=headers, stream=False
        )
        ai_reply = ""
        origin_docs = []
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode("utf-8")
                if decoded_line.startswith("data"):
                    data = decoded_line.replace("data: ", "")
                    data = json.loads(data)
                    ai_reply += data["choices"][0]["delta"]["content"]
                    for doc in data.get("docs", []):
                        doc = (
                            str(doc)
                            .replace("\n", " ")
                            .replace("<span style='color:red'>", "")
                            .replace("</span>", "")
                        )
                        doc = re.sub(r"\(http.+\.pdf\)", "", doc)
                        doc = doc + "......\n"
                        origin_docs.append(doc)
        return ai_reply, origin_docs

    def _get_tavily_reply(query):
        title = conversation_history[0]["content"].split("《")[1].split("》")[0]
        tavliy_prompt = f"""
        你是一个文献研读助手，我正在阅读一篇名为《{title}》的论文。
        请根据这篇论文的标题和我的问题"{query}"，用自然语言回答该问题，保留必要的参考文献。
        """
        ai_reply = query_tavily(tavliy_prompt)

        collect_prompt = f"""你是一个文献调研助手，用户提问了这样一个问题："{query}"。
        你的搜索引擎伙伴搜索到了以下回答{ai_reply}。
        请你根据搜索到的资料，直接自然地回答原问题，回答中要提供给用户必要的证据（网页链接、论文名称等）。
        """

        ai_reply = query_glm(collect_prompt)
        return ai_reply

    # task = asyncio.create_task(_get_ai_reply())  # 创建任务
    if "yes" in judge_answer:
        ai_reply, origin_docs = _get_ai_reply(payload)
    else:
        ai_reply = _get_tavily_reply(query)
        origin_docs = []

    print("[state]:", f"{step}思考完成")
    print("origin answer:", ai_reply)

    # 给出用户仍可能存在的问题
    def _get_prob_paper_study_question(question, origin_answer):
        prompt = f"""
        用户提出了一个问题，你有另一个大模型伙伴已经回答了这个问题，请你根据原问题和回答推断用户接下来可能会提问哪些相关问题，给出2-4个可能的问题。请用数字分点回答。
        要求：
        1. 问题需与原始问题逻辑相关且自然延伸
        2. 直接按数字序号排列，并且提问概率越高序号越靠前，不要额外解释
        3. 每个问题占一行
        例如：
        问题："什么是Vision Transformer?"
        伙伴回答："Vision Transformer（ViT）是一种基于Transformer架构的神经网络模型，专门用于处理计算机视觉任务‌。与传统计算机视觉模型如卷积神经网络（CNN）相比，ViT通过引入Transformer的注意力机制来解决长距离依赖建模的问题，并在一些视觉任务上取得了优秀的结果‌。"
        你的回答：
            1. Vision Transformer的应用有哪些？
            2. Vision Transformer比传统CNN的优势在哪？
            3. Vision Transformer是谁提出的？
        现在给出原问题："{question}"
        伙伴回答："{origin_answer}"
        下面给出你的回答：
        """

        # empty模板不含任何知识库信息
        # payload = json.dumps(
        #     {
        #         "query": prompt,
        #         "mode": "temp_kb",
        #         "kb_name": tmp_kb_id,
        #         "history": conversation_history[-4:],
        #         # "prompt_name": "question",  # 使用问题模式
        #         "max_tokens": 50,
        #         "temperature": 0.4,
        #     }
        # )
        question_reply, _ = query_r1(prompt)
        print("more question:", question_reply)
        cleaned = re.sub(r"\d+[\.\)\-]\s*", "", question_reply)
        # 分割、清理、过滤空值
        question_reply = [
            q.strip()
            for q in cleaned.split("\n")
            if q.strip() and len(q.strip()) > 2  # 过滤过短内容
        ]
        question_reply.append("告诉我更多")
        return question_reply

    step = "推理"
    print("[state]:", f"正在{step}用户感兴趣的问题......")
    question_reply = _get_prob_paper_study_question(query, ai_reply)
    print("[state]:", f"{step}用户兴趣完成")
    return ai_reply, origin_docs, question_reply


def add_conversation_history(conversation_history, query, ai_reply, conversation_path):
    # 添加历史记录并保存
    conversation_history.extend(
        [
            {"role": "user", "content": query},
            {
                "role": "assistant",
                "content": ai_reply if ai_reply != "" else "此问题由于某原因无回答",
            },
        ]
    )

    with open(conversation_path, "w") as f:
        json.dump({"conversation": conversation_history}, f, indent=4)


@authenticate_user
@require_http_methods(["POST"])
def do_paper_study(request, _: User):
    """
    论文研读 Key! 此时AI回复为非流式输出, 可能浪费时间, alpha版本先这样
    """
    request_data = json.loads(request.body)
    query = request_data.get("query")  # 本次询问对话
    file_reading_id = request_data.get("file_reading_id")
    fr = FileReading.objects.get(id=file_reading_id)
    tmp_kb_id = get_tmp_kb_id(file_reading_id=file_reading_id)  # 临时知识库id
    if tmp_kb_id is None:
        return fail(msg="请先创建研读会话")
    # 加载历史记录
    with open(fr.conversation_path, "r") as f:
        conversation_history = json.load(f)

    print(tmp_kb_id)
    conversation_history = list(conversation_history.get("conversation"))  # List[Dict]
    # print(conversation_history, query, tmp_kb_id)
    ai_reply, origin_docs, question_reply = do_file_chat(
        conversation_history, query, tmp_kb_id
    )
    add_conversation_history(
        conversation_history, query, ai_reply, fr.conversation_path
    )
    return ok(
        {"ai_reply": ai_reply, "docs": origin_docs, "prob_question": question_reply},
        msg="成功",
    )


@authenticate_user
@require_http_methods(["POST"])
def re_do_paper_study(request, user: User):
    """
    论文研读：重新生成回复
    """
    request_data = json.loads(request.body)
    file_reading_id = request_data.get("file_reading_id")
    tmp_kb_id = get_tmp_kb_id(file_reading_id=file_reading_id)
    if tmp_kb_id is None:
        return fail(msg="请先创建研读会话")

    fr = FileReading.objects.get(id=file_reading_id)
    conversation_path = fr.conversation_path
    with open(fr.conversation_path, "r") as f:
        conversation_history = json.load(f)

    conversation_history = list(conversation_history.get("conversation"))
    if len(conversation_history) < 2:
        return fail(msg="无法找到您的上一条对话")
    # 获取最后一次的询问, 并去除最后一次的对话记录
    query = conversation_history[-2].get("content")
    conversation_history = conversation_history[:-2]

    # 同 do_paper_study
    ai_reply, origin_docs, question_reply = do_file_chat(
        conversation_history, query, tmp_kb_id
    )
    add_conversation_history(conversation_history, query, ai_reply, conversation_path)
    return ok(
        {"ai_reply": ai_reply, "docs": origin_docs, "prob_question": question_reply},
        msg="成功",
    )


# @require_http_methods(["POST"])
# def paper_interpret(request):
#     # mark:已被放弃
#     '''
#     本文件唯一的接口，类型为POST
#     根据用户的问题，返回一个回答
#     思路如下：
#         1. 根据session获得用户的username, request中包含local_path和question
#         2. 根据paper_id得到向量库中各段落的向量，根据question得到问题的向量，选择最相似的段落
#         3. 将段落输入到ChatGLM2-6B中，得到回答，进行总结，给出一个本文中的回答
#         4. 查找与其相似度最高的几篇文章的段落，相似度最高的5个段落，对每段给出一个简单的总结。
#         5. 将几个总结和回答拼接返回
#         6. 把聊天记录保存到数据库中，见backend/business/models/file_reading.py
#     return : {
#         content: str
#     }
#     '''
#     if request.method == 'POST':
#         data = json.loads(request.body)
#         local_path = data['local_path']
#         question = data['question']
#         username = request.session.get('username')
#         user = User.objects.get(username=username)
#         file = FileReading.objects.get(user_id=user, file_local_path=local_path)
#         conversation = []
#         conversation_path = ''
#         if file is None:
#             # 新建一个研读记录
#             t = get_pdf_title(local_path)
#             file = FileReading(user_id=user.user_id, file_local_path=local_path, title=t, conversation_path=None)
#             file.conversation_path = f'{USER_READ_CONSERVATION_PATH}/{file.user_id.id}_{file.title}.txt'
#             conversation_path = file.conversation_path
#             file.save()
#         else:
#             conversation_path = file.conversation_path
#             with open(conversation_path, 'r') as f:
#                 conversation = json.load(f)
#         conversation.append({'role': 'user', 'content': question})
#         # 从数据库中找到最相似的段落
#
#             # print(f"Received data (Client ID {client_id}): {data}")
#         elif decoded_line.startswith('event'):
#             event_type = decoded_line.replace('event: ', '')
#             # print(f"Event type: {event_type}")
#     finally:
#         response.close()
#     # print(response)  # 目前不清楚是何种返回 TODO:
#     return success({"ai_reply": ai_reply, "docs": origin_docs}, msg="成功")


@authenticate_user
@require_http_methods(["POST"])
def clear_conversation(request, user: User):
    request_data = json.loads(request.body)
    file_reading_id = request_data.get("file_reading_id")
    fr = FileReading.objects.get(id=file_reading_id)
    with open(fr.conversation_path, "r") as f:
        # noinspection PyTypeChecker
        conversation_history = json.load(f)
        conversation_history = list(conversation_history.get("conversation"))[0]
        with open(fr.conversation_path, "w") as f:
            json.dump({"conversation": [conversation_history]}, f, indent=4)
    return ok(msg="清除对话历史成功")
