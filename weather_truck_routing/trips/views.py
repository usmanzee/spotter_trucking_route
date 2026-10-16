from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from trips.clients.geoapify import GeoapifyClient
from trips.clients.open_meteo import OpenMeteoClient
from trips.exceptions import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    TripAnalysisError,
)
from trips.serializers import LocationSearchQuerySerializer, TripAnalysisRequestSerializer
from trips.services.analysis import TripAnalysisInput, TripAnalysisService


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """Return a lightweight liveness response without calling external services."""

    return Response({"status": "ok"})


def build_geocoding_client() -> GeoapifyClient:
    return GeoapifyClient(
        settings.GEOAPIFY_API_KEY,
        geocoding_url=settings.GEOAPIFY_GEOCODING_URL,
        routing_url=settings.GEOAPIFY_ROUTING_URL,
        timeout_seconds=settings.PROVIDER_TIMEOUT_SECONDS,
        max_retries=settings.PROVIDER_MAX_RETRIES,
    )


def build_analysis_service() -> TripAnalysisService:
    route_client = build_geocoding_client()
    weather_client = OpenMeteoClient(
        forecast_url=settings.OPEN_METEO_FORECAST_URL,
        timeout_seconds=settings.PROVIDER_TIMEOUT_SECONDS,
        max_retries=settings.PROVIDER_MAX_RETRIES,
    )
    return TripAnalysisService(route_client, weather_client)


@api_view(["GET"])
@permission_classes([AllowAny])
def search_locations(request):
    serializer = LocationSearchQuerySerializer(data=request.query_params)
    if not serializer.is_valid():
        return _error_response(
            "validation_error",
            "Enter at least two characters to search for a location.",
            status.HTTP_400_BAD_REQUEST,
            serializer.errors,
        )

    try:
        matches = build_geocoding_client().geocode(
            serializer.validated_data["q"],
            limit=5,
        )
    except ProviderError as exc:
        return _provider_error_response(exc)

    return Response(
        {
            "results": [
                {
                    "provider_id": match.provider_id,
                    "label": match.label,
                    "lat": match.coordinate.lat,
                    "lng": match.coordinate.lng,
                    "result_type": match.result_type,
                }
                for match in matches
            ]
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def create_trip_analysis(request):
    serializer = TripAnalysisRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return _error_response(
            "validation_error",
            "The request contains invalid fields.",
            status.HTTP_400_BAD_REQUEST,
            serializer.errors,
        )

    trip = TripAnalysisInput(**serializer.validated_data)
    try:
        result = build_analysis_service().analyze(trip)
    except TripAnalysisError as exc:
        return _error_response(
            exc.code, str(exc), exc.status_code, exc.details or None
        )
    except ProviderError as exc:
        return _provider_error_response(exc)

    return Response(result, status=status.HTTP_200_OK)


def _error_response(code, message, response_status, details=None):
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return Response({"error": error}, status=response_status)


def _provider_error_response(exc: ProviderError):
    if isinstance(exc, ProviderRateLimitError):
        details = (
            {"retry_after_seconds": exc.retry_after_seconds}
            if exc.retry_after_seconds is not None
            else None
        )
        return _error_response(
            exc.code,
            str(exc),
            status.HTTP_429_TOO_MANY_REQUESTS,
            details,
        )
    if isinstance(exc, ProviderTimeoutError):
        return _error_response(exc.code, str(exc), status.HTTP_504_GATEWAY_TIMEOUT)
    if isinstance(exc, (ProviderConfigurationError, ProviderAuthenticationError)):
        return _error_response(
            exc.code,
            str(exc),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return _error_response(exc.code, str(exc), status.HTTP_502_BAD_GATEWAY)
