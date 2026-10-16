import { CloudSun, FastForward } from "lucide-react";

import { RISK_META, formatDateTime } from "../utils";

interface ForecastControlProps {
  departureTime: string;
  hour: number;
  maxHours: number;
  onChange: (hour: number) => void;
}

export function ForecastControl({
  departureTime,
  hour,
  maxHours,
  onChange,
}: ForecastControlProps) {
  const target = new Date(new Date(departureTime).getTime() + hour * 3_600_000);
  return (
    <section className="forecast-control" aria-label="Weather forecast time">
      <div className="forecast-title-row">
        <span className="forecast-icon"><CloudSun size={20} /></span>
        <div>
          <span className="eyebrow">Corridor weather outlook</span>
          <strong>+{hour} hours · {formatDateTime(target.toISOString())}</strong>
        </div>
        <span className="forecast-window"><FastForward size={14} /> 0–{maxHours} hr</span>
      </div>
      <div className="slider-row">
        <span>Now</span>
        <input
          aria-label="Forecast hour"
          type="range"
          min="0"
          max={maxHours}
          step="1"
          value={hour}
          onChange={(event) => onChange(Number(event.target.value))}
          style={{ "--slider-progress": `${(hour / maxHours) * 100}%` } as React.CSSProperties}
        />
        <span>+{maxHours}h</span>
      </div>
      <div className="risk-legend" aria-label="Weather risk legend">
        {(["low", "moderate", "high", "severe", "no_travel", "unknown"] as const).map(
          (level) => (
            <span key={level}>
              <i style={{ background: RISK_META[level].color }} />
              {RISK_META[level].label}
            </span>
          ),
        )}
      </div>
    </section>
  );
}
