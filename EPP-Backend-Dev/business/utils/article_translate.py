import html
import re
import textwrap
import uuid
from pathlib import Path
from typing import Tuple

import fitz
from django.conf import settings

from business.models import Glossary, User
from business.models.paper_translation import query_one_translation, TranslationStatus
from business.utils.chat_glm import query_glm


TRANSLATION_DIR = Path(settings.MEDIA_ROOT) / "translations"
TRANSLATION_URL = settings.MEDIA_URL.rstrip("/") + "/translations/"
MAX_TRANSLATE_CHARS = 12000
CHUNK_CHARS = 1800


def _extract_pdf_text(raw_file: Path) -> str:
    if not raw_file.exists():
        raise FileNotFoundError(f"PDF file not found: {raw_file}")

    parts = []
    with fitz.open(raw_file) as doc:
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                parts.append(f"[Page {page_index}]\n{text}")
    return "\n\n".join(parts)


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_text(text: str) -> list[str]:
    text = text[:MAX_TRANSLATE_CHARS]
    chunks = []
    current = []
    current_len = 0
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and current_len + len(paragraph) > CHUNK_CHARS:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        if len(paragraph) > CHUNK_CHARS:
            chunks.extend(textwrap.wrap(paragraph, CHUNK_CHARS))
            continue
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _glossary_prompt(glossary: Glossary | None) -> str:
    if glossary is None:
        return ""
    terms = [f"- {term.term}: {term.translation}" for term in glossary.terms.all()]
    if not terms:
        return ""
    return "请尽量遵循以下术语表：\n" + "\n".join(terms)


def _translate_chunk(chunk: str, glossary: Glossary | None, index: int, total: int) -> str:
    prompt = f"""
你是科研论文翻译助手。请把下面英文论文片段翻译成中文。
要求：
1. 保留论文中的技术术语、公式、引用编号和专有名词。
2. 不要扩写，不要总结，只翻译原文含义。
3. 如果片段中有明显 OCR 或换行噪声，请自然整理为通顺中文。
4. 这是第 {index}/{total} 个片段。

{_glossary_prompt(glossary)}

待翻译片段：
{chunk}
"""
    result = query_glm(prompt.strip())
    if not result or str(result).startswith("错误:"):
        return f"> 该片段翻译失败：{result or '模型无返回'}\n\n原文：\n\n{chunk}"
    return result.strip()


def do_article_translate(glossary: Glossary | None, raw_file: Path) -> dict | None:
    """
    Translate the article with the local LangChain-Chatchat model and save Markdown.

    The result is a readable Markdown translation, not a layout-preserving PDF.
    """
    try:
        raw_text = _clean_text(_extract_pdf_text(raw_file))
    except Exception as exc:
        print("Error extracting PDF text for translation:", repr(exc))
        return None

    if not raw_text:
        return None

    task_id = f"local-{uuid.uuid4()}"
    chunks = _split_text(raw_text)
    if not chunks:
        return None

    translated_chunks = []
    for index, chunk in enumerate(chunks, start=1):
        translated_chunks.append(_translate_chunk(chunk, glossary, index, len(chunks)))

    TRANSLATION_DIR.mkdir(parents=True, exist_ok=True)
    result_name = f"{task_id}.html"
    result_path = TRANSLATION_DIR / result_name
    truncated_notice = ""
    if len(raw_text) > MAX_TRANSLATE_CHARS:
        truncated_notice = (
            "\n\n> 免费模式说明：为避免小模型上下文过长，本次仅翻译了文档前 "
            f"{MAX_TRANSLATE_CHARS} 个字符。\n"
        )
    translated_markdown = (
        "# 文献翻译（免费文本模式）\n\n"
        "> 本结果由本地 LangChain-Chatchat 小模型生成，不保留 PDF 原排版。\n"
        f"{truncated_notice}\n\n"
        + "\n\n---\n\n".join(translated_chunks)
    )
    result_path.write_text(
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>文献翻译（免费文本模式）</title>\n"
        "  <style>\n"
        "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "line-height: 1.7; margin: 32px auto; max-width: 960px; padding: 0 20px; }\n"
        "    pre { white-space: pre-wrap; word-wrap: break-word; font-family: inherit; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"<pre>{html.escape(translated_markdown)}</pre>\n"
        "</body>\n"
        "</html>\n",
        encoding="utf-8",
    )
    return {"task_id": task_id, "result_path": TRANSLATION_URL + result_name}


def query_translate_status(task_id: str, user: User) -> Tuple[bool, str]:
    translation = query_one_translation(task_id=task_id, user=user)
    if translation is None:
        raise Exception("Translation not found")
    if translation.task_status == TranslationStatus.Success:
        return True, translation.result_path
    if translation.task_status == TranslationStatus.Working and translation.result_path:
        translation.task_status = TranslationStatus.Success
        translation.save(update_fields=["task_status"])
        return True, translation.result_path
    if translation.task_status == TranslationStatus.Working:
        return False, "Working"
    raise Exception("Translation failed")
