import type { Checkpoint, RiskLevel, RouteOption } from "./types";
import { nearestForecast } from "./utils";

export type HeatPoint = [lat: number, lng: number, intensity: number];

const RISK_INTENSITY: Record<RiskLevel, number | null> = {
  low: 0.18,
  moderate: 0.4,
  high: 0.6,
  severe: 0.82,
  no_travel: 1,
  unknown: null,
};

function checkpointIntensity(
  checkpoint: Checkpoint,
  targetTime: Date,
): number | null {
  const forecast = nearestForecast(checkpoint, targetTime);
  return RISK_INTENSITY[forecast?.risk.level ?? "unknown"];
}

export function buildRouteHeatPoints(
  route: RouteOption,
  targetTime: Date,
  maxGeometryPoints = 240,
): HeatPoint[] {
  const checkpoints = route.checkpoints
    .map((checkpoint) => ({
      checkpoint,
      intensity: checkpointIntensity(checkpoint, targetTime),
    }))
    .filter(
      (item): item is { checkpoint: Checkpoint; intensity: number } =>
        item.intensity !== null,
    );
  if (checkpoints.length === 0) return [];

  const geometry = route.geometry.coordinates;
  const step = Math.max(1, Math.ceil(geometry.length / maxGeometryPoints));
  const sampleIndexes = new Set<number>();
  for (let index = 0; index < geometry.length; index += step) {
    sampleIndexes.add(index);
  }
  if (geometry.length > 0) sampleIndexes.add(geometry.length - 1);

  const routePoints = [...sampleIndexes].map((index): HeatPoint => {
    const [lng, lat] = geometry[index];
    const nearest = checkpoints.reduce((current, candidate) => {
      const currentDistance =
        (current.checkpoint.location.lat - lat) ** 2 +
        (current.checkpoint.location.lng - lng) ** 2;
      const candidateDistance =
        (candidate.checkpoint.location.lat - lat) ** 2 +
        (candidate.checkpoint.location.lng - lng) ** 2;
      return candidateDistance < currentDistance ? candidate : current;
    });
    return [lat, lng, nearest.intensity];
  });

  const exactCheckpointPoints = checkpoints.map(
    ({ checkpoint, intensity }): HeatPoint => [
      checkpoint.location.lat,
      checkpoint.location.lng,
      intensity,
    ],
  );
  return [...routePoints, ...exactCheckpointPoints];
}
