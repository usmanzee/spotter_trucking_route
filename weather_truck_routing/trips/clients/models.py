from dataclasses import dataclass

from trips.services.checkpoints import Coordinate


@dataclass(frozen=True)
class GeocodedLocation:
    provider_id: str
    label: str
    coordinate: Coordinate
    result_type: str


@dataclass(frozen=True)
class RouteSpan:
    offset: int
    length_meters: float
    duration_seconds: float


@dataclass(frozen=True)
class RouteSection:
    section_id: str
    coordinates: tuple[Coordinate, ...]
    length_meters: float
    duration_seconds: float
    spans: tuple[RouteSpan, ...]
    notices: tuple[str, ...] = ()
    has_critical_notice: bool = False


@dataclass(frozen=True)
class ProviderRoute:
    route_id: str
    label: str | None
    sections: tuple[RouteSection, ...]
    notices: tuple[str, ...] = ()
    has_critical_notice: bool = False
