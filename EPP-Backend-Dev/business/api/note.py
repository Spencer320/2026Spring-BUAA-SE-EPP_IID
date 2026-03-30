# Deprecated!

import json

from django.views.decorators.http import require_http_methods

from business.models import (
    User,
    UserDocumentNote,
    PaperNote,
    PaperPosition,
)
from business.models.paper_note import PaperNoteType
from business.utils.authenticate import authenticate_user
from business.utils.find_article import get_article, ArticleType
from business.utils.response import fail, ok


@authenticate_user
@require_http_methods(["GET"])
def get_all_notes(request, user: User):
    article_id = request.GET.get("article_id")
    article_type = int(request.GET.get("article_type"))

    article = get_article(article_id, article_type, user)
    if isinstance(article, str):
        return fail(err=article)

    if article_type == ArticleType.UserDocument.value:
        notes = UserDocumentNote.objects.filter(
            user_document_id=article, author_id=user
        )
    else:
        notes = PaperNote.objects.filter(paper_id=article, author_id=user)
    data = []
    for note in notes:
        position = []
        for pos in note.position.all():
            position.append(
                {
                    "pn": pos.page_number,
                    "x": pos.x,
                    "y": pos.y,
                }
            )
        data.append(
            {
                "id": str(note.note_id),
                "date": note.date.strftime("%Y-%m-%d %H:%M:%S"),
                "position": position,
                "type": PaperNoteType(note.note_type).name.lower(),
                "content": note.content,
            }
        )

    return ok({"data": data}, msg=f"Get {len(data)} note(s) successfully")


@authenticate_user
@require_http_methods(["PUT"])
def create_note(request, user: User):
    article_id = request.GET.get("article_id")
    article_type = int(request.GET.get("article_type"))
    data = json.loads(request.body)

    article = get_article(article_id, article_type, user)
    if isinstance(article, str):
        return fail(err=article)

    common_fields = {
        "note_type": PaperNoteType.from_str(data["type"]),
        "author_id": user,
        "content": data["content"],
    }

    if article_type == ArticleType.UserDocument.value:
        note = UserDocumentNote.objects.create(
            user_document_id=article,
            **common_fields,
        )
    elif article_type == ArticleType.Publication.value:
        note = PaperNote.objects.create(
            paper_id=article,
            **common_fields,
        )
    else:
        return fail(err="Unreachable code reached!")

    obj_positions = []
    for position in data.get("position"):
        obj_position = PaperPosition.objects.create(
            page_number=position["pn"], x=position["x"], y=position["y"]
        )
        obj_positions.append(obj_position)
    note.position.add(*obj_positions)

    return ok(
        {"id": str(note.note_id), "date": note.date.strftime("%Y-%m-%d %H:%M:%S")}
    )


@authenticate_user
@require_http_methods(["DELETE", "POST"])
def delete_or_modify_note(request, user: User):
    note_id = request.GET.get("note_id")

    note = UserDocumentNote.objects.filter(note_id=note_id).first()
    if note is None:
        note = PaperNote.objects.filter(note_id=note_id).first()
    if note is None:
        return fail(err="Note not found")

    if note.author_id != user:
        return fail(err="Permission denied")

    # Delete the note
    if request.method == "DELETE":
        note.delete()
        return ok(msg="Note deleted successfully")

    # Modify the note's content
    if request.method == "POST":
        data = json.loads(request.body)
        note.content = data["content"]
        note.save()
        return ok(msg="Note modified successfully")
