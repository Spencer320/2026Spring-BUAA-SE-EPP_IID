from typing import List

from django.db import models

from business.models import SummaryReport, SearchRecord, Paper


class AIDialogStorage(models.Model):
    """
    用于存储 AI 对话的模型
    """

    user_id = models.CharField(max_length=255)
    conversation = models.JSONField(default=dict)  # 存储对话内容
    created_at = models.DateTimeField(auto_now_add=True)  # 创建时间
    updated_at = models.DateTimeField(auto_now=True)  # 更新时间

    class Meta:
        abstract = True

    def is_last_ai_response(self):
        """
        判断最后一次对话是否是 AI 的回复
        :return: True 如果最后一次对话是 AI 的回复，否则 False
        """
        if not self.conversation or not self.conversation.get("conversition"):
            return False
        last_message = self.conversation["conversition"][-1]
        return last_message.get("role") == "assistant" if last_message else False

    def is_last_ai_hint(self):
        """
        判断最后一次对话是否是 AI 的提示
        :return: True 如果最后一次对话是 AI 的提示，否则 False
        """
        if not self.conversation or not self.conversation.get("conversition"):
            return False
        last_message = self.conversation["conversition"][-1]
        return last_message.get("role") == "hint" if last_message else False

    def is_last_user_response(self):
        """
        判断最后一次对话是否是用户的回复
        :return: True 如果最后一次对话是用户的回复，否则 False
        """
        if not self.conversation or not self.conversation.get("conversition"):
            return False
        last_message = self.conversation["conversition"][-1]
        return last_message.get("role") == "user" if last_message else False

    def add_ai_message(self, message):
        """
        添加 AI 消息到对话中
        :param message: AI 消息内容
        """
        if not self.conversation.get("conversition"):
            self.conversation["conversition"] = []
        self.conversation["conversition"].append(
            {"role": "assistant", "content": message}
        )
        self.save()

    def add_ai_hint(self, hint):
        """
        添加 AI 提示到对话中
        :param hint: AI 提示内容
        """
        if not self.conversation.get("conversition"):
            self.conversation["conversition"] = []
        self.conversation["conversition"].append({"role": "hint", "content": hint})
        print("Store AI Hint:", hint)
        self.save()

    def add_user_message(self, message):
        """
        添加用户消息到对话中
        :param message: 用户消息内容
        """
        if not self.conversation.get("conversition"):
            self.conversation["conversition"] = []
        self.conversation["conversition"].append({"role": "user", "content": message})
        self.save()

    def get_last_message(self):
        """
        获取最后一条消息
        :return: 最后一条消息内容
        """
        if not self.conversation or not self.conversation.get("conversition"):
            return None
        last_message = self.conversation["conversition"][-1]
        return last_message.get("content") if last_message else None


class SummaryDialogStorage(AIDialogStorage):
    """
    用于存储摘要对话的模型
    """

    report = models.OneToOneField(SummaryReport, on_delete=models.CASCADE)
    steps = models.IntegerField(default=0)  # 步骤数
    paper_info = models.JSONField(default=list)  # 论文信息
    tmp_kb_id = models.CharField(max_length=255, null=True, blank=True)  # 临时知识库 ID


class VectorSearchStorage(AIDialogStorage):
    search_record = models.OneToOneField(SearchRecord, on_delete=models.CASCADE)

    def terminate(self, papers: List[Paper], ai_reply: str):
        print("[Storage] Terminate!")
        if not self.conversation.get("conversition"):
            self.conversation["conversition"] = []
        self.conversation["conversition"].append(
            {
                "role": "assistant",
                "content": {
                    "papers": [str(paper.paper_id) for paper in papers],
                    "reply": ai_reply,
                },
            }
        )
        self.save()

    def has_terminate(self) -> bool:
        if not self.conversation or not self.conversation.get("conversition"):
            return False
        last_message = self.conversation["conversition"][-1]
        return last_message.get("role") == "assistant"

    def get_terminate(self):
        if not self.conversation or not self.conversation.get("conversition"):
            return None
        last_message = self.conversation["conversition"][-1]
        if last_message.get("role") == "assistant":
            return last_message.get("content")
        return None


class DialogSearchStorage(AIDialogStorage):
    search_record = models.OneToOneField(SearchRecord, on_delete=models.CASCADE)

    def new_ask(self, question: str):
        if not self.conversation.get("conversition"):
            self.conversation["conversition"] = []
        self.conversation["conversition"].append({"role": "user", "content": question})
        self.save()

    def has_result(self) -> bool:
        if not self.conversation or not self.conversation.get("conversition"):
            return False
        last_message = self.conversation["conversition"][-1]
        return last_message.get("role") == "assistant"

    def get_hint(self):
        if not self.conversation or not self.conversation.get("conversition"):
            return None
        last_message = self.conversation["conversition"][-1]
        if last_message.get("role") == "hint":
            return last_message.get("content")
        return "AI 祈祷中 。。。"

    def terminate(self, papers: List[Paper], dialog_type: str, content: str):
        print("[Storage] Terminate!")
        if not self.conversation.get("conversition"):
            self.conversation["conversition"] = []
        data = {
            "papers": [str(paper.paper_id) for paper in papers],
            "dialog_type": dialog_type,
            "content": content,
        }
        self.conversation["conversition"].append({"role": "assistant", "content": data})
        self.save()
