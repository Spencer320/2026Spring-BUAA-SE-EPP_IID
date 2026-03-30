import json
import threading

from django.views.decorators.http import require_http_methods

from business.models import (
    User,
    Paper,
    PaperAnnotationNew,
    PaperAnnotationItem,
    PaperAnnotationComment,
)
from business.utils.authenticate import authenticate_user
from business.utils.auto_detect import detect_content_safety

from business.utils.response import ok, fail


@authenticate_user
@require_http_methods(["GET"])
def get_all_annotations_new(request, user: User):
    paper_id = request.GET.get("paper_id")
    paper = Paper.objects.get(paper_id=paper_id)

    annos = PaperAnnotationNew.objects.filter(paper=paper)
    annotations = []
    for anno in annos.all():
        items = []
        for item in anno.paperannotationitem_set.all():
            author = item.author
            if item.under_pending or not item.visibility:
                if user != author:
                    continue
                else:
                    author_name = author.username + "（仅自己可见）"
            else:
                author_name = author.username
            items.append(
                {
                    "id": item.id,
                    "position": anno.position,
                    "content": item.content,
                    "data": item.last_modified.strftime("%Y-%m-%d %H:%M:%S"),
                    "author_name": author_name,
                    "author_avatar": f"{request.scheme}://{request.get_host()}{author.avatar.url}",
                    "liked": user in item.liked_by_user.all(),
                    "comment_count": item.paperannotationcomment_set.count(),
                }
            )
        # annotations.append({"passage_content": anno.passage_content, "comments": items})
        annotations.extend(items)

    return ok(
        data={"data": annotations},
        msg=f"Get {len(annotations)} annotation(s) successfully",
    )


@authenticate_user
@require_http_methods(["POST"])
def annotation_like_toggle_new(request, user: User):
    annotation_id = request.GET.get("annotation_id")
    annotation_item = PaperAnnotationItem.objects.get(id=annotation_id)
    if annotation_item is None:
        return fail(err="Annotation not found")

    if user in annotation_item.liked_by_user.all():
        annotation_item.liked_by_user.remove(user)
        return ok(msg="Unlike successfully")
    else:
        annotation_item.liked_by_user.add(user)
        return ok(msg="Like successfully")


@authenticate_user
@require_http_methods(["PUT"])
def create_annotation_new(request, user: User):
    paper_id = request.GET.get("paper_id")
    paper = Paper.objects.get(paper_id=paper_id)
    if paper is None:
        return fail(err="Paper not found")
    data = json.loads(request.body)
    position = data.get("position")
    content = data.get("content", {"content": ""}).get("content", "")

    # Get the annotation content from the request body
    annotation = PaperAnnotationNew.objects.filter(
        position=position, paper=paper
    ).first()
    if annotation is None:
        annotation = PaperAnnotationNew.objects.create(paper=paper, position=position)

    # Insert the annotation content
    item = PaperAnnotationItem.objects.create(
        annotation=annotation,
        content=content,
        author=user,
    )

    threading.Thread(target=detect_content_safety, args=(content, item)).start()

    return ok({"id": item.id}, msg="Annotation created successfully")


@authenticate_user
@require_http_methods(["GET"])
def get_annotation_first_comment(request, user: User):
    annotation_id = request.GET.get("annotation_id")
    annotation_item = PaperAnnotationItem.objects.get(id=annotation_id)

    if annotation_item is None:
        return fail(err="Annotation not found")

    data = []
    for comment in annotation_item.paperannotationcomment_set.all():
        author = comment.author
        if comment.under_pending or not comment.visibility:
            if user != author:
                continue
            else:
                author_name = author.username + "（仅自己可见）"
        else:
            author_name = author.username
        data.append(
            {
                "id": comment.id,
                "date": comment.last_modified.strftime("%Y-%m-%d %H:%M:%S"),
                "author_name": author_name,
                "author_avatar": f"{request.scheme}://{request.get_host()}{author.avatar.url}",
                "content": comment.content,
                "like_count": comment.liked_by_user.count(),
                "liked": user in comment.liked_by_user.all(),
                "sub_comment_count": comment.paperannotationsubcomment_set.count(),
                "owned": comment.author_id == user,
            }
        )

    return ok({"data": data}, msg=f"Get {len(data)} comment(s) successfully")


@authenticate_user
@require_http_methods(["GET"])
def get_annotation_subcomment(request, user: User):
    annotation_id = request.GET.get("annotation_id")
    comment_id = request.GET.get("comment_id")

    annotation_item = PaperAnnotationItem.objects.get(id=annotation_id)
    if annotation_item is None:
        return fail(err="Annotation not found")
    comment = annotation_item.paperannotationcomment_set.get(id=comment_id)
    if comment is None:
        return fail(err="Comment not found")

    data = []
    for sub_comment in comment.paperannotationsubcomment_set.all():
        author = sub_comment.author
        if sub_comment.under_pending or not sub_comment.visibility:
            if user != author:
                continue
            else:
                author_name = author.username + "（仅自己可见）"
        else:
            author_name = author.username
        data.append(
            {
                "id": sub_comment.id,
                "date": sub_comment.last_modified.strftime("%Y-%m-%d %H:%M:%S"),
                "author_name": author_name,
                "author_avatar": f"{request.scheme}://{request.get_host()}{author.avatar.url}",
                "content": sub_comment.content,
                "like_count": sub_comment.liked_by_user.count(),
                "liked": user in sub_comment.liked_by_user.all(),
                "owned": sub_comment.author_id == user,
            }
        )

    return ok({"data": data}, msg=f"Get {len(data)} sub-comment(s) successfully")


@authenticate_user
@require_http_methods(["PUT"])
def annotation_comment_first_level(request, user: User):
    annotation_id = request.GET.get("annotation_id")
    annotation_item = PaperAnnotationItem.objects.get(id=annotation_id)
    if annotation_item is None:
        return fail(err="Annotation not found")

    data = json.loads(request.body)
    text = data.get("comment")
    comment = PaperAnnotationComment.objects.create(
        author=user, annotation_item=annotation_item, content=text
    )

    threading.Thread(target=detect_content_safety, args=(text, comment)).start()

    return ok(
        {"id": comment.id, "date": comment.last_modified.strftime("%Y-%m-%d %H:%M:%S")},
        msg="Comment created successfully",
    )


@authenticate_user
@require_http_methods(["PUT"])
def annotation_comment_second_level(request, user: User):
    annotation_id = request.GET.get("annotation_id")
    annotation_item = PaperAnnotationItem.objects.get(id=annotation_id)
    if annotation_item is None:
        return fail(err="Annotation not found")

    comment_id = request.GET.get("comment_id")
    comment = annotation_item.paperannotationcomment_set.get(id=comment_id)
    if comment is None:
        return fail(err="Comment not found")

    data = json.loads(request.body)
    text = data.get("comment")
    sub_comment = comment.paperannotationsubcomment_set.create(
        author=user, parent_comment=comment, content=text
    )

    threading.Thread(target=detect_content_safety, args=(text, sub_comment)).start()

    return ok(
        {
            "id": sub_comment.id,
            "date": sub_comment.last_modified.strftime("%Y-%m-%d %H:%M:%S"),
        },
        msg="Sub-comment created successfully",
    )
