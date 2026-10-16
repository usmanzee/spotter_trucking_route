from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from trips.clients.models import GeocodedLocation
from trips.exceptions import ProviderTimeoutError
from trips.services.analysis import TripAnalysisService
from trips.services.checkpoints import Coordinate
from trips.tests.test_analysis import FakeRouteClient, FakeWeatherClient, make_route


class TripAnalysisApiTests(APITestCase):
    def valid_payload(self):
        return {
            "origin": "Lahore, Pakistan",
            "destination": "Karachi, Pakistan",
            "departure_time": (timezone.now() + timedelta(days=1)).isoformat(),
            "cargo_weight_lb": 35_000,
            "checkpoint_interval_miles": 25,
        }

    @patch("trips.views.build_analysis_service")
    def test_trip_analysis_endpoint_returns_complete_result(self, build_service):
        build_service.return_value = TripAnalysisService(
            FakeRouteClient(routes=[make_route()]),
            FakeWeatherClient(),
        )

        response = self.client.post(
            reverse("trips:trip-analysis-create"),
            self.valid_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "complete")
        self.assertEqual(response.data["recommendation"]["route_id"], "route-1")
        self.assertEqual(len(response.data["routes"]), 1)

    def test_invalid_checkpoint_interval_uses_standard_error_envelope(self):
        payload = self.valid_payload()
        payload["checkpoint_interval_miles"] = 30

        response = self.client.post(
            reverse("trips:trip-analysis-create"), payload, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(
            "checkpoint_interval_miles", response.data["error"]["details"]
        )

    def test_equal_origin_and_destination_are_rejected(self):
        payload = self.valid_payload()
        payload["destination"] = "lahore, pakistan"

        response = self.client.post(
            reverse("trips:trip-analysis-create"), payload, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")

    @patch("trips.views.build_analysis_service")
    def test_provider_timeout_maps_to_504(self, build_service):
        class TimeoutService:
            def analyze(self, trip):
                raise ProviderTimeoutError(
                    "Geoapify",
                    "Geoapify timed out.",
                    code="provider_timeout",
                    retryable=True,
                )

        build_service.return_value = TimeoutService()

        response = self.client.post(
            reverse("trips:trip-analysis-create"),
            self.valid_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.data["error"]["code"], "provider_timeout")


class LocationSearchApiTests(APITestCase):
    @patch("trips.views.build_geocoding_client")
    def test_location_search_returns_normalized_suggestions(self, build_client):
        class FakeGeocodingClient:
            def geocode(self, query, *, limit=5):
                self.query = query
                self.limit = limit
                return (
                    GeocodedLocation(
                        provider_id="mock-lahore",
                        label="Lahore, Punjab, Pakistan",
                        coordinate=Coordinate(31.5204, 74.3587),
                        result_type="city",
                    ),
                )

        client = FakeGeocodingClient()
        build_client.return_value = client

        response = self.client.get(
            reverse("trips:location-search"),
            {"q": "Lahore"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.query, "Lahore")
        self.assertEqual(client.limit, 5)
        self.assertEqual(response.data["results"][0]["provider_id"], "mock-lahore")
        self.assertEqual(response.data["results"][0]["lat"], 31.5204)

    def test_location_search_requires_two_characters(self):
        response = self.client.get(
            reverse("trips:location-search"),
            {"q": "C"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
