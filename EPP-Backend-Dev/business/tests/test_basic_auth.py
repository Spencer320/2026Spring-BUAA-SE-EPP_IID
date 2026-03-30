from django.test import TestCase, Client

from business.tests.helper_session import get_session_dict
from business.tests.helper_user import insert_user


class TestBasicAuth(TestCase):
    def setUp(self):
        self.username, self.password = insert_user()
        self.client = Client()

    def test_login(self):
        response = self.client.post(
            "/api/login",
            data={"username": self.username, "userpassword": self.password},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_session_dict(response).get("username"), self.username)

        response = self.client.get("/api/testLogin")
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/api/logout")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("username", get_session_dict(response))

        response = self.client.get("/api/testLogin")
        self.assertEqual(response.status_code, 400)
