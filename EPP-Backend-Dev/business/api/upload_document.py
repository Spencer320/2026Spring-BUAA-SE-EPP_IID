"""
用户上传论文相关接口
"""

import json
import os
import random
import re
import time

from django.views.decorators.http import require_http_methods

from backend.settings import USER_DOCUMENTS_PATH, USER_DOCUMENTS_URL
from business.models import FileReading, User, UserDocument
from business.utils.authenticate import authenticate_user
from business.utils.response import fail, ok

if not os.path.exists(USER_DOCUMENTS_PATH):
    os.makedirs(USER_DOCUMENTS_PATH)


def _sanitize_upload_name(raw_name: str) -> tuple[str, str]:
    base_name = os.path.basename(raw_name or "document")
    file_name, file_ext = os.path.splitext(base_name)
    if not file_name:
        file_name = "document"
    file_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", file_name.strip())[:80]
    file_ext = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", file_ext.strip())[:20]
    if not file_name:
        file_name = "document"
    return file_name, file_ext


@authenticate_user
@require_http_methods(["POST"])
def upload_paper(request, user: User):
    """
    上传文献
    """
    file = request.FILES.get("new_paper")
    if not (user and file):
        return fail(err="用户或文件不存在")

    try:
        file_name, file_ext = _sanitize_upload_name(file.name)
        store_name = (
            file_name
            + time.strftime("%Y%m%d%H%M%S")
            + "_%d" % random.randint(0, 100)
            + file_ext
        )
        file_size = file.size
        file_path = os.path.join(USER_DOCUMENTS_PATH, store_name)

        with open(file_path, "wb") as uploaded_file:
            for chunk in file.chunks():
                uploaded_file.write(chunk)

        user_document = UserDocument(
            user_id=user,
            title=file_name,
            local_path=file_path,
            format=file_ext,
            size=file_size,
        )
        user_document.save()

        file_url = USER_DOCUMENTS_URL + store_name
        return ok(
            {
                "file_id": user_document.document_id,
                "file_url": file_url,
            },
            msg="上传成功",
        )
    except Exception as exc:
        return fail(err=f"上传失败: {str(exc)}")


@authenticate_user
@require_http_methods(["POST"])
def remove_uploaded_paper(request, user: User):
    """
    删除上传的文献
    """
    data = json.loads(request.body)
    document_id = data.get("paper_id")
    document = UserDocument.objects.filter(document_id=document_id).first()
    if user and document:
        if document.user_id == user:
            if os.path.exists(document.local_path):
                os.remove(document.local_path)
            document.delete()
            return ok(msg="删除成功")
        return fail(err="用户无权限删除该文献")
    return fail(err="用户或文献不存在")


@authenticate_user
@require_http_methods(["GET"])
def document_list(_, user: User):
    """用户上传文件列表"""
    documents = UserDocument.objects.filter(user_id=user).order_by("-upload_date")
    data = {"total": len(documents), "documents": []}
    for document in documents:
        url = USER_DOCUMENTS_URL + os.path.basename(document.local_path)
        file_reading = FileReading.objects.filter(
            document_id=document.document_id
        ).first()
        data["documents"].append(
            {
                "document_id": document.document_id,
                "document_url": url,
                "file_reading_id": file_reading.id if file_reading else None,
                "title": document.title,
                "format": document.format,
                "size": document.size,
                "date": document.upload_date.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return ok(data=data, msg="文件列表获取成功")


@require_http_methods(["GET"])
def get_document_url(request):
    """
    获取用户上传文件url
    """
    document_id = request.GET.get("document_id")
    document = UserDocument.objects.filter(document_id=document_id).first()
    if document:
        return ok(
            {
                "local_url": "/" + document.local_path,
            },
            msg="获取成功",
        )
    return fail(err="文件不存在")
