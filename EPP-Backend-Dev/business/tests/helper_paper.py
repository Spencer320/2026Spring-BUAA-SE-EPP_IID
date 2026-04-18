import datetime
import random
import uuid

from business.models import Paper, User, UserDocument


def insert_fake_paper():
    return Paper.objects.create(
        title=f"Fake Paper {uuid.uuid4()}",
        authors="author1,author2",
        abstract="This is a fake paper",
        publication_date=datetime.date.today(),
        journal=None,  # 期刊允许为空，arXiv没有
        citation_count=random.randint(0, 1000),
        original_url="https://arxiv.org/abs/xxxx.xxxxx",
        read_count=random.randint(0, 1000),
        like_count=0,
        collect_count=0,
        comment_count=0,
        download_count=random.randint(0, 1000),
        local_path="/dev/null",
    )


def insert_fake_document(user: User):
    return UserDocument.objects.create(
        user_id=user,
        title=f"Fake Document {uuid.uuid4()}",
        local_path="/dev/null",
        format="pdf",
        size=random.randint(500, 1000),
    )
