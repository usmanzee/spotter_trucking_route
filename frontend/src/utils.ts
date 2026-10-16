import type {
  Checkpoint,
  HourlyForecast,
  RiskLevel,
  WeatherReading,
} from "./types";

export const RISK_META: Record<
  RiskLevel,
  { label: string; color: string; shortLabel: string }
> = {
  low: { label: "Low", shortLabel: "Low", color: "#21a179" },
  moderate: { label: "Moderate", shortLabel: "Mod", color: "#e4a11b" },
  high: { label: "High", shortLabel: "High", color: "#ef7b45" },
  severe: { label: "Severe", shortLabel: "Sev", color: "#dd4a5f" },
  no_travel: { label: "No travel", shortLabel: "Stop", color: "#7a2436" },
  unknown: { label: "Unknown", shortLabel: "N/A", color: "#7d8b91" },
};

export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3_600);
  const minutes = Math.round((seconds % 3_600) / 60);
  if (minutes === 60) return `${hours + 1} hr`;
  return `${hours} hr ${minutes} min`;
}

export function formatDateTime(value: string | null): string {
  if (!value) return "Unavailable";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(value));
}

export function formatNumber(value: number | null, digits = 1): string {
  return value === null ? "-" : value.toFixed(digits);
}

export function defaultDepartureValue(): string {
  const date = new Date(Date.now() + 60 * 60 * 1_000);
  date.setMinutes(Math.ceil(date.getMinutes() / 15) * 15, 0, 0);
  const localOffset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - localOffset).toISOString().slice(0, 16);
}

export function toApiDateTime(localValue: string): string {
  return new Date(localValue).toISOString();
}

export function nearestForecast(
  checkpoint: Checkpoint,
  targetTime: Date,
): HourlyForecast | null {
  if (!checkpoint.hourly_forecast.length) return null;
  return checkpoint.hourly_forecast.reduce((nearest, forecast) => {
    const nearestDelta = Math.abs(
      new Date(nearest.time).getTime() - targetTime.getTime(),
    );
    const candidateDelta = Math.abs(
      new Date(forecast.time).getTime() - targetTime.getTime(),
    );
    return candidateDelta < nearestDelta ? forecast : nearest;
  });
}

export function primaryWeatherLabel(weather: WeatherReading): string {
  const values = [
    weather.wind_mph === null ? null : `${weather.wind_mph.toFixed(0)} mph wind`,
    weather.rain_in_per_hr && weather.rain_in_per_hr > 0
      ? `${weather.rain_in_per_hr.toFixed(2)} in/hr rain`
      : null,
    weather.snow_in_per_hr && weather.snow_in_per_hr > 0
      ? `${weather.snow_in_per_hr.toFixed(2)} in/hr snow`
      : null,
  ].filter(Boolean);
  return values.join(" · ") || "Weather unavailable";
}
