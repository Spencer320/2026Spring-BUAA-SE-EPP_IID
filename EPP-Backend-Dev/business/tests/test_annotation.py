import datetime

from django.test import TestCase, Client

from business.models import PaperAnnotation, User
from business.models.paper_annotation import AnnotationType
from business.tests.helper_paper import insert_fake_paper
from business.tests.helper_user import insert_user, login_user


class TestAnnotation(TestCase):
    def setUp(self):
        self.client = Client()

        self.username, self.password = insert_user()
        self.user = User.objects.get(username=self.username)
        login_user(self.client, self.username, self.password)

        self.user2_username, _ = insert_user()

        self.paper = insert_fake_paper()

    def test_get_annotation(self):
        response = self.client.get(
            f"/api/paper/annotations?paper_id={self.paper.paper_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            len(response.json()["data"]), self.paper.paperannotation_set.count()
        )

    def test_owned(self):
        PaperAnnotation.objects.create(
            author_id=self.user,
            paper_id=self.paper,
            annotation_type=AnnotationType.POSTIL,
            date=datetime.datetime.now(),
            content="test",
        ).save()
        PaperAnnotation.objects.create(
            author_id=User.objects.get(username=self.user2_username),
            paper_id=self.paper,
            annotation_type=AnnotationType.POSTIL,
            date=datetime.datetime.now(),
            content="test",
        ).save()
        response = self.client.get(
            f"/api/paper/annotations?paper_id={self.paper.paper_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"][0]["owned"])
        self.assertFalse(response.json()["data"][1]["owned"])

    def test_create(self):
        response = self.client.put(
            f"/api/paper/annotation?paper_id={self.paper.paper_id}",
            data={
                "position": [{"pn": 1, "x": 0, "y": 0}],
                "type": "underline",
                "content": "test",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaperAnnotation.objects.filter(paper_id=self.paper).count(), 1)

        response = self.client.get(
            f"/api/paper/annotations?paper_id={self.paper.paper_id}"
        )
        self.assertEqual(response.status_code, 200)
        # Underline annotation should not have content
        self.assertNotEqual(response.json()["data"][0]["content"], "test")
        self.assertEqual(response.json()["data"][0]["type"], "underline")
        self.assertEqual(
            response.json()["data"][0]["position"][0], {"pn": 1, "x": 0, "y": 0}
        )

    def test_create_content(self):
        self.client.put(
            f"/api/paper/annotation?paper_id={self.paper.paper_id}",
            data={"position": [], "type": "postil", "content": "test"},
            content_type="application/json",
        )
        response = self.client.get(
            f"/api/paper/annotations?paper_id={self.paper.paper_id}"
        )
        self.assertEqual(response.json()["data"][0]["content"], "test")

    def test_comment(self):
        # Create annotation
        annotation = PaperAnnotation.objects.create(
            author_id=self.user,
            paper_id=self.paper,
            annotation_type=AnnotationType.POSTIL,
            date=datetime.datetime.now(),
            content="test",
        )
        annotation.save()

        # Do first level comment
        response = self.client.put(
            f"/api/annotation/comment?annotation_id={annotation.id}",
            data={"comment": "test->first"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        first_comment_id = response.json()["id"]

        # Do second level comment
        response = self.client.put(
            f"/api/annotation/comments/subcomment?annotation_id={annotation.id}&comment_id={first_comment_id}",
            data={"comment": "test->second"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        # Get the first level comment
        response = self.client.get(
            f"/api/annotation/comments?annotation_id={annotation.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)
        self.assertEqual(response.json()["data"][0]["content"], "test->first")

        # Get the second level comment
        response = self.client.get(
            f"/api/annotation/comment/subcomments?annotation_id={annotation.id}&comment_id={first_comment_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)
        self.assertEqual(response.json()["data"][0]["content"], "test->second")

    def test_comment_like(self):
        # Create annotation
        annotation = PaperAnnotation.objects.create(
            author_id=self.user,
            paper_id=self.paper,
            annotation_type=AnnotationType.UNDERLINE,
        )
        annotation.save()

        # Do first level comment
        response = self.client.put(
            f"/api/annotation/comment?annotation_id={annotation.id}",
            data={"comment": ""},
            content_type="application/json",
        )
        first_comment_id = response.json()["id"]

        # Like the first level comment
        response = self.client.post(
            f"/api/annotation/comments/like/toggle?comment_id={first_comment_id}&comment_level=1"
        )
        self.assertEqual(response.status_code, 200)

        # Get the first level comment
        response = self.client.get(
            f"/api/annotation/comments?annotation_id={annotation.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"][0]["like_count"], 1)

        # Unlike the first level comment
        response = self.client.post(
            f"/api/annotation/comments/like/toggle?comment_id={first_comment_id}&comment_level=1"
        )
        self.assertEqual(response.status_code, 200)

        # Get the first level comment
        response = self.client.get(
            f"/api/annotation/comments?annotation_id={annotation.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"][0]["like_count"], 0)

        # Do second level comment
        response = self.client.put(
            f"/api/annotation/comments/subcomment?annotation_id={annotation.id}&comment_id={first_comment_id}",
            data={"comment": ""},
            content_type="application/json",
        )
        second_comment_id = response.json()["id"]

        # Like the second level comment
        response = self.client.post(
            f"/api/annotation/comments/like/toggle?comment_id={second_comment_id}&comment_level=2"
        )
        self.assertEqual(response.status_code, 200)

        # Get the second level comment
        response = self.client.get(
            f"/api/annotation/comment/subcomments?annotation_id={annotation.id}&comment_id={first_comment_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"][0]["like_count"], 1)

        # Check the wrong comment level
        response = self.client.post(
            f"/api/annotation/comments/like/toggle?comment_id={second_comment_id}&comment_level=3"
        )
        self.assertEqual(response.status_code, 400)
