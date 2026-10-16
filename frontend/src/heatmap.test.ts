import { describe, expect, it } from "vitest";

import { buildRouteHeatPoints } from "./heatmap";
import type { RouteOption } from "./types";

describe("buildRouteHeatPoints", () => {
  it("converts checkpoint risk into heat intensity along the route", () => {
    const hourly = (level: "low" | "no_travel", score: number) => [
      {
        time: "2026-10-16T12:00:00Z",
        weather: {
          wind_mph: 10,
          wind_gust_mph: 12,
          rain_in_per_hr: 0,
          snow_in_per_hr: 0,
        },
        risk: { level, score, is_complete: true },
      },
    ];
    const route = {
      geometry: {
        type: "LineString",
        coordinates: [[-87, 41], [-86, 41.5], [-85, 42]],
      },
      checkpoints: [
        {
          location: { lat: 41, lng: -87 },
          hourly_forecast: hourly("low", 0),
        },
        {
          location: { lat: 42, lng: -85 },
          hourly_forecast: hourly("no_travel", 4),
        },
      ],
    } as RouteOption;

    const points = buildRouteHeatPoints(
      route,
      new Date("2026-10-16T12:00:00Z"),
    );

    expect(points.length).toBeGreaterThan(route.geometry.coordinates.length);
    expect(points.some((point) => point[2] === 0.18)).toBe(true);
    expect(points.some((point) => point[2] === 1)).toBe(true);
  });
});
