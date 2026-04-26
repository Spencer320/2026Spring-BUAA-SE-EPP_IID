from typing import Dict, List

import requests
from django.conf import settings

API_KEY = settings.CENSOR_API_KEY
SECRET_KEY = settings.CENSOR_SECRET_KEY


def _get_access_token():
    """
    使用 AK，SK 生成鉴权签名（Access Token）

    Returns:
        str: access_token，用于后续API调用的鉴权
        None: 如果获取失败则返回None
    """
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": API_KEY,
        "client_secret": SECRET_KEY,
    }
    return str(requests.post(url, params=params).json().get("access_token"))


def text_censor(text) -> Dict[str, str | List[dict] | dict]:
    """
    使用百度文本审核API检查文本内容是否合规

    Args:
        text (str): 需要审核的文本内容

    Returns:
        dict: 审核结果，包含以下字段：
            - conclusion (str): 审核结论，可能的值：
                * "合规"：文本内容合规
                * "不合规"：文本内容不合规
                * "疑似"：文本内容疑似不合规
            - log_id (str): 请求的唯一标识符
            - phoneRisk (dict): 手机号风险信息，通常为空
            - data (list): 详细的审核结果列表，每个元素包含：
                * msg (str): 不合规的具体原因
                * conclusion (str): 该条目的审核结论
                * hits (list): 命中信息列表，包含：
                    - probability (float): 命中概率，0-1之间
                    - datasetName (str): 命中的规则库名称
                    - words (list): 命中的关键词列表
                    - modelHitPositions (list): 命中位置信息，格式为[起始位置, 结束位置, 概率]
                * subType (int): 子类型代码
                * conclusionType (int): 结论类型代码
                * type (int): 违规类型代码
            - isHitMd5 (bool): 是否命中MD5黑名单
            - conclusionType (int): 结论类型代码，可能的值：
                * 1: 合规
                * 2: 不合规
                * 3: 疑似
    """
    url = (
        "https://aip.baidubce.com/rest/2.0/solution/v1/text_censor/v2/user_defined?access_token="
        + _get_access_token()
    )

    payload = {"text": text}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    response = requests.request("POST", url, headers=headers, data=payload, timeout=15)
    print("Response from censor API Code:", response.status_code)
    return response.json()
