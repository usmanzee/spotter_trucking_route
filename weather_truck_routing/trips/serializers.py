import math
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers


class LocationSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(
        min_length=2,
        max_length=200,
        trim_whitespace=True,
    )


class TripAnalysisRequestSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=200, trim_whitespace=True)
    destination = serializers.CharField(max_length=200, trim_whitespace=True)
    departure_time = serializers.DateTimeField()
    cargo_weight_lb = serializers.FloatField(min_value=0)
    checkpoint_interval_miles = serializers.ChoiceField(
        choices=(10, 25, 50),
    )

    def validate_departure_time(self, value):
        now = timezone.now()
        if value < now - timedelta(minutes=5):
            raise serializers.ValidationError("Departure time cannot be in the past.")
        if value > now + timedelta(days=14):
            raise serializers.ValidationError(
                "Departure time must be within the next 14 days."
            )
        return value

    def validate_cargo_weight_lb(self, value):
        if not math.isfinite(value):
            raise serializers.ValidationError("Cargo weight must be a finite number.")
        return value

    def validate(self, attributes):
        if attributes["origin"].casefold() == attributes["destination"].casefold():
            raise serializers.ValidationError(
                {"destination": "Origin and destination must be different."}
            )
        return attributes
