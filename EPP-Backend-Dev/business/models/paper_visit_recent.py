from datetime import timedelta
from typing import Dict

from django.db import models
from django.utils import timezone

from business.models import Paper


class PaperVisitRecent(models.Model):
    """
    Model to store recent paper visit information.
    """

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE)
    visit_time = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def record(paper: Paper):
        """
        Record the recent visit of a paper.
        """
        PaperVisitRecent.objects.create(paper=paper)

    @staticmethod
    def clear_three_days():
        """
        Clear records older than three days.
        """
        print("@@b.m.p.PaperVisitRecent.clear_three_days end at", timezone.now())
        PaperVisitRecent.objects.filter(
            visit_time__lt=timezone.now() - timedelta(days=3)
        ).delete()
        print("@@b.m.p.PaperVisitRecent.clear_three_days end at", timezone.now())

    @staticmethod
    def get_visit_dict() -> Dict[Paper, int]:
        """
        Get a dictionary of papers and their visit counts.
        """
        recent_visits = PaperVisitRecent.objects.values("paper").annotate(
            count=models.Count("paper")
        )
        return {
            Paper.objects.get(pk=visit["paper"]): visit["count"]
            for visit in recent_visits
        }
