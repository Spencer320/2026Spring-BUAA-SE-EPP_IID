from typing import Dict, Type

from django.views.decorators.http import require_http_methods

from business.models import (
    Admin,
    AutoDeletedFirstComment,
    AutoDeletedSecondComment,
    AutoDeletedAnnotationNew,
    AutoDeletedAnnotationCommentNew,
    AutoDeletedAnnotationSubCommentNew,
)
from business.models.auto_deleted import AutoDeleted
from business.utils.authenticate import authenticate_admin
from business.utils.response import ok, fail

_support_detect: Dict[str, Type[AutoDeleted]] = {
    "paper_comment": AutoDeletedFirstComment,
    "paper_second_comment": AutoDeletedSecondComment,
    "annotation": AutoDeletedAnnotationNew,
    "annotation_comment": AutoDeletedAnnotationCommentNew,
    "annotation_sub_comment": AutoDeletedAnnotationSubCommentNew,
}


def _revert(obj: AutoDeleted, key: str, recover: bool):
    """
    Revert the auto-deleted item based on the key.
    """
    if key not in _support_detect:
        return
    clazz = _support_detect[key]
    if not isinstance(obj, clazz):
        return
    obj.reverted = recover
    obj.save()
    if recover:
        obj.mark_content_safe()
    else:
        obj.mark_content_blocked()


@authenticate_admin
@require_http_methods(["GET"])
def admin_get_all_system_report(request, admin: Admin):
    data = []

    for k, clazz in _support_detect.items():
        items = clazz.objects.all().order_by("-date")
        for item in items:
            author = item.get_author()
            data.append(
                {
                    "id": str(item.id),
                    "comment_id": item.get_id(),
                    "comment_content": item.get_content(),
                    "comment_level": item.get_level(),
                    "author_id": str(author.user_id),
                    "author_name": str(author.username),
                    "author_date": item.get_date(),
                    "reverted": item.reverted,
                    "type": k,
                }
            )

    return ok({"data": data}, msg=f"Get {len(data)} system reports successfully")


@authenticate_admin
@require_http_methods(["POST"])
def admin_recover_system_report(request, admin: Admin):
    auto_deleted_id = request.GET.get("id")
    auto_deleted_type = request.GET.get("type")
    auto_deleted_direct = request.GET.get("direction")

    recover = auto_deleted_direct == "recover"

    if auto_deleted_type not in _support_detect:
        return fail({}, msg="Unsupported type")

    clazz = _support_detect[auto_deleted_type]
    try:
        auto_deleted_item = clazz.objects.get(id=auto_deleted_id)
    except clazz.DoesNotExist:
        return fail({}, msg="Item not found")

    if recover == auto_deleted_item.reverted:
        return fail({}, msg="Item already reverted")

    _revert(auto_deleted_item, auto_deleted_type, recover)

    return ok({}, msg="Item reverted successfully")
