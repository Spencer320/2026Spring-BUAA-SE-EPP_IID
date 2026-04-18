from django.test import TestCase, Client

from business.models import User, Glossary
from business.tests.helper_paper import insert_fake_paper, insert_fake_document
from business.tests.helper_user import login_user, insert_user


class TestTranslation(TestCase):
    def setUp(self):
        self.client = Client()

        self.username, self.password = insert_user()
        self.user = User.objects.get(username=self.username)
        login_user(self.client, self.username, self.password)

        self.paper = insert_fake_paper()
        self.document = insert_fake_document(self.user)

        for name in [
            "[recommend] glossary8",
            "glossary6",
            "[recommend] glossary3",
            "glossary4",
        ]:
            target_glossary = Glossary.objects.create(name=name)
        self.target_glossary = target_glossary
        self.term_data = [
            ("term 1", "翻译 1"),
            ("term 2", "翻译 2"),
            ("term 3", "翻译 3"),
        ]
        for term, translation in self.term_data:
            target_glossary.terms.create(term=term, translation=translation)

    def test_glossary_recommend(self):
        response = self.client.get(
            f"/api/translate/glossaries?paper_id={self.paper.paper_id}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 4)
        for i, (result, gid) in enumerate(
            [(True, 3), (True, 8), (False, 4), (False, 6)]
        ):
            self.assertEqual(response.json()["data"][i]["recommend"], result)
            self.assertIn(f"glossary{gid}", response.json()["data"][i]["name"])

    def test_glossary_view(self):
        response = self.client.get(
            f"/api/translate/glossary?glossary_id={self.target_glossary.glossary_id}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 3)
        for i, (term, translation) in enumerate(self.term_data):
            self.assertEqual(response.json()["data"][i]["en"], term)
            self.assertEqual(response.json()["data"][i]["zh"], translation)

    def _test_translate(self):
        def get_all_translations():
            r = self.client.get(
                f"/api/userInfo/translations",
            )
            self.assertEqual(r.status_code, 200)
            return r.json()["data"]

        # Do translate with the self.paper
        response = self.client.post(
            f"/api/article/translate?id={self.paper.paper_id}",
            data={
                "file_type": 2,
                "reuse": False,
            },
            content_type="application/json",
        )
        old_translation_id = response.json()["id"]
        self.assertEqual(response.status_code, 200)
        translations = get_all_translations()
        self.assertEqual(len(translations), 1)
        self.assertEqual(translations[0]["title"], self.paper.title)

        # Test NOT reuse the translation
        response = self.client.post(
            f"/api/article/translate?id={self.paper.paper_id}",
            data={
                "file_type": 2,
                "reuse": False,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        new_translation_id = response.json()["id"]
        translations = get_all_translations()
        self.assertEqual(len(translations), 2)
        self.assertEqual(translations[1]["title"], self.paper.title)

        self.assertNotEqual(old_translation_id, new_translation_id)
        self.assertNotEqual(translations[0]["path"], translations[1]["path"])
        self.assertEqual(translations[0]["id"], old_translation_id)
        self.assertEqual(translations[1]["id"], new_translation_id)

        # Test reuse the translation
        response = self.client.post(
            f"/api/article/translate?id={self.paper.paper_id}",
            data={
                "file_type": 2,
                "reuse": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        translations = get_all_translations()
        self.assertEqual(len(translations), 2)
        self.assertEqual(response.json()["id"], new_translation_id)

        # Test different glossary
        response = self.client.post(
            f"/api/article/translate?id={self.paper.paper_id}",
            data={
                "file_type": 2,
                "glossary_id": self.target_glossary.glossary_id,
                "reuse": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        translations = get_all_translations()
        old_translation_id_with_glossary = response.json()["id"]
        self.assertEqual(len(translations), 3)

        # Test delete
        response = self.client.delete(
            f"/api/userInfo/translation?translation_id={old_translation_id_with_glossary}",
        )
        self.assertEqual(response.status_code, 200)
        translations = get_all_translations()
        self.assertEqual(len(translations), 2)

        # Deleted translation should not be reused
        response = self.client.post(
            f"/api/article/translate?id={self.paper.paper_id}",
            data={
                "file_type": 2,
                "glossary_id": self.target_glossary.glossary_id,
                "reuse": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["id"], old_translation_id_with_glossary)

    def _test_different_user_reuse(self):
        response = self.client.post(
            f"/api/article/translate?id={self.paper.paper_id}",
            data={
                "file_type": 2,
                "reuse": False,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        old_translation_id = response.json()["id"]
        old_path = response.json()["path"]

        # Switch to another user
        username, password = insert_user()
        login_user(self.client, username, password)

        response = self.client.post(
            f"/api/article/translate?id={self.paper.paper_id}",
            data={
                "file_type": 2,
                "reuse": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        new_translation_id = response.json()["id"]
        new_path = response.json()["path"]

        self.assertNotEqual(old_translation_id, new_translation_id)
        self.assertEqual(old_path, new_path)
