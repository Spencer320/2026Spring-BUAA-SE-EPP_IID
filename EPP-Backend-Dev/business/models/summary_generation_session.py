import uuid

from django.db import models


class SummaryStatus(models.IntegerChoices):
    Initial = 0, "Initial"
    WaitingAI = 1, "Waiting AI"
    WaitingUser = 2, "Waiting User"
    Done = 3, "Done"


class SummaryGenerateSession(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, unique=True
    )
    search_record = models.ForeignKey(
        "SearchRecord", on_delete=models.CASCADE, related_name="summary_session"
    )
    paper_ids = models.JSONField(default=list)

    status = models.IntegerField(
        choices=SummaryStatus.choices, default=SummaryStatus.Initial
    )
    date = models.DateTimeField(auto_now_add=True)
    update = models.DateTimeField(auto_now=True)
    content_buffer = models.TextField(default="")

    def receive_ai_response_continue(self, content):
        # if self.status != SummaryStatus.WaitingAI:
        #     raise ValueError("Invalid status for AI response.")
        self.status = SummaryStatus.WaitingUser
        self.content_buffer = content
        self.save()

    def receive_ai_response_stop(self, content):
        # if self.status != SummaryStatus.WaitingAI:
        #     raise ValueError("Invalid status for AI response.")
        self.status = SummaryStatus.Done
        self.content_buffer = content
        self.save()

    def receive_user_response_continue(self, content):
        # if self.status != SummaryStatus.WaitingUser:
        #     raise ValueError("Invalid status for User response.")
        self.status = SummaryStatus.WaitingAI
        self.content_buffer = content
        self.save()

    def receive_user_response_stop(self):
        # if self.status != SummaryStatus.WaitingUser:
        #     raise ValueError("Invalid status for User response.")
        self.status = SummaryStatus.Done
        self.content_buffer = ""
        self.save()
