export type RiskLevel =
  | "low"
  | "moderate"
  | "high"
  | "severe"
  | "no_travel"
  | "unknown";

export interface WeatherReading {
  wind_mph: number | null;
  wind_gust_mph: number | null;
  rain_in_per_hr: number | null;
  snow_in_per_hr: number | null;
}

export interface RiskReading {
  level: RiskLevel;
  score: number | null;
  is_complete: boolean;
  condition_levels?: Partial<Record<"wind" | "rain" | "snow", RiskLevel>>;
  drivers?: string[];
}

export interface HourlyForecast {
  time: string;
  weather: WeatherReading;
  risk: RiskReading;
}

export interface Checkpoint {
  sequence: number;
  distance_miles: number;
  location: { lat: number; lng: number };
  elapsed_seconds: number | null;
  eta: string | null;
  forecast_time: string | null;
  weather: WeatherReading;
  risk: RiskReading;
  hourly_forecast: HourlyForecast[];
}

export interface RouteSummary {
  distance_miles: number;
  duration_seconds: number;
  severe_miles: number;
  high_miles: number;
  no_travel_miles: number;
  unknown_miles: number;
  average_risk: number | null;
  contains_no_travel: boolean;
  weather_complete: boolean;
  risk_miles: Record<RiskLevel, number>;
}

export interface RouteOption {
  id: string;
  label: string;
  provider_order: number;
  is_recommended: boolean;
  geometry: {
    type: "LineString";
    coordinates: [number, number][];
  };
  summary: RouteSummary;
  checkpoints: Checkpoint[];
  notices: string[];
}

export interface ResolvedLocation {
  provider_id: string;
  label: string;
  lat: number;
  lng: number;
  result_type: string;
}

export type LocationSuggestion = ResolvedLocation;

export interface TripAnalysis {
  analysis_id: string;
  status: "complete";
  request: TripRequest;
  resolved_locations: {
    origin: ResolvedLocation;
    destination: ResolvedLocation;
  };
  recommendation: {
    status: "recommended" | "no_safe_route" | "insufficient_weather_data";
    route_id: string | null;
    ranked_route_ids: string[];
    reason: string;
  };
  routes: RouteOption[];
  warnings: { code: string; message: string }[];
  forecast_window: {
    start_time: string;
    end_time: string;
    hours: number;
  };
  attribution: {
    routing: string;
    weather: string;
  };
}

export interface TripRequest {
  origin: string;
  destination: string;
  departure_time: string;
  cargo_weight_lb: number;
  checkpoint_interval_miles: 10 | 25 | 50;
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, string[] | string>;
  };
}
