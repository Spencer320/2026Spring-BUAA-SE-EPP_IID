import json
from typing import Dict, Optional
import requests
import time
import os


class TranslationAPIError(Exception):
    pass


class SimplifyAITranslator:
    def __init__(self, api_key):
        self.base_url = "https://translate.simplifyai.cn/api/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    def create_translation_task(self, files, from_lang, to_lang, **kwargs):
        """
        创建翻译任务
        :param files: 需要翻译的文件路径
        :param from_lang: 源语言 (e.g. "English")
        :param to_lang: 目标语言 (e.g. "Simplified Chinese")
        :param kwargs: 其他可选参数 (glossary, model, etc.)
        :return: 任务ID
        """
        url = f"{self.base_url}/translations"

        try:
            files = {"file": files}
            data = {"fromLang": from_lang, "toLang": to_lang, **kwargs}
            response = requests.post(url, headers=self.headers, files=files, data=data)

        except FileNotFoundError:
            raise Exception("File not found")

        if response.status_code == 201:
            return response.json()["taskId"]
        else:
            raise TranslationAPIError(
                f"Failed to create task: {response.status_code} - {response.text}"
            )

    def get_task_status(self, task_id, client_task=False):
        """
        查询任务状态
        :param task_id: 任务ID
        :param client_task: 是否为自定义任务ID
        :return: 任务状态字典
        """
        url = f"{self.base_url}/translations/{task_id}"
        if client_task:
            url = f"{self.base_url}/translations?clientTaskId={task_id}"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            return response.json()
        else:
            raise TranslationAPIError(
                f"Failed to get task status: {response.status_code} - {response.text}"
            )

    @staticmethod
    def download_translated_file(url, save_path):
        """
        下载翻译后的文件
        :param url: 文件下载URL
        :param save_path: 本地保存路径
        """
        response = requests.get(url)
        if response.status_code == 200:
            print("get url")
            with open(save_path, "wb") as f:
                f.write(response.content)
        else:
            raise TranslationAPIError(
                f"Failed to download file: {response.status_code}"
            )

    def create_glossary(self, name: str, content: Dict[str, str]) -> Dict:
        """
        创建新术语表
        :param name: 术语表名称（必须唯一）
        :param content: 术语内容字典（如 {"AI": "人工智能"}）
        :return: 创建成功的术语表信息(id, name)
        """
        # 参数验证
        if not name or not isinstance(name, str):
            raise ValueError("术语表名称必须是非空字符串")
        if not content or not isinstance(content, dict):
            raise ValueError("术语内容必须是有效的字典")

        url = f"{self.base_url}/glossaries"
        data = {"name": name, "content": json.dumps(content)}

        response = requests.post(url, headers=self.headers, data=data)

        if response.status_code == 201:
            return response.json()
        elif response.status_code == 400:
            if "already used" in response.text:
                raise TranslationAPIError(f"术语表名称 '{name}' 已存在")
            raise TranslationAPIError(f"参数错误: {response.text}")
        else:
            raise TranslationAPIError(
                f"创建失败 [{response.status_code}]: {response.text}"
            )

    def get_glossary(self, glossary_id: str) -> dict:
        """
        获取单个术语表详情
        :param glossary_id: 术语表ID
        :return: 术语表详细信息
        """
        response = requests.get(
            f"{self.base_url}/glossaries/{glossary_id}", headers=self.headers
        )

        if response.status_code == 200:
            data = response.json()
            return {"id": data["id"], "name": data["name"], "content": data["content"]}
        elif response.status_code == 404:
            raise TranslationAPIError("术语表不存在或无权访问")
        else:
            raise TranslationAPIError(
                f"查询失败 [{response.status_code}]: {response.text}"
            )

    def update_glossary(
        self,
        glossary_id: str,
        new_name: Optional[str] = None,
        new_content: Optional[Dict[str, str]] = None,
    ) -> Dict:
        """
        更新术语表（可修改名称或内容）
        :param glossary_id: 要修改的术语表ID
        :param new_name: 新名称（可选）
        :param new_content: 新内容字典（可选）
        :return: 更新后的术语表信息
        """
        if not new_name and not new_content:
            raise ValueError("必须提供至少一个修改参数（new_name或new_content）")

        data = {}
        if new_name:
            if not isinstance(new_name, str):
                raise ValueError("术语表名称必须为字符串")
            data["name"] = new_name
        if new_content:
            if not isinstance(new_content, dict):
                raise ValueError("术语内容必须是字典")
            data["content"] = json.dumps(new_content)

        response = requests.put(
            f"{self.base_url}/glossaries/{glossary_id}", headers=self.headers, data=data
        )

        if response.status_code == 200:
            return self.get_glossary(glossary_id)
        elif response.status_code == 400:
            error_msg = response.json().get("message", "未知错误")
            if "already used" in error_msg:
                raise TranslationAPIError(f"术语表名称 '{new_name}' 已存在")
            raise TranslationAPIError(f"参数错误: {error_msg}")
        elif response.status_code == 404:
            raise TranslationAPIError("术语表不存在或无权修改")
        else:
            raise TranslationAPIError(
                f"更新失败 [{response.status_code}]: {response.text}"
            )

    def delete_glossary(self, glossary_id: str) -> bool:
        """
        删除术语表
        :param glossary_id: 要删除的术语表ID
        :return: 是否删除成功
        """
        response = requests.delete(
            f"{self.base_url}/glossaries/{glossary_id}", headers=self.headers
        )

        if response.status_code == 204:
            return True
        elif response.status_code == 404:
            raise Exception("术语表不存在或无权删除")
        else:
            raise Exception(f"删除失败 [{response.status_code}]: {response.text}")

    def translate_pdf(
        self, files, from_lang, to_lang, poll_interval=5, timeout=3600, **kwargs
    ):
        """
        完整翻译流程
        :param files: PDF文件路径
        :param from_lang: 源语言
        :param to_lang: 目标语言
        :param poll_interval: 状态查询间隔（秒）
        :param timeout: 超时时间（秒）
        :return: 译文文件路径url
        """
        try:
            # 判断客户是否指定任务ID
            is_client = "clientTaskId" in kwargs

            # 创建任务
            task_id = self.create_translation_task(
                files=files, from_lang=from_lang, to_lang=to_lang, **kwargs
            )

            print(f"Task created. Task ID: {task_id}")

            # 轮询任务状态
            start_time = time.time()
            while True:
                status_info = self.get_task_status(task_id, is_client)
                status = status_info["status"]
                progress = status_info.get("progress", 0)

                print(f"Status: {status}, Progress: {progress:.1f}%")

                if status == "Completed":
                    translated_url = status_info["translatedFileUrl"]
                    return translated_url

                if status in ("Cancelled", "Terminated", "NotSupported"):
                    raise Exception(f"Translation failed. Final status: {status}")

                if time.time() - start_time > timeout:
                    raise Exception("Translation timeout")

                time.sleep(poll_interval)

        except Exception as e:
            raise Exception(f"Translation failed: {str(e)}")


# 使用示例
if __name__ == "__main__":
    # 配置参数
    API_KEY = os.getenv("TRANS_API_KEY")  # 配置环境变量
    PDF_FILE = "test.pdf"  # 要翻译的PDF文件路径
    FROM_LANG = "English"  # 源语言
    TO_LANG = "Simplified Chinese"  # 目标语言
    CLIENT_TASK_ID = ""  # 客户指定任务ID

    # model: ["gpt-4.1-mini","gpt-4.1","gpt-4o-mini","gpt-4",
    # "gemini-pro","gemini-flash","qwen-turbo",
    # "deepseek-v3","deepseek-r1","manual"]

    file_name = PDF_FILE.split(".pdf")[0]
    save_path = f"{file_name}_zh.pdf"

    # 初始化翻译器
    translator = SimplifyAITranslator(API_KEY)

    try:
        # 执行翻译
        with open(PDF_FILE, "rb") as f:
            translated_url = translator.translate_pdf(
                files=f,
                from_lang=FROM_LANG,
                to_lang=TO_LANG,
                shouldTranslateImage=True,  # 翻译图片中的文字
                autoStart=1,  # 支付用于翻译的积分，预览可以设置为1
                # model="deepseek-v3",          # 翻译模型，高级模型gpt-4o收费更贵
                # clientTaskId=CLIENT_TASK_ID,  # 使用客户自定义任务ID
                # shouldTranslateFileName=True  # 翻译文件名
            )
        # 下载文件
        translator.download_translated_file(translated_url, save_path)
        print(f"Translation completed. File saved to: {save_path}")
    except Exception as e:
        print(f"Error occurred: {str(e)}")
