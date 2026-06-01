import base64
import json

from django.views.decorators.http import require_http_methods

from business.models import User, PaperNote, UserDocumentNote
from business.utils.authenticate import authenticate_user
from business.utils.find_article import raw_get_article, ArticleType
from business.utils.response import fail, ok


@authenticate_user
@require_http_methods(["POST"])
def save_notes(request, user: User):
    data = json.loads(request.body)
    paper_id = data.get("paper_id")
    name = data.get("name") or "未命名笔记"
    annotations = data.get("annotations") or []
    markdown_text = data.get("markdown") or ""
    markdown = base64.b64encode(markdown_text.encode()).decode()

    article_type, article = raw_get_article(paper_id)
    clazz = None

    if article_type == ArticleType.Invalid:
        return fail(err=f"Not found paper with id `{paper_id}`")
    elif article_type == ArticleType.Publication:
        clazz = PaperNote
    elif article_type == ArticleType.UserDocument:
        clazz = UserDocumentNote

    lookup = {"author_id": user, "name": name}
    article_field = "paper_id" if article_type == ArticleType.Publication else "user_document_id"
    lookup[article_field] = article

    paper_note = clazz.objects.filter(**lookup).first()
    if paper_note is None:
        clazz.objects.create(
            **lookup,
            contents=annotations,
            markdown=markdown,
        )
    else:
        paper_note.contents = annotations
        paper_note.markdown = markdown
        paper_note.save()

    return ok(msg="Saved!")


@authenticate_user
@require_http_methods(["GET"])
def list_notes(request, user: User):
    paper_id = request.GET.get("paper_id")
    article_type, article = raw_get_article(paper_id)

    if article_type == ArticleType.Invalid:
        return fail(err=f"Not found paper with id `{paper_id}`")

    annotations = []
    if article_type == ArticleType.Publication:
        for paper_note in PaperNote.objects.filter(author_id=user, paper_id=article):
            annotations.append(
                {
                    "name": paper_note.name,
                    "annotations": paper_note.contents or [],
                    "markdown": base64.b64decode(paper_note.markdown or "").decode(),
                }
            )
    elif article_type == ArticleType.UserDocument:
        for paper_note in UserDocumentNote.objects.filter(
            author_id=user, user_document_id=article
        ):
            annotations.append(
                {
                    "name": paper_note.name,
                    "annotations": paper_note.contents or [],
                    "markdown": base64.b64decode(paper_note.markdown or "").decode(),
                }
            )
    return ok(
        data={"annotations": annotations},
        msg=f"Successfully get {len(annotations)} notes",
    )
