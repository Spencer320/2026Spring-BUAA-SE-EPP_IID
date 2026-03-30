import itertools
import json
from pathlib import Path

from django.views.decorators.http import require_http_methods

from business.api.paper_interpret import get_paper_local_url
from business.models import (
    User,
    Paper,
    UserDocument,
    Glossary,
    PaperTranslation,
    UserDocumentTranslation,
)
from business.models.paper_translation import TranslationStatus
from business.utils.article_translate import (
    do_article_translate,
    query_translate_status,
)
from business.utils.authenticate import authenticate_user
from business.utils.find_article import raw_get_article, ArticleType
from business.utils.glossary_recommend import glossary_recommend
from business.utils.response import ok, fail


@authenticate_user
@require_http_methods(["GET"])
def translate_glossary_view(request, _: User):
    paper = Paper.objects.filter(paper_id=request.GET.get("paper_id")).first()
    document = UserDocument.objects.filter(
        document_id=request.GET.get("document_id")
    ).first()

    glossaries = Glossary.objects.all()
    glossary_names = [glossary.name for glossary in glossaries]
    if paper is not None:
        recommend = glossary_recommend(glossary_names, Path(paper.local_path))
    elif document is not None:
        recommend = glossary_recommend(glossary_names, Path(document.local_path))
    else:
        recommend = [False] * glossaries.count()

    data = []
    for glossary, rec in zip(glossaries, recommend):
        data.append(
            {
                "id": glossary.glossary_id,
                "name": glossary.name,
                "recommend": rec,
            }
        )
    data.sort(
        key=lambda x: ("0##" if x["recommend"] else "1##") + x["name"], reverse=False
    )

    return ok(
        {"data": data},
        msg=f"Get {len(data)} glossary(s), with {len([rec for rec in recommend if rec])} recommended successfully",
    )


@authenticate_user
@require_http_methods(["GET"])
def get_glossary(request, _: User):
    glossary = Glossary.objects.filter(
        glossary_id=request.GET.get("glossary_id")
    ).first()
    if glossary is None:
        return fail(err="Glossary not found")

    data = []
    for term in glossary.terms.all():
        data.append({"en": term.term, "zh": term.translation})

    return ok(
        {"name": glossary.name, "data": data},
        msg=f"Get glossary successfully",
    )


@authenticate_user
@require_http_methods(["GET"])
def get_user_info_translation(request, user: User):
    data = []
    for translation in itertools.chain(
        PaperTranslation.objects.filter(user=user),
        UserDocumentTranslation.objects.filter(user=user),
    ):
        item = {
            "id": translation.translation_id,
            "title": (
                translation.paper.title
                if isinstance(translation, PaperTranslation)
                else translation.user_document.title
            ),
            "task_id": translation.task_id,
            "date": translation.date.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if translation.glossary is not None:
            item["glossary_name"] = translation.glossary.name
        if translation.task_status == TranslationStatus.Working:
            try:
                query_translate_status(translation.task_id, user)
            except Exception as e:
                print("Error getting task status:", repr(e))
            translation.refresh_from_db()
        if translation.task_status == TranslationStatus.Success:
            item["path"] = translation.result_path
            item["status"] = "done"
        elif translation.task_status == TranslationStatus.Working:
            item["status"] = "working"
        else:
            item["status"] = "fail"
        data.append(item)
    return ok(
        {"data": data},
        msg=f"Get {len(data)} translation(s) successfully",
    )


@authenticate_user
@require_http_methods(["DELETE"])
def delete_translation(request, user: User):
    translation_id = request.GET.get("translation_id")

    target = PaperTranslation.objects.filter(
        translation_id=translation_id, user=user
    ).first()
    if target is None:
        target = UserDocumentTranslation.objects.filter(
            translation_id=translation_id, user_document__user=user
        ).first()

    if target is None:
        return fail(err="Translation not found")

    target.delete()
    return ok(msg="Delete translation successfully")


@authenticate_user
@require_http_methods(["POST"])
def translate_article(request, user: User):
    article_id = request.GET.get("id")

    data = json.loads(request.body)
    glossary_id = data.get("glossary_id")
    reuse = data.get("reuse")

    article_type, article = raw_get_article(article_id)

    if article_type == ArticleType.Invalid or article is None:
        return fail(err="Article not found")

    if glossary_id is not None:
        glossary = Glossary.objects.filter(glossary_id=glossary_id).first()
        if glossary is None:
            return fail(err="Glossary not found")
    else:
        glossary = None

    if reuse:
        if article_type == ArticleType.UserDocument:
            translation = (
                UserDocumentTranslation.objects.filter(
                    user_document=article,
                    glossary=glossary,
                    task_status=TranslationStatus.Success,
                    user=user,
                )
                .order_by("-date")
                .first()
            )
        else:
            translation = (
                PaperTranslation.objects.filter(
                    paper=article,
                    glossary=glossary,
                    task_status=TranslationStatus.Success,
                )
                .order_by("-date")
                .first()
            )
            if translation is not None and translation.user != user:
                translation = PaperTranslation.objects.create(
                    paper=article,
                    glossary=glossary,
                    result_path=translation.result_path,
                    task_id=translation.task_id,
                    task_status=TranslationStatus.Success,
                    user=user,
                )
        if translation is not None:
            return ok(
                {
                    "id": translation.task_id,
                },
                msg="Reuse translation successfully",
            )

    # Both the user document & paper have a 'local path' field
    task_id = do_article_translate(glossary, Path(get_paper_local_url(article)))
    if task_id is None:
        return fail(err="Translation failed")
    if article_type == 1:
        UserDocumentTranslation.objects.create(
            user_document=article,
            glossary=glossary,
            task_id=task_id,
            user=user,
        )
    else:
        PaperTranslation.objects.create(
            paper=article,
            glossary=glossary,
            task_id=task_id,
            user=user,
        )
    return ok(
        {
            "id": task_id,
        },
        msg="Translate article successfully",
    )


@authenticate_user
@require_http_methods(["GET"])
def query_trans_status(request, user: User):
    task_id = request.GET.get("id")
    try:
        status, info = query_translate_status(task_id, user)
    except Exception as e:
        return fail({"status": "fail"}, err=str(e))
    if status:
        return ok(
            {"status": "done", "url": info},
            msg="Query translation status successfully",
        )
    else:
        return ok(
            {"status": "working"},
            msg="Query translation status successfully, " + info,
        )
