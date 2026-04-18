from tavily import TavilyClient
import json
from typing import Optional, List, Dict, Any

from django.conf import settings
from requests import Session
from requests.exceptions import RequestException, ChunkedEncodingError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
tavily_key = settings.TAVILY_API_KEY

# 初始化 Tavily 客户端，只有1000次免费
client = TavilyClient(tavily_key)


def _payload_2_tavily(original_payload: dict) -> dict:
    """
    将原始payload转换为Tavily API所需的格式
    """
    result = {
        "query": original_payload["query"],
        "search_depth": "advanced",  # 可选: basic, advanced
        "include_answer": True,
        "include_raw_content": True,
        "max_results": original_payload.get("max_results", 5),
    }

    if original_payload.get("include_domains"):
        result["include_domains"] = original_payload["include_domains"]
    if original_payload.get("exclude_domains"):
        result["exclude_domains"] = original_payload["exclude_domains"]

    return result


def query_tavily(
    query: str,
    max_results: int = 5,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    time_range: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用Tavily API进行搜索查询

    Args:
        query: 搜索查询字符串
        max_results: 最大返回结果数
        include_domains: 包含的域名列表
        exclude_domains: 排除的域名列表
        time_range: 时间范围，可选值：
            - "day": 过去24小时
            - "week": 过去一周
            - "month": 过去一个月
            - "year": 过去一年
            - None: 不限时间

    Returns:
        Dict包含搜索结果和相关信息
    """
    print(f"Querying Tavily with: {query}")

    try:
        # 使用 Tavily 客户端进行搜索
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            time_range=time_range,
        )

        print(f"Tavily response: {json.dumps(response, indent=4, ensure_ascii=False)}")
        return response

    except Exception as e:
        print(f"Error in Tavily search: {e}")
        return {"error": str(e)}


# 示例使用
if __name__ == "__main__":
    # 基本查询
    result = query_tavily("What is the capital of France?")
    print(result)

    # 带域名的查询
    result = query_tavily(
        "Python programming",
        max_results=3,
        include_domains=["python.org", "docs.python.org"],
        exclude_domains=["wikipedia.org"],
        time_range="month",  # 搜索过去一个月的内容
    )
    print(result)
