import os

from openai import OpenAI
from django.conf import settings

deepseek_key = settings.DEEPSEEK_API_KEY
deepseek_base = settings.DEEPSEEK_BASE_URL


def query_r1(msg: str, history=None, r1_model="deepseek-chat") -> tuple[str, str]:
    """
    :return: 输出内容，推理内容
    """
    messages = [{"role": "user", "content": msg}]
    if isinstance(history, list):
        messages = history + messages
    client = OpenAI(api_key=deepseek_key, base_url=deepseek_base)
    rsp = client.chat.completions.create(
        model=r1_model, messages=messages, temperature=0.1, stream=False
    )
    if r1_model == "deepseek-reasoner":
        return rsp.choices[0].message.content, rsp.choices[0].message.reasoning_content
    else:
        return rsp.choices[0].message.content, ""
