import {
  AlertCircle,
  CloudSun,
  MapPinned,
  Navigation,
  Route as RouteIcon,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ApiError, analyzeTrip } from "./api";
import { ForecastControl } from "./components/ForecastControl";
import { RouteCard } from "./components/RouteCard";
import { RouteMap } from "./components/RouteMap";
import { TripForm } from "./components/TripForm";
import type { TripAnalysis, TripRequest } from "./types";

function App() {
  const [analysis, setAnalysis] = useState<TripAnalysis | null>(null);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [forecastHour, setForecastHour] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function handleAnalyze(request: TripRequest) {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setIsLoading(true);
    setError(null);
    try {
      const nextAnalysis = await analyzeTrip(request, controller.signal);
      setAnalysis(nextAnalysis);
      setSelectedRouteId(
        nextAnalysis.recommendation.route_id ?? nextAnalysis.routes[0]?.id ?? null,
      );
      setForecastHour(0);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError(
        caught instanceof ApiError
          ? caught.message
          : "An unexpected error prevented this trip from being analyzed.",
      );
    } finally {
      if (activeRequest.current === controller) {
        setIsLoading(false);
        activeRequest.current = null;
      }
    }
  }

  const selectedRoute =
    analysis?.routes.find((route) => route.id === selectedRouteId) ??
    analysis?.routes[0] ??
    null;
  const visibleWarnings =
    analysis?.warnings.filter(
      (warning) => warning.code !== "fewer_route_alternatives",
    ) ?? [];

  return (
    <div className="app-shell">
      <main id="top" className="main-layout">
        <aside className="planner-panel">
          <TripForm isLoading={isLoading} onSubmit={handleAnalyze} />
          {error && (
            <div className="error-alert" role="alert">
              <AlertCircle size={19} />
              <div>
                <strong>Couldn’t analyze this trip</strong>
                <span>{error}</span>
              </div>
            </div>
          )}
        </aside>

        <section className="results-panel" aria-live="polite">
          {isLoading && !analysis && <LoadingState />}
          {!isLoading && !analysis && <EmptyState />}
          {analysis && selectedRoute && (
            <>
              <div className="results-heading">
                <div>
                  <span className="eyebrow">Analysis complete</span>
                  <h2>
                    {analysis.request.origin}
                    <Navigation size={20} />
                    {analysis.request.destination}
                  </h2>
                </div>
              </div>

              {visibleWarnings.length > 0 && (
                <div className="warning-strip">
                  <TriangleAlert size={17} />
                  <span>{visibleWarnings.map((warning) => warning.message).join(" ")}</span>
                </div>
              )}

              <div className="route-card-grid">
                {analysis.routes.map((route, index) => (
                  <RouteCard
                    key={route.id}
                    route={route}
                    routeNumber={index + 1}
                    isSelected={route.id === selectedRoute.id}
                    onSelect={() => setSelectedRouteId(route.id)}
                  />
                ))}
              </div>

              <ForecastControl
                departureTime={analysis.forecast_window.start_time}
                hour={forecastHour}
                maxHours={analysis.forecast_window.hours}
                onChange={setForecastHour}
              />

              <RouteMap
                analysis={analysis}
                selectedRoute={selectedRoute}
                forecastHour={forecastHour}
                onSelectRoute={setSelectedRouteId}
              />

              <footer className="data-footer">
                <span>{analysis.attribution.routing}</span>
                <span>{analysis.attribution.weather}</span>
              </footer>
            </>
          )}
        </section>
      </main>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-visual" aria-hidden="true">
        <span className="visual-node"><MapPinned size={21} /></span>
        <i />
        <span className="visual-node weather"><CloudSun size={22} /></span>
        <i />
        <span className="visual-node route"><RouteIcon size={22} /></span>
      </div>
      <span className="eyebrow">Weather-aware routing</span>
      <h2>See risk before it’s on the road.</h2>
      <p>Enter a trip to compare truck routes, checkpoint forecasts and arrival-time risk on one map.</p>
      <div className="empty-features">
        <span><strong>01</strong> Truck-ready alternatives</span>
        <span><strong>02</strong> ETA-matched weather</span>
        <span><strong>03</strong> 48-hour corridor outlook</span>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="loading-state">
      <span className="radar" aria-hidden="true"><i /></span>
      <span className="eyebrow">Building your route profile</span>
      <h2>Checking roads against the forecast…</h2>
      <p>Resolving locations, requesting truck routes and matching weather to checkpoint ETAs.</p>
    </div>
  );
}

export default App;
