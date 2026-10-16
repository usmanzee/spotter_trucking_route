import L from "leaflet";
import "leaflet.heat";
import { useEffect, useMemo } from "react";
import { useMap } from "react-leaflet";

import { buildRouteHeatPoints } from "../heatmap";
import type { RouteOption } from "../types";

interface WeatherHeatLayerProps {
  route: RouteOption;
  targetTime: Date;
}

export function WeatherHeatLayer({ route, targetTime }: WeatherHeatLayerProps) {
  const map = useMap();
  const points = useMemo(
    () => buildRouteHeatPoints(route, targetTime),
    [route, targetTime],
  );

  useEffect(() => {
    if (points.length === 0) return;
    const paneName = "weather-heatmap";
    const pane = map.getPane(paneName) ?? map.createPane(paneName);
    pane.style.zIndex = "350";
    pane.style.pointerEvents = "none";
    const heatOptions = {
      pane: paneName,
      radius: 34,
      blur: 27,
      minOpacity: 0.28,
      max: 1,
      gradient: {
        0: "#21a179",
        0.32: "#21a179",
        0.4: "#e4a11b",
        0.6: "#ef7b45",
        0.82: "#dd4a5f",
        1: "#7a2436",
      },
    } as L.HeatMapOptions & L.LayerOptions;
    const layer = L.heatLayer(points, heatOptions).addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, points]);

  return null;
}
