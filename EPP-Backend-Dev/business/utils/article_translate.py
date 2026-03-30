import json
from pathlib import Path
from typing import Tuple

from django.conf import settings

from business.models import Glossary, User
from business.models.paper_translation import query_one_translation, TranslationStatus

from business.utils.pdf_translate import TranslationAPIError, SimplifyAITranslator

translator = SimplifyAITranslator(settings.SIMPLIFY_TRANS_KEY)


def do_article_translate(glossary: Glossary | None, raw_file: Path) -> str | None:
    """
    Translate the article using SimplifyAI API.
    :param glossary: Glossary object containing terms and translations.
    :param raw_file: Path to the article file.
    :return: Task ID of the translation task or None means error detected.
    """
    files = open(raw_file, "rb")

    if glossary is not None:
        glossary_content = {
            term.term: term.translation for term in glossary.terms.all()
        }
    else:
        glossary_content = {}

    try:
        return translator.create_translation_task(
            files,
            "English",
            "Simplified Chinese",
            glossaryContent=json.dumps(glossary_content),
        )
    except TranslationAPIError as e:
        print("Error creating translation task:", repr(e))
        return None


def query_translate_status(task_id: str, user: User) -> Tuple[bool, str]:
    translation = query_one_translation(task_id=task_id, user=user)
    if translation is None:
        raise Exception("Translation not found")
    if translation.task_status == TranslationStatus.Working:
        try:
            status_info = translator.get_task_status(task_id)
            if status_info["status"] == "Completed":
                translation.task_status = TranslationStatus.Success
                translation.result_path = status_info["translatedFileUrl"]
                translation.save()
                return True, translation.result_path
        except TranslationAPIError as e:
            translation.task_status = TranslationStatus.Failed
            translation.save()
            raise Exception("Error getting task status: " + repr(e))
        return False, "Working"
    elif translation.task_status == TranslationStatus.Success:
        return True, translation.result_path
    else:
        raise Exception("Translation failed")
