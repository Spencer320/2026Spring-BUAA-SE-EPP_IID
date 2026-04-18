from django.db import models


class Detectable(models.Model):
    """
    An abstract base model for objects that can be detected for content compliance.

    Fields:
        - date: The date when the object was created.
        - reverted: Whether the object has been reverted.
        - reason: The reason for detection or deletion.
    """

    check_date = models.DateTimeField(auto_now_add=True)
    visibility = models.BooleanField(default=True)
    under_pending = models.BooleanField(default=True)

    class Meta:
        abstract = True

    @staticmethod
    def get_content_name() -> str:
        raise NotImplementedError("Subclasses must implement this method.")

    def insert_auto_delete(self, reason: str = None, title: str = None):
        raise NotImplementedError("Subclasses must implement this method.")

    def block(self):
        """
        Block the content by setting visibility to False.
        """
        self.visibility = False
        self.under_pending = False
        self.save()

    def safe(self):
        """
        Mark the content as safe by setting under_pending to False.
        """
        self.under_pending = False
        self.visibility = True
        self.save()
