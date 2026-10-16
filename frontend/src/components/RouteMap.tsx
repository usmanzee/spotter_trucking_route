import { useEffect, useMemo } from "react";
import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import L, { type LatLngExpression } from "leaflet";

import type { RouteOption, TripAnalysis } from "../types";
import {
  formatDateTime,
  formatNumber,
  nearestForecast,
  primaryWeatherLabel,
  RISK_META,
} from "../utils";
import { WeatherHeatLayer } from "./WeatherHeatLayer";

const ROUTE_COLORS = ["#056b79", "#71838a", "#9a6f50"];

interface RouteMapProps {
  analysis: TripAnalysis;
  selectedRoute: RouteOption;
  forecastHour: number;
  onSelectRoute: (routeId: string) => void;
}

function FitRouteBounds({ routes }: { routes: RouteOption[] }) {
  const map = useMap();
  const signature = routes.map((route) => route.id).join("|");
  useEffect(() => {
    const points = routes.flatMap((route) =>
      route.geometry.coordinates.map(([lng, lat]) => [lat, lng] as LatLngExpression),
    );
    if (points.length > 1) {
      map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 10 });
    }
  }, [map, routes, signature]);
  return null;
}

export function RouteMap({
  analysis,
  selectedRoute,
  forecastHour,
  onSelectRoute,
}: RouteMapProps) {
  const targetTime = useMemo(
    () =>
      new Date(
        new Date(analysis.forecast_window.start_time).getTime() +
          forecastHour * 3_600_000,
      ),
    [analysis.forecast_window.start_time, forecastHour],
  );
  const orderedRoutes = [
    ...analysis.routes.filter((route) => route.id !== selectedRoute.id),
    selectedRoute,
  ];

  return (
    <div className="map-shell">
      <MapContainer
        center={[39.5, -98.35]}
        zoom={4}
        scrollWheelZoom
        className="route-map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitRouteBounds routes={analysis.routes} />
        <WeatherHeatLayer route={selectedRoute} targetTime={targetTime} />

        {orderedRoutes.map((route) => {
          const selected = route.id === selectedRoute.id;
          const color = route.is_recommended
            ? "#e24d68"
            : ROUTE_COLORS[route.provider_order % ROUTE_COLORS.length];
          const positions = route.geometry.coordinates.map(
            ([lng, lat]) => [lat, lng] as LatLngExpression,
          );
          return (
            <Polyline
              key={route.id}
              positions={positions}
              pathOptions={{
                color,
                weight: selected ? 6 : 4,
                opacity: selected ? 0.95 : 0.48,
                dashArray: selected ? undefined : "8 8",
              }}
              eventHandlers={{ click: () => onSelectRoute(route.id) }}
            >
              <Tooltip sticky>{route.label}</Tooltip>
            </Polyline>
          );
        })}

        {selectedRoute.checkpoints.map((checkpoint) => {
          const forecast = nearestForecast(checkpoint, targetTime);
          const risk = forecast?.risk.level ?? "unknown";
          const weather = forecast?.weather ?? checkpoint.weather;
          return (
            <CircleMarker
              key={checkpoint.sequence}
              center={[checkpoint.location.lat, checkpoint.location.lng]}
              radius={risk === "no_travel" ? 15 : 12}
              pathOptions={{
                color: "#ffffff",
                weight: 2,
                fillColor: RISK_META[risk].color,
                fillOpacity: 0.72,
                opacity: 0.95,
              }}
            >
              <Tooltip direction="top" offset={[0, -8]}>
                Mile {formatNumber(checkpoint.distance_miles, 0)} · {RISK_META[risk].label}
              </Tooltip>
              <Popup>
                <div className="map-popup">
                  <span className="popup-risk" style={{ color: RISK_META[risk].color }}>
                    {RISK_META[risk].label} risk
                  </span>
                  <strong>Checkpoint {checkpoint.sequence + 1} · mile {formatNumber(checkpoint.distance_miles, 0)}</strong>
                  <span>{primaryWeatherLabel(weather)}</span>
                  <small>Forecast: {formatDateTime(forecast?.time ?? null)}</small>
                  <hr />
                  <small>Truck ETA: {formatDateTime(checkpoint.eta)}</small>
                  <small>ETA risk: {RISK_META[checkpoint.risk.level].label}</small>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}

        <CircleMarker
          center={[
            analysis.resolved_locations.origin.lat,
            analysis.resolved_locations.origin.lng,
          ]}
          radius={7}
          pathOptions={{ color: "#003f4a", fillColor: "#ffffff", fillOpacity: 1, weight: 4 }}
        >
          <Tooltip permanent direction="top">Origin</Tooltip>
        </CircleMarker>
        <CircleMarker
          center={[
            analysis.resolved_locations.destination.lat,
            analysis.resolved_locations.destination.lng,
          ]}
          radius={7}
          pathOptions={{ color: "#e24d68", fillColor: "#ffffff", fillOpacity: 1, weight: 4 }}
        >
          <Tooltip permanent direction="top">Destination</Tooltip>
        </CircleMarker>
      </MapContainer>
    </div>
  );
}
