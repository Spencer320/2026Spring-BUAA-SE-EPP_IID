"""
用户个人中心功能
api/userInfo/...
"""

import json
import os

from django.views.decorators.http import require_http_methods
from django.db.models import Q
from backend.settings import USER_REPORTS_PATH, BASE_DIR, USER_READ_CONSERVATION_PATH

from business.models import User
from business.models import SearchRecord
from business.models import SummaryReport
from business.models import FileReading
from business.models import Notification
from business.utils.authenticate import authenticate_user
from business.utils.response import ok, fail

if not os.path.exists(USER_READ_CONSERVATION_PATH):
    os.makedirs(USER_READ_CONSERVATION_PATH)
if not os.path.exists(USER_REPORTS_PATH):
    os.makedirs(USER_REPORTS_PATH)


@authenticate_user
@require_http_methods(["GET"])
def user_info(_, user: User):
    """用户基础信息"""
    return ok(
        data={
            "user_id": user.user_id,
            "username": user.username,
            "avatar": user.avatar.url,
            "registration_date": user.registration_date.strftime("%Y-%m-%d %H:%M:%S"),
            "collected_papers_cnt": user.collected_papers.all().count(),
            "liked_papers_cnt": user.liked_papers.all().count(),
        },
        msg="个人信息获取成功",
    )


@authenticate_user
@require_http_methods(["POST"])
def modify_avatar(request, user: User):
    """修改用户头像"""
    user.avatar = request.FILES["avatar"]
    user.save()
    return ok(data={"avatar": user.avatar.url}, msg="头像修改成功")


@authenticate_user
@require_http_methods(["GET"])
def collected_papers_list(_, user: User):
    """收藏文献列表"""
    data = {"total": 0, "papers": []}
    papers_cnt = 0
    for paper in user.collected_papers.all():
        papers_cnt += 1
        data["papers"].append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "authors": paper.authors.split(","),
                "abstract": paper.abstract,
                "publication_date": paper.publication_date.strftime("%Y-%m-%d"),
                "journal": paper.journal,
                "citation_count": paper.citation_count,
                "read_count": paper.read_count,
                "like_count": paper.like_count,
                "collect_count": paper.collect_count,
                "download_count": paper.download_count,
                "score": paper.score,
            }
        )
    data["total"] = papers_cnt
    return ok(data=data, msg="收藏文章列表获取成功")


@authenticate_user
@require_http_methods("DELETE")
def delete_collected_papers(request, user: User):
    """删除收藏论文"""
    params: dict = json.loads(request.body)
    paper_ids = params.get("paper_ids", [])

    if not paper_ids or len(paper_ids) == 0:
        # 清空收藏论文列表
        papers_to_remove = user.collected_papers.all()
    else:
        # 删除指定论文
        papers_to_remove = user.collected_papers.filter(paper_id__in=paper_ids)

    print(len(papers_to_remove))
    # 逐论文处理
    for paper in papers_to_remove:
        paper.collect_count -= 1
        user.collected_papers.remove(paper)
        user.save()
        paper.save()

    return ok(msg="删除成功")


@authenticate_user
@require_http_methods(["GET"])
def search_history_list(request, user: User):
    """搜索历史列表"""
    search_records = SearchRecord.objects.filter(user_id=user).order_by("-date")
    data = {"total": len(search_records), "keywords": []}
    for item in search_records:
        data["keywords"].append(
            {
                "search_record_id": item.search_record_id,
                "keyword": item.keyword,
                "date": item.date.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return ok(data=data, msg="搜索历史记录获取成功")


@authenticate_user
@require_http_methods("DELETE")
def delete_search_history(request, user: User):
    """删除历史搜索记录"""
    params: dict = json.loads(request.body)
    search_record_id = params.get("search_record_id", None)
    print(search_record_id)
    if search_record_id:
        record = SearchRecord.objects.filter(search_record_id=search_record_id).first()
        if record:
            record.delete()
        else:
            return fail(msg="搜索记录不存在")
    else:
        SearchRecord.objects.filter(user_id=user).delete()
    return ok(msg="记录已删除")


@authenticate_user
@require_http_methods(["GET"])
def summary_report_list(_, user: User):
    """查看用户生成的综述报告列表"""
    summary_reports = SummaryReport.objects.filter(
        user_id=user, status=SummaryReport.STATUS_COMPLETED
    )
    data = {"total": len(summary_reports), "reports": []}
    for report in summary_reports:
        data["reports"].append(
            {
                "report_id": report.report_id,
                "title": report.title,
                "path": report.report_path,
                "date": report.date.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    print(data)
    return ok(data=data, msg="综述报告列表获取成功")


@authenticate_user
@require_http_methods("DELETE")
def delete_summary_reports(request, user: User):
    """删除综述报告列表"""
    params: dict = json.loads(request.body)
    report_ids = params.get("report_ids", [])
    if not report_ids or len(report_ids) == 0:
        # 清空综述报告列表
        reports_to_remove = SummaryReport.objects.filter(user_id=user)
    else:
        # 删除指定报告
        reports_to_remove = SummaryReport.objects.filter(
            Q(report_id__in=report_ids) & Q(user_id=user)
        )

    for report in reports_to_remove:
        # 删除报告文件
        path = os.path.join(BASE_DIR, report.report_path)
        if os.path.exists(path):
            os.remove(path)
        report.delete()

    return ok(msg="删除成功")


@authenticate_user
@require_http_methods(["GET"])
def paper_reading_list(_, user: User):
    """论文研读记录列表"""
    reading_list = FileReading.objects.filter(user_id=user).order_by("-date")
    data = {"total": len(reading_list), "paper_reading_list": []}
    for reading in reading_list:
        data["paper_reading_list"].append(
            {
                "mode": 1 if reading.paper_id else 2,  # 1: 论文研读，2: 文件研读
                "file_reading_id": reading.id,
                "paper_id": (
                    reading.paper_id.paper_id
                    if reading.paper_id
                    else reading.document_id.document_id
                ),  # 研读论文ID
                "paper_title": (
                    reading.paper_id.title
                    if reading.paper_id
                    else reading.document_id.title
                ),
                # paper_id为空时，显示文件的标题
                "paper_score": (
                    reading.paper_id.score if reading.paper_id else None
                ),  # 研读论文评分
                # anything to add
                "title": reading.title,  # 研读标题
                "date": reading.date.strftime("%Y-%m-%d %H:%M:%S"),  # 上次研读时间
            }
        )
    return ok(data=data, msg="论文研读记录获取成功")


@authenticate_user
@require_http_methods("DELETE")
def delete_paper_reading(request, user: User):
    """删除论文研读记录"""
    params: dict = json.loads(request.body)
    paper_ids = params.get("paper_ids", [])  # 需要删除的研读论文ID
    mode = params.get("mode", 0)  # 1: 论文研读，2: 文件研读
    if not paper_ids or len(paper_ids) == 0:
        # 清空论文研读历史
        reading_list = FileReading.objects.filter(
            Q(user_id=user) & Q(paper_id__isnull=False)
        )
    else:
        # 删除指定研读历史
        if mode == 1:
            reading_list = FileReading.objects.filter(
                Q(user_id=user) & Q(paper_id__in=paper_ids)
            )
        elif mode == 2:
            reading_list = FileReading.objects.filter(
                Q(user_id=user) & Q(document_id__in=paper_ids)
            )
        else:
            reading_list = FileReading.objects.filter(
                Q(user_id=user) & Q(paper_id__in=paper_ids)
            )

    print(len(reading_list))
    for reading in reading_list:
        # 删除研读历史
        path = os.path.join(BASE_DIR, reading.conversation_path)
        if os.path.exists(path):
            os.remove(path)
        reading.delete()

    return ok(msg="删除成功")


@authenticate_user
@require_http_methods(["GET"])
def notification_list(request, user: User):
    """用户通知列表"""
    mode = int(request.GET.get("mode"))
    if mode == 1:
        notifications = Notification.objects.filter(user_id=user, is_read=False)
        return ok(data={"total": len(notifications)}, msg="未读信息数量获取成功")
    elif mode == 2:
        notifications = Notification.objects.filter(user_id=user)
        data = {"total": len(notifications), "notifications": []}
        for notice in notifications:
            data["notifications"].append(
                {
                    "notification_id": notice.notification_id,
                    "title": notice.title,
                    "content": notice.content,
                    "date": notice.date.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_read": notice.is_read,
                }
            )
        return ok(data=data, msg="通知列表获取成功")
    else:
        return fail(msg="mode参数有误")


@authenticate_user
@require_http_methods(["POST"])
def read_notification(request, user: User):
    """通知已读"""
    params: dict = json.loads(request.body)
    notification_id = params.get("notification_id", [])
    if notification_id and len(notification_id) != 0:
        notice = Notification.objects.filter(
            user_id=user, notification_id=notification_id
        ).first()
        notice.is_read = True
        notice.save()
    else:
        for item in Notification.objects.filter(user_id=user, is_read=False):
            item.is_read = True
            item.save()

    return ok(msg="消息已读完成")


@authenticate_user
@require_http_methods("DELETE")
def delete_notification(request, user: User):
    """删除通知"""
    params: dict = json.loads(request.body)
    notification_ids = params.get("notification_ids", [])  # 需要删除的通知ID数组
    if not notification_ids or len(notification_ids) == 0:
        # 清空通知列表
        notifications_to_remove = Notification.objects.filter(user_id=user)
    else:
        # 删除指定通知
        notifications_to_remove = Notification.objects.filter(
            Q(user_id=user) & Q(notification_id__in=notification_ids)
        )
    print(len(notifications_to_remove))
    notifications_to_remove.delete()

    return ok(msg="删除成功")


@authenticate_user
@require_http_methods(["GET"])
def get_summary_report(request, user: User):
    """获取综述报告"""
    report_id = request.GET.get("report_id")
    report = SummaryReport.objects.filter(report_id=report_id, user_id=user).first()
    if report:
        with open(report.report_path, "r", encoding="utf-8") as f:
            content = f.read()
        return ok({"summary": content}, msg="综述报告获取成功")
    else:
        return fail(msg="综述报告不存在")
