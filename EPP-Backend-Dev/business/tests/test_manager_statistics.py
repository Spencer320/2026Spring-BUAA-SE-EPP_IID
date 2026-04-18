import datetime

from django.test import TestCase, Client

from business.tests.helper_paper import insert_fake_paper
from business.tests.helper_user import insert_admin, login_admin, insert_user
from business.models import SearchRecord, User, PaperVisitRecent, UserVisit


class TestManagerStatistics(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = insert_admin()
        self.user = User.objects.filter(username=insert_user()[0]).first()
        login_admin(self.client, *self.admin)

    def test_get_popular_search(self):
        # Insert search records
        key_words = ["kw1"] * 10 + ["kw2"] * 5 + ["kw3"] * 3
        for keyword in key_words:
            SearchRecord.objects.create(user_id=self.user, keyword=keyword)
        response = self.client.get("/api/manage/popular/search")
        self.assertEqual(response.status_code, 200)
        self.assertIn("data", response.json())

        data = response.json()["data"]
        self.assertEqual(len(data), 3)

        # Test the top ten search records
        for i in range(20):
            SearchRecord.objects.create(user_id=self.user, keyword=f"kw{i}")

        response = self.client.get("/api/manage/popular/search")
        data = response.json()["data"]
        self.assertEqual(len(data), 10)

    def test_get_popular_paper(self):
        papers = [insert_fake_paper() for _ in range(20)]
        for _ in range(10):
            PaperVisitRecent.record(papers[0])
            PaperVisitRecent.record(papers[1])
        for _ in range(5):
            PaperVisitRecent.record(papers[1])
            PaperVisitRecent.record(papers[2])

        response = self.client.get("/api/manage/popular/papers")
        self.assertEqual(response.status_code, 200)
        self.assertIn("data", response.json())
        data = response.json()["data"]
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]["id"], str(papers[1].paper_id))

        for paper in papers:
            PaperVisitRecent.record(paper)

        response = self.client.get("/api/manage/popular/papers")
        data = response.json()["data"]
        self.assertEqual(len(data), 10)

    def test_visit_record(self):
        today = datetime.datetime.now()
        if today.hour < 6:
            today -= datetime.timedelta(days=1)

        for i in range(4):
            for j in range(i + 1):
                time = today.replace(hour=i * 6 + j)
                UserVisit.objects.create(ip_address="127.0.0.1", timestamp=time)

        today -= datetime.timedelta(days=1)
        for i in range(4):
            for j in range(5 - i):
                time = today.replace(hour=i * 6 + j)
                UserVisit.objects.create(ip_address="127.0.0.1", timestamp=time)

        response = self.client.get("/api/manage/visittime")
        self.assertEqual(response.status_code, 200)
        self.assertIn("data", response.json())
        data = response.json()["data"]
        self.assertEqual(len(data), 30)
        self.assertEqual(data[-2]["date"], today.strftime("%Y-%m-%d"))
        for i in range(4):
            self.assertEqual(data[-1]["visits"][i], i + 1)
            self.assertEqual(data[-2]["visits"][i], 5 - i)
