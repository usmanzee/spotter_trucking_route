from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_health_check_returns_ok(self):
        response = self.client.get(reverse("trips:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_local_frontend_origin_is_allowed(self):
        response = self.client.get(
            reverse("trips:health"),
            HTTP_ORIGIN="http://127.0.0.1:5173",
        )

        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "http://127.0.0.1:5173",
        )
