import json

import openai
from django.conf import settings

from requests import Session
from requests.exceptions import RequestException, ChunkedEncodingError
from requests.adapters import HTTPAdapter

from urllib3.util.retry import Retry

from business.utils.futures import deprecated


def _payload_2_openai(original_payload: dict) -> dict:
    """
    使用 OpenAI 的 API 进行查询
    """

    messages = []
    if original_payload.get("history"):
        for item in original_payload["history"]:
            messages.append(item)
    messages.append({"role": "user", "content": original_payload["query"]})
    result = {
        "messages": messages,
        "model": settings.CHATCHAT_CHAT_MODEL,
    }
    if original_payload.get("temperature"):
        result["temperature"] = original_payload["temperature"]
    if original_payload.get("max_tokens"):
        result["max_tokens"] = original_payload["max_tokens"]
    if original_payload.get("top_k"):
        result["top_p"] = original_payload["top_k"]
    return result


@deprecated("Use query_glm instead")
def query_glm_openai(msg: str, history=None) -> str:
    """
    对 chatGLM3-6B 发出一次单纯的询问
    """
    openai.api_base = f"{settings.REMOTE_CHATCHAT_GLM3_OPENAI_PATH}/v1"
    openai.api_key = "none"
    if history is None:
        history = [{"role": "user", "content": msg}]
    else:
        history.extend([{"role": "user", "content": msg}])
    response = openai.ChatCompletion.create(
        model="chatglm3-6b", messages=history, stream=False
    )
    return response.choices[0].message.content


def query_glm(msg: str, history=None) -> str:
    """
    对chatGLM3-6B发出一次单纯的询问
    """
    chat_chat_url = f"{settings.REMOTE_MODEL_BASE_PATH}/chat/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = json.dumps(
        _payload_2_openai({"query": msg, "prompt_name": "default", "temperature": 0.3})
    )
    session = Session()
    retry = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    try:
        response = session.post(
            chat_chat_url, data=payload, headers=headers, stream=False
        )
        response.raise_for_status()
        # 确保正确处理分块响应
        decoded_line = next(response.iter_lines()).decode("utf-8")
        if decoded_line.startswith("data"):
            data = json.loads(decoded_line.replace("data: ", ""))
        else:
            data = decoded_line
        return json.loads(data)["choices"][0]["message"]["content"]
    except ChunkedEncodingError as e:
        print(f"ChunkedEncodingError: {e}")
        return "错误: 响应提前结束"
    except RequestException as e:
        print(f"RequestException: {e}")
        return f"错误: {e}"
