import uuid

from django.core.validators import MinValueValidator
from django.db import models


class PaperPosition(models.Model):
    """Field:
    - pos_id          位置ID
    - page_number     页码
    - x               x坐标
    - y               y坐标
    """

    pos_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    page_number = models.IntegerField(validators=[MinValueValidator(1)])
    x = models.IntegerField(validators=[MinValueValidator(0)])
    y = models.IntegerField(validators=[MinValueValidator(0)])
