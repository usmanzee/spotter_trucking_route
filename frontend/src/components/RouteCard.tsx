import { Clock3, Route as RouteIcon, ShieldCheck, TriangleAlert } from "lucide-react";

import type { RouteOption } from "../types";
import { formatDuration, formatNumber, RISK_META } from "../utils";

interface RouteCardProps {
  route: RouteOption;
  routeNumber: number;
  isSelected: boolean;
  onSelect: () => void;
}

export function RouteCard({
  route,
  routeNumber,
  isSelected,
  onSelect,
}: RouteCardProps) {
  const hasStop = route.summary.contains_no_travel;
  const visibleRiskLevels = (
    ["moderate", "high", "severe", "no_travel", "unknown"] as const
  ).filter((level) => (route.summary.risk_miles[level] ?? 0) > 0);
  return (
    <button
      className={`route-card ${isSelected ? "selected" : ""}`}
      onClick={onSelect}
      type="button"
      aria-pressed={isSelected}
    >
      <span className="route-card-topline">
        <span className="route-index">0{routeNumber}</span>
        <span className="route-name">{route.label}</span>
        {route.is_recommended && (
          <span className="recommended-badge">
            <ShieldCheck size={13} /> Safest
          </span>
        )}
        {hasStop && (
          <span className="stop-badge">
            <TriangleAlert size={13} /> No travel
          </span>
        )}
      </span>
      <span className="route-metrics">
        <span>
          <RouteIcon size={15} />
          <strong>{formatNumber(route.summary.distance_miles, 0)} mi</strong>
        </span>
        <span>
          <Clock3 size={15} />
          <strong>{formatDuration(route.summary.duration_seconds)}</strong>
        </span>
        <span>
          Avg risk
          <strong>{formatNumber(route.summary.average_risk, 2)}</strong>
        </span>
      </span>
      <span className="risk-mile-row">
        {visibleRiskLevels.length === 0 ? (
          <span className="all-clear">All sampled miles are low risk</span>
        ) : (
          visibleRiskLevels.map((level) => (
            <span key={level}>
              <i style={{ background: RISK_META[level].color }} />
              {RISK_META[level].label} {formatNumber(route.summary.risk_miles[level] ?? 0, 0)} mi
            </span>
          ))
        )}
      </span>
    </button>
  );
}
