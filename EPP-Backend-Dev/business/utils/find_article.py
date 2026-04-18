from enum import IntEnum
from typing import Tuple

from business.models import UserDocument, Paper, User


class ArticleType(IntEnum):
    Invalid = 0
    UserDocument = 1
    Publication = 2


def raw_get_article(article_id: str) -> Tuple[ArticleType, UserDocument | Paper | None]:
    paper = Paper.objects.filter(paper_id=article_id).first()
    if paper is not None:
        return ArticleType.Publication, paper
    user_document = UserDocument.objects.filter(document_id=article_id).first()
    if user_document is not None:
        return ArticleType.UserDocument, user_document
    return ArticleType.Invalid, None


def get_article(
    article_id: str, article_type: int, user: User | None
) -> UserDocument | Paper | str:
    try:
        article_type = ArticleType(article_type)  # Validate the article type
    except ValueError:
        return f"Invalid article type, got `{article_type}`, with type `{type(article_type)}`"

    article = None
    if article_type == ArticleType.UserDocument:
        article = UserDocument.objects.filter(document_id=article_id).first()
        if article is not None and user is not None and article.user_id != user:
            return f"User `{user}` does not have permission to access this document"
    if article_type == ArticleType.Publication:
        article = Paper.objects.filter(paper_id=article_id).first()

    if article is None:
        return f"Cannot find article with id `{article_id}` & type `{article_type}`"

    return article
