from django.urls import path

from .views import create_trip_analysis, health_check, search_locations

app_name = "trips"

urlpatterns = [
    path("health/", health_check, name="health"),
    path("locations/search/", search_locations, name="location-search"),
    path("trip-analyses/", create_trip_analysis, name="trip-analysis-create"),
]
