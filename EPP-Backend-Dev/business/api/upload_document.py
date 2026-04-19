"""
用户上传论文相关接口
"""

import os
from backend.settings import USER_DOCUMENTS_PATH
from backend.settings import USER_DOCUMENTS_URL
from business.models import User, UserDocument, FileReading
import json
import random
import time
from django.views.decorators.http import require_http_methods

from business.utils.authenticate import authenticate_user
from business.utils.response import ok, fail

if not os.path.exists(USER_DOCUMENTS_PATH):
    os.makedirs(USER_DOCUMENTS_PATH)


@authenticate_user
@require_http_methods(["POST"])
def upload_paper(request, user: User):
    """
    上传文献
    """
    file = request.FILES.get("new_paper")
    print(file)
    print(request.session)
    if user and file:
        # 保存文件
        file_name = os.path.splitext(file.name)[0]
        file_ext = os.path.splitext(file.name)[1]
        store_name = (
            file_name
            + time.strftime("%Y%m%d%H%M%S")
            + "_%d" % random.randint(0, 100)
            + file_ext
        )
        file_size = file.size
        file_path = USER_DOCUMENTS_PATH + "/" + store_name
        with open(file_path, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)
        # 保存文献信息
        usr_document = UserDocument(
            user_id=user,
            title=file_name,
            local_path=file_path,
            format=file_ext,
            size=file_size,
        )
        usr_document.save()
        file_url = USER_DOCUMENTS_URL + store_name
        return ok(
            {
                "file_id": usr_document.document_id,
                "file_url": file_url,
            },
            msg="上传成功",
        )
    else:
        return fail(err="用户或文件不存在")


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
        else:
            return fail(err="用户无权限删除该文献")
    else:
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
    else:
        return fail(err="文件不存在")
