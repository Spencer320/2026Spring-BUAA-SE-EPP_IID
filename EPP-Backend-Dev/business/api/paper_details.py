"""
论文详情页相关接口
"""

import json
import random
import threading
import time
import zipfile
import os
from django.views.decorators.http import require_http_methods
from business.models import (
    User,
    Paper,
    PaperScore,
    CommentReport,
    FirstLevelComment,
    SecondLevelComment,
    Notification,
    PaperVisitRecent,
)
from business.utils.authenticate import authenticate_user
from business.utils.auto_detect import detect_content_safety
from business.utils.response import ok, fail
from business.utils.download_paper import download_paper
from backend.settings import (
    BATCH_DOWNLOAD_PATH,
    BATCH_DOWNLOAD_URL,
)

if not os.path.exists(BATCH_DOWNLOAD_PATH):
    os.makedirs(BATCH_DOWNLOAD_PATH)


@authenticate_user
@require_http_methods(["POST"])
def like_paper(request, user: User):
    """
    点赞/取消点赞文献
    """
    data = json.loads(request.body)
    paper_id = data.get("paper_id")
    paper = Paper.objects.filter(paper_id=paper_id).first()
    liked = user.liked_papers.filter(paper_id=paper_id).first()
    # 取消点赞
    if liked:
        user.liked_papers.remove(paper)
        paper.like_count -= 1
        user.save()
        paper.save()
        return ok(msg="取消点赞成功")
    # 点赞
    if user and paper:
        user.liked_papers.add(paper)
        paper.like_count += 1
        user.save()
        paper.save()

        PaperVisitRecent.record(paper)

        return ok(msg="点赞成功")
    else:
        return fail(err="用户或文献不存在")


@authenticate_user
@require_http_methods(["POST"])
def score_paper(request, user: User):
    """
    文献评分
    """
    data = json.loads(request.body)
    paper_id = data.get("paper_id")
    score = data.get("score")
    paper = Paper.objects.filter(paper_id=paper_id).first()
    paper_score = PaperScore.objects.filter(user_id=user, paper_id=paper).first()
    # 判断用户是否对该文献进行过评分
    if paper_score:
        return fail({"error": "用户已对该文献进行过评分"})
    # 判断评分是否在1到5之间，且为整数
    if not isinstance(score, int) or score < 1 or score > 5:
        return fail({"error": "评分应为0到10之间的整数"})
    # 存储评分，更新文献平均分，保留两位小数
    if user and paper:
        paper_score = PaperScore(user_id=user, paper_id=paper, score=score)
        paper_score.save()
        paper.score_count += 1
        paper.score = round(
            (paper.score * (paper.score_count - 1) + score) / paper.score_count, 2
        )
        paper.save()

        PaperVisitRecent.record(paper)

        return ok(msg="评分成功")
    else:
        return fail(err="用户或文献不存在")


@authenticate_user
@require_http_methods(["POST"])
def collect_paper(request, user: User):
    """
    收藏/取消收藏文献
    """
    data = json.loads(request.body)
    paper_id = data.get("paper_id")
    paper = Paper.objects.filter(paper_id=paper_id).first()
    collected = user.collected_papers.filter(paper_id=paper_id).first()
    # 取消收藏
    if collected:
        user.collected_papers.remove(paper)
        paper.collect_count -= 1
        user.save()
        paper.save()
        return ok(msg="取消收藏成功")
    # 收藏
    if user and paper:
        user.collected_papers.add(paper)
        paper.collect_count += 1
        user.save()
        paper.save()

        PaperVisitRecent.record(paper)

        return ok(msg="收藏成功")
    else:
        return fail(err="用户或文献不存在")


@authenticate_user
@require_http_methods(["POST"])
def report_comment(request, user: User):
    """
    举报评论
    """
    data = json.loads(request.body)
    comment_id = data.get("comment_id")
    comment_level = data.get("comment_level")
    report = data.get("report")
    # 这里需要知道是一级评论还是二级评论
    comment = None
    if comment_level == 1:
        comment = FirstLevelComment.objects.filter(comment_id=comment_id).first()
    elif comment_level == 2:
        comment = SecondLevelComment.objects.filter(comment_id=comment_id).first()
    if user and comment:
        if comment_level == 1:
            report_com = CommentReport(
                comment_id_1=comment, comment_level=1, user_id=user, content=report
            )
            report_com.save()
        elif comment_level == 2:
            report_com = CommentReport(
                comment_id_2=comment, comment_level=2, user_id=user, content=report
            )
            report_com.save()
        return ok(msg="举报成功")
    else:
        return fail(err="用户或评论不存在")


@authenticate_user
@require_http_methods(["POST"])
def comment_paper(request, user: User):
    """
    用户评论（含一级、二级评论）
    """
    data = json.loads(request.body)
    paper_id = data.get("paper_id")
    comment_level = data.get("comment_level")  # 1 / 2
    text = data.get("comment")
    paper = Paper.objects.filter(paper_id=paper_id).first()
    if user and paper:
        if comment_level == 1:
            comment = FirstLevelComment(user_id=user, paper_id=paper, text=text)
            comment.save()
        elif comment_level == 2:
            level1_comment_id = data.get("level1_comment_id")
            level1_comment = FirstLevelComment.objects.filter(
                comment_id=level1_comment_id
            ).first()
            # 如果是回复二级评论的评论，获取其回复的二级评论的id
            reply_comment_id = data.get("reply_comment_id")
            reply_comment = None
            if reply_comment_id:
                reply_comment = SecondLevelComment.objects.filter(
                    comment_id=reply_comment_id
                ).first()
            comment = SecondLevelComment(
                user_id=user,
                paper_id=paper,
                text=text,
                level1_comment=level1_comment,
                reply_comment=reply_comment,
            )
            comment.save()
        else:
            return fail(err="评论级别错误")
        paper.comment_count += 1
        paper.save()

        PaperVisitRecent.record(paper)
        threading.Thread(target=detect_content_safety, args=(text, comment)).start()

        return ok(msg="评论成功")
    else:
        return fail(err="用户或文献不存在")


@authenticate_user
@require_http_methods(["GET"])
def get_first_comment(request, user: User):
    """
    获取一级评论
    """
    paper_id = request.GET.get("paper_id")
    comments = FirstLevelComment.objects.filter(paper_id=paper_id)
    data = []
    for comment in comments:
        second_len = SecondLevelComment.objects.filter(
            level1_comment_id=comment.comment_id,
            visibility=True,
        ).count()
        author = comment.user_id
        if comment.under_pending or not comment.visibility:
            if user != author:
                continue
            else:
                author_name = author.username + "（仅自己可见）"
        else:
            author_name = author.username
        data.append(
            {
                "comment_id": comment.comment_id,
                "date": comment.date.strftime("%Y-%m-%d %H:%M:%S"),
                "text": comment.text,
                "like_count": comment.like_count,
                "username": author_name,
                "user_image": comment.user_id.avatar.url,
                "user_liked": comment.liked_by_users.filter(username=user).first()
                is not None,
                "second_len": second_len,
            }
        )
    total = len(data)
    return ok(
        {
            "total": total,
            "comments": data,
        },
        msg="获取成功",
    )


@authenticate_user
@require_http_methods(["GET"])
def get_second_comment(request, user: User):
    """
    获取二级评论
    """
    level1_comment_id = request.GET.get("comment1_id")
    comments = SecondLevelComment.objects.filter(level1_comment_id=level1_comment_id)
    data = []
    for comment in comments:
        if comment.level1_comment.visibility is False:
            continue
        if comment.reply_comment and comment.reply_comment.visibility is False:
            continue
        author = comment.user_id
        if comment.under_pending or not comment.visibility:
            if user != author:
                continue
            else:
                author_name = author.username + "（仅自己可见）"
        else:
            author_name = author.username
        data.append(
            {
                "comment_id": comment.comment_id,
                "date": comment.date.strftime("%Y-%m-%d %H:%M:%S"),
                "text": comment.text,
                "like_count": comment.like_count,
                "to_username": (
                    comment.reply_comment.user_id.username
                    if comment.reply_comment
                    else None
                ),
                "username": author_name,
                "user_image": comment.user_id.avatar.url,
                "user_liked": comment.liked_by_users.filter(username=user).first()
                is not None,
            }
        )
    return ok({"comments": data}, msg="获取成功")


@authenticate_user
@require_http_methods(["POST"])
def like_comment(request, user: User):
    """
    点赞评论/取消点赞评论
    """
    data = json.loads(request.body)
    comment_id = data.get("comment_id")
    comment_level = data.get("comment_level")
    # 这里需要知道是一级评论还是二级评论
    comment = None
    if comment_level == 1:
        comment = FirstLevelComment.objects.filter(comment_id=comment_id).first()
    elif comment_level == 2:
        comment = SecondLevelComment.objects.filter(comment_id=comment_id).first()
    if user and comment:
        liked = comment.liked_by_users.filter(user_id=user.user_id).first()
        # 取消点赞
        if liked:
            comment.like_count -= 1
            comment.liked_by_users.remove(user)
            comment.save()
            return ok(msg="取消点赞成功")
        # 点赞
        else:
            comment.like_count += 1
            comment.liked_by_users.add(user)
            comment.save()
            # 被点赞的评论的作者收到通知
            notification = Notification(user_id=comment.user_id, title="你被赞了！")
            paper = comment.paper_id
            paper_title = paper.title
            notification.content = (
                "你在论文《"
                + paper_title
                + "》的评论被用户"
                + user.username
                + "点赞了！"
            )
            notification.save()
            return ok(msg="点赞成功")
    else:
        return fail(err="用户或评论不存在")


@authenticate_user
@require_http_methods(["POST"])
def batch_download_papers(request, user: User):
    """
    批量下载文献
    """
    data = json.loads(request.body)
    username = user.username
    paper_ids = data.get("paper_id_list")
    papers = Paper.objects.filter(paper_id__in=paper_ids)
    if user and papers:
        for paper in papers:
            # 首先判断文献是否有本地副本，没有则下载到服务器
            if not paper.local_path or not os.path.exists(paper.local_path):
                original_url = paper.original_url
                # 将路径中的abs修改为pdf，最后加上.pdf后缀
                original_url = original_url.replace("abs", "pdf") + ".pdf"
                # 访问url，下载文献到服务器
                filename = str(paper.paper_id)
                local_path = download_paper(original_url, filename)
                paper.local_path = local_path
                paper.save()

            PaperVisitRecent.record(paper)

        # 将所有paper打包成zip文件，存入BATCH_DOWNLOAD_PATH，返回zip文件路径
        zip_name: str = (
            username
            + "_batchDownload_"
            + time.strftime("%Y%m%d%H%M%S")
            + "_%d" % random.randint(0, 100)
            + ".zip"
        )
        zip_file_path = os.path.join(BATCH_DOWNLOAD_PATH, zip_name)
        print(zip_file_path)
        with zipfile.ZipFile(zip_file_path, "w") as z:
            for paper in papers:
                z.write(paper.local_path, paper.title + ".pdf")
        zip_url = BATCH_DOWNLOAD_URL + zip_name
        return ok({"zip_url": zip_url}, msg="下载成功")
    else:
        return fail(err="用户或文献不存在")


@require_http_methods(["GET"])
def get_paper_info(request):
    """
    获取文献信息
    """
    paper_id = request.GET.get("paper_id")
    paper = Paper.objects.filter(paper_id=paper_id).first()
    if paper:
        return ok(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "authors": paper.authors,
                "abstract": paper.abstract,
                "publication_date": paper.publication_date.strftime("%Y-%m-%d"),
                "journal": paper.journal,
                "citation_count": paper.citation_count,
                "read_count": paper.read_count,
                "like_count": paper.like_count,
                "collect_count": paper.collect_count,
                "download_count": paper.download_count,
                "comment_count": paper.comment_count,
                "score": paper.score,
                "score_count": paper.score_count,
                "original_url": paper.original_url,
            },
            msg="获取成功",
        )
    else:
        return fail(err="文献不存在")


@authenticate_user
@require_http_methods(["GET"])
def get_user_paper_info(request, user: User):
    """
    获得用户对论文的收藏、点赞、评分情况
    """
    paper_id = request.GET.get("paper_id")
    paper = Paper.objects.filter(paper_id=paper_id).first()
    if user and paper:
        liked = user.liked_papers.filter(paper_id=paper_id).first()
        collected = user.collected_papers.filter(paper_id=paper_id).first()
        scored = PaperScore.objects.filter(user_id=user, paper_id=paper).first()
        return ok(
            {
                "liked": True if liked else False,
                "collected": True if collected else False,
                "scored": True if scored else False,
                "score": scored.score if scored else 0,
            },
            msg="获取成功",
        )
    else:
        return fail(err="用户或文献不存在")
