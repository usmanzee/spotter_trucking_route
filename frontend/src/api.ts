import type {
  ApiErrorBody,
  LocationSuggestion,
  TripAnalysis,
  TripRequest,
} from "./types";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1"
).replace(/\/$/, "");

export class ApiError extends Error {
  readonly code: string;
  readonly details?: Record<string, string[] | string>;

  constructor(
    message: string,
    code = "request_failed",
    details?: Record<string, string[] | string>,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
  }
}

export async function searchLocations(
  query: string,
  signal?: AbortSignal,
): Promise<LocationSuggestion[]> {
  let response: Response;
  try {
    const params = new URLSearchParams({ q: query });
    response = await fetch(`${API_BASE_URL}/locations/search/?${params}`, {
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(
      "Location suggestions are temporarily unavailable.",
      "network_error",
    );
  }

  const payload = (await response.json().catch(() => ({}))) as
    | { results: LocationSuggestion[] }
    | ApiErrorBody;
  if (!response.ok) {
    const error = (payload as ApiErrorBody).error;
    throw new ApiError(
      error?.message ?? "Locations could not be searched.",
      error?.code,
      error?.details,
    );
  }
  return (payload as { results: LocationSuggestion[] }).results;
}

export async function analyzeTrip(
  request: TripRequest,
  signal?: AbortSignal,
): Promise<TripAnalysis> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/trip-analyses/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(
      "The routing service could not be reached. Confirm the Django server is running.",
      "network_error",
    );
  }

  const payload = (await response.json().catch(() => ({}))) as
    | TripAnalysis
    | ApiErrorBody;
  if (!response.ok) {
    const error = (payload as ApiErrorBody).error;
    throw new ApiError(
      error?.message ?? "The trip could not be analyzed.",
      error?.code,
      error?.details,
    );
  }
  return payload as TripAnalysis;
}
