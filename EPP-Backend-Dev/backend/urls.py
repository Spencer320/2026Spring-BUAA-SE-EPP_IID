"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

import re

from django.contrib import admin
from django.urls import include, path
from django.conf import settings

# from django.conf.urls.static import static
from django.urls import re_path
from django.views.static import serve

from business.api.annotation import (
    get_annotation_first_comment,
    get_annotation_subcomment,
    annotation_comment_first_level,
    annotation_comment_second_level,
    create_annotation_new,
    get_all_annotations_new,
    annotation_like_toggle_new,
)
from business.api.manage import (
    manager_get_popular_saearch,
    manager_get_popular_paper,
    manager_get_visit_time,
)
from business.api.manage_auto_deleted_items import (
    admin_get_all_system_report,
    admin_recover_system_report,
)
from business.api.note import get_all_notes, create_note, delete_or_modify_note
from business.api.paper_interpret import (
    clear_conversation,
    re_do_paper_study,
    create_paper_study,
    restore_paper_study,
    do_paper_study,
    get_paper_url,
)
from business.api.auth import (
    login,
    signup,
    test_login,
    logout,
    manager_login,
    manager_logout,
)
from business.api.paper_details import (
    like_paper,
    score_paper,
    collect_paper,
    report_comment,
    comment_paper,
    batch_download_papers,
    get_paper_info,
    get_first_comment,
    get_second_comment,
    like_comment,
    get_user_paper_info,
)
from business.api.paper_notes import save_notes, list_notes
from business.api.translation import (
    translate_glossary_view,
    get_glossary,
    get_user_info_translation,
    translate_article,
    delete_translation,
    query_trans_status,
)
from business.api.upload_document import (
    upload_paper,
    remove_uploaded_paper,
    document_list,
    get_document_url,
)
from business.api import user_info, manage
from business.api.search import (
    get_user_search_history,
    vector_query,
    dialog_query_v2,
    flush,
    restore_search_record,
    build_kb,
    change_record_papers,
    vector_query_v2,
    vector_query_v2_get_status,
    vector_query_v2_get_result,
    dialog_query_v2_get_status,
    dialog_query_v2_get_result,
)
from business.utils.paper_vdb_init import local_vdb_init, local_vdb_status, easy_vector_query
from business.api.summary import (
    generate_summary,
    create_abstract_report,
    get_summary_status,
    get_summary_v2_get_status,
    get_summary_v2_set_user_response,
)

from business.api.paper_recommend import get_recommendation, individuation_recommend
from business.api import manage_access_frequency
from business.api.deep_research import (
    # 用户端
    user_create_task,
    user_task_status,
    user_task_events,
    user_task_report,
    user_abort_task,
    user_follow_up,
    user_export_tasks,
    # 管理端
    admin_stats,
    admin_task_list,
    admin_task_detail,
    admin_task_trace,
    admin_force_stop,
    admin_suppress_output,
    admin_unsuppress_output,
    admin_task_audit_logs,
    admin_global_audit_logs,
)


def static_in_all_mode(prefix, view=serve, **kwargs):
    return [
        re_path(
            r"^%s(?P<path>.*)$" % re.escape(prefix.lstrip("/")), view, kwargs=kwargs
        ),
    ]


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/research-agent/", include("research_agent.urls")),
    # 用户及管理员认证模块
    path("api/login", login),
    path("api/sign", signup),
    path("api/testLogin", test_login),
    path("api/logout", logout),
    path("api/managerLogin", manager_login),
    path("api/managerLogout", manager_logout),
    # 论文详情界面
    path("api/userLikePaper", like_paper),
    path("api/userScoring", score_paper),
    path("api/collectPaper", collect_paper),
    path("api/reportComment", report_comment),
    path("api/commentPaper", comment_paper),
    path("api/batchDownload", batch_download_papers),
    path("api/getPaperInfo", get_paper_info),
    path("api/getComment1", get_first_comment),
    path("api/getComment2", get_second_comment),
    path("api/likeComment", like_comment),
    path("api/getUserPaperInfo", get_user_paper_info),
    # 用户上传论文模块
    path("api/uploadPaper", upload_paper),
    path("api/removeUploadedPaper", remove_uploaded_paper),
    path("api/userInfo/documents", document_list),
    path("api/getDocumentURL", get_document_url),
    # 个人中心
    path("api/userInfo/userInfo", user_info.user_info),
    path("api/userInfo/avatar", user_info.modify_avatar),
    path("api/userInfo/collectedPapers", user_info.collected_papers_list),
    path("api/userInfo/delCollectedPapers", user_info.delete_collected_papers),
    path("api/userInfo/searchHistory", user_info.search_history_list),
    path("api/userInfo/delSearchHistory", user_info.delete_search_history),
    path("api/userInfo/summaryReports", user_info.summary_report_list),
    path("api/userInfo/delSummaryReports", user_info.delete_summary_reports),
    path("api/userInfo/paperReading", user_info.paper_reading_list),
    path("api/userInfo/delPaperReading", user_info.delete_paper_reading),
    path("api/userInfo/notices", user_info.notification_list),
    path("api/userInfo/readNotices", user_info.read_notification),
    path("api/userInfo/delNotices", user_info.delete_notification),
    path("api/userInfo/getSummary", user_info.get_summary_report),
    # 管理端
    path("api/manage/users", manage.user_list),
    path("api/manage/papers", manage.paper_list),
    path("api/manage/commentReports", manage.comment_report_list),
    path("api/manage/commentReportDetail", manage.comment_report_detail),
    path("api/manage/judgeCmtRpt", manage.judge_comment_report),
    # path("api/manage/delComment", manage.delete_comment),
    path("api/manage/userProfile", manage.user_profile),
    path("api/manage/userStatistic", manage.user_statistic),
    path("api/manage/paperOutline", manage.paper_outline),
    path("api/manage/paperStatistic", manage.paper_statistic),
    path("api/manage/serverStatus", manage.server_status),
    path("api/manage/recordVisit", manage.record_visit),
    path("api/manage/visitStatistic", manage.visit_statistic),
    path("api/manage/popular/search", manager_get_popular_saearch),
    path("api/manage/popular/papers", manager_get_popular_paper),
    path("api/manage/visittime", manager_get_visit_time),
    path("api/manage/filtered/comments", admin_get_all_system_report),
    path("api/manage/filtered/recover", admin_recover_system_report),
    # 信息检索模块
    path("api/search/easyVectorQuery", easy_vector_query),
    # path("api/search/vectorQuery", vector_query),
    path("api/v2/search/vectorQuery", vector_query_v2),
    path("api/v2/search/status", vector_query_v2_get_status),
    path("api/v2/search/result", vector_query_v2_get_result),
    # path("api/search/dialogQuery", dialog_query),
    path("api/v2/search/dialogQuery", dialog_query_v2),
    path("api/v2/search/dialog/status", dialog_query_v2_get_status),
    path("api/v2/search/dialog/result", dialog_query_v2_get_result),
    path("api/search/flush", flush),
    path("api/search/restoreSearchRecord", restore_search_record),
    path("api/study/getUserSearchHistory", get_user_search_history),
    path("api/search/rebuildKB", build_kb),
    # path('api/search/getSearchRecord', get_search_record),
    path("api/search/changeRecordPapers", change_record_papers),
    # 向量化模块
    # path("insert_vector_database", insert_vector_database),
    # 文献研读模块
    path("api/study/createPaperStudy", create_paper_study),
    path("api/study/restorePaperStudy", restore_paper_study),
    path("api/study/doPaperStudy", do_paper_study),
    path("api/study/getPaperPDF", get_paper_url),
    path("api/study/reDoPaperStudy", re_do_paper_study),
    path("api/study/clearConversation", clear_conversation),
    path("api/study/generateAbstractReport", create_abstract_report),
    # 本地向量库初始化
    path("api/init/localVDBInit", local_vdb_init),
    path("api/init/localVDBStatus", local_vdb_status),
    # 综述摘要生成
    path("api/summary/generateSummaryReport", generate_summary),
    path("api/summary/generateAbstractReport", create_abstract_report),
    path("api/summary/getSummaryStatus", get_summary_status),
    path("api/v2/summary/status", get_summary_v2_get_status),
    path("api/v2/summary/response", get_summary_v2_set_user_response),
    # 热门文献推荐
    path("api/paperRecommend/hot", get_recommendation),
    path("api/paperRecommend/personalized", individuation_recommend),
    path("api/refresh", get_recommendation),
    # 文献笔记模块（新版）
    path("api/saveNote", save_notes),
    path("api/listNotes", list_notes),
    # 文献批注模块
    path("api/paper/annotations", get_all_annotations_new),
    path("api/paper/annotation", create_annotation_new),
    path("api/annotation/comments", get_annotation_first_comment),
    path("api/annotation/comment/subcomments", get_annotation_subcomment),
    path("api/annotation/like/toggle", annotation_like_toggle_new),
    path("api/annotation/comment", annotation_comment_first_level),
    path("api/annotation/comments/subcomment", annotation_comment_second_level),
    # 文献翻译模块
    path("api/translate/glossaries", translate_glossary_view),
    path("api/translate/glossary", get_glossary),
    path("api/userInfo/translations", get_user_info_translation),
    path("api/article/translate", translate_article),
    path("api/translate/status", query_trans_status),
    path("api/userInfo/translation", delete_translation),
    # 文献笔记模块
    path("api/article/notes", get_all_notes),
    path("api/article/note", create_note),
    path("api/note", delete_or_modify_note),
    # ── Deep Research 用户端 ─────────────────────────────────────────
    path("api/deep-research/tasks", user_create_task),
    path("api/deep-research/tasks/export", user_export_tasks),
    path("api/deep-research/tasks/<str:task_id>/status", user_task_status),
    path("api/deep-research/tasks/<str:task_id>/events", user_task_events),
    path("api/deep-research/tasks/<str:task_id>/report", user_task_report),
    path("api/deep-research/tasks/<str:task_id>/abort", user_abort_task),
    path("api/deep-research/tasks/<str:task_id>/follow-up", user_follow_up),
    # ── Deep Research 管理端监控 ─────────────────────────────────────
    path("api/manage/deep-research/stats", admin_stats),
    path("api/manage/deep-research/tasks", admin_task_list),
    path("api/manage/deep-research/audit-logs", admin_global_audit_logs),
    path("api/manage/deep-research/tasks/<str:task_id>", admin_task_detail),
    path("api/manage/deep-research/tasks/<str:task_id>/trace", admin_task_trace),
    path("api/manage/deep-research/tasks/<str:task_id>/force-stop", admin_force_stop),
    path("api/manage/deep-research/tasks/<str:task_id>/suppress-output", admin_suppress_output),
    path("api/manage/deep-research/tasks/<str:task_id>/unsuppress-output", admin_unsuppress_output),
    path("api/manage/deep-research/tasks/<str:task_id>/audit-logs", admin_task_audit_logs),
    # ── 访问频次控制管理端 ───────────────────────────────────────────
    path("api/manage/access-frequency/rules", manage_access_frequency.rule_list_create),
    path("api/manage/access-frequency/rules/<int:rule_id>", manage_access_frequency.rule_update_delete),
    path("api/manage/access-frequency/user-overrides", manage_access_frequency.override_list_create),
    path("api/manage/access-frequency/user-overrides/<int:override_id>", manage_access_frequency.override_delete),
    path("api/manage/access-frequency/stats", manage_access_frequency.global_stats),
    path("api/manage/access-frequency/stats/users", manage_access_frequency.user_stats_ranking),
    path("api/manage/access-frequency/stats/users/<str:user_id>", manage_access_frequency.user_stats_detail),
] + static_in_all_mode(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
