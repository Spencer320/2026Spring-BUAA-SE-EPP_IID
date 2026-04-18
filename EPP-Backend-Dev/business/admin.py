from django.contrib import admin as django_admin

# Register your models here.

from .models import *

for model in [
    User,
    Paper,
    PaperPosition,
    PaperVisitRecent,
    PaperAnnotation,
    PaperAnnotationCommentFirstLevel,
    PaperAnnotationCommentSecondLevel,
    PaperNote,
    UserDocumentNote,
    AbstractReport,
    Admin,
    AutoDeletedPaperAnnotation,
    AutoDeletedPaperAnnotationFirstComment,
    AutoDeletedPaperAnnotationSecondComment,
    AutoDeletedFirstComment,
    AutoDeletedSecondComment,
    AutoDeletedAnnotationNew,
    AutoDeletedAnnotationCommentNew,
    AutoDeletedAnnotationSubCommentNew,
    Glossary,
    GlossaryTerm,
    PaperTranslation,
    UserDocumentTranslation,
    FirstLevelComment,
    SecondLevelComment,
    CommentReport,
    FileReading,
    PaperScore,
    SummaryReport,
    UserDocument,
    SearchRecord,
    Notification,
    UserDailyAddition,
    UserVisit,
    Subclass,
    SummaryGenerateSession,
    PaperAnnotationNew,
    PaperAnnotationComment,
    PaperAnnotationSubComment,
    PaperAnnotationItem,
    SummaryDialogStorage,
    VectorSearchStorage,
]:
    try:
        django_admin.site.register(model)
    except Exception as e:
        print(f"Failed to register {model.__name__}: {e}")
