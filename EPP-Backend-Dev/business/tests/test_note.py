from django.test import TestCase, Client

from business.models import User, PaperNote, UserDocumentNote
from business.tests.helper_paper import insert_fake_paper, insert_fake_document
from business.tests.helper_user import insert_user, login_user


class TestNote(TestCase):
    def setUp(self):
        self.client = Client()

        username, password = insert_user()
        self.user = User.objects.get(username=username)
        login_user(self.client, username, password)

        self.paper = insert_fake_paper()
        self.user_document = insert_fake_document(self.user)

    def test_get_note(self):
        PaperNote.objects.create(
            paper_id=self.paper,
            author_id=self.user,
            content="Test note",
            note_type=1,
        )
        response = self.client.get(
            f"/api/article/notes?article_id={self.paper.paper_id}&article_type=2"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), self.paper.papernote_set.count())

    def test_create_note(self):
        data = {
            "type": "highlight",
            "content": "Test note",
            "position": [
                {"pn": 1, "x": 1, "y": 2},
                {"pn": 2, "x": 3, "y": 4},
            ],
        }
        # Insert a note for the paper
        response = self.client.put(
            f"/api/article/note?article_id={self.paper.paper_id}&article_type=2",
            data=data,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaperNote.objects.filter(author_id=self.user).count(), 1)

        # Insert a note for the user document
        response = self.client.put(
            f"/api/article/note?article_id={self.user_document.document_id}&article_type=1",
            data=data,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            UserDocumentNote.objects.filter(author_id=self.user).count(), 1
        )

        # Test with another user
        new_user = insert_user()
        login_user(self.client, *new_user)

        response = self.client.get(
            f"/api/article/notes?article_id={self.paper.paper_id}&article_type=2"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 0)

        response = self.client.get(
            f"/api/article/notes?article_id={self.user_document.document_id}&article_type=1"
        )
        self.assertEqual(response.status_code, 400)

        new_doc = insert_fake_document(
            User.objects.filter(username=new_user[0]).first()
        )
        response = self.client.get(
            f"/api/article/notes?article_id={new_doc.document_id}&article_type=1"
        )
        self.assertEqual(len(response.json()["data"]), 0)

    def test_modify_delete_node(self):
        data = {
            "type": "highlight",
            "content": "First-Note",
            "position": [],
        }

        # Insert a note for the paper
        response = self.client.put(
            f"/api/article/note?article_id={self.paper.paper_id}&article_type=2",
            data=data,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        note_id = response.json()["id"]

        # Check if the note is created
        note = PaperNote.objects.get(note_id=note_id)
        self.assertEqual(note.content, "First-Note")

        # Modify the note
        response = self.client.post(
            f"/api/note?note_id={note_id}",
            data={"content": "Modified-Note"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        note.refresh_from_db()
        self.assertEqual(note.content, "Modified-Note")

        # Delete the note
        response = self.client.delete(f"/api/note?note_id={note_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaperNote.objects.count(), 0)
