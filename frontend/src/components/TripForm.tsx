import { ArrowDownUp, CalendarClock, Scale, Search } from "lucide-react";
import { useState } from "react";

import type { TripRequest } from "../types";
import { defaultDepartureValue, toApiDateTime } from "../utils";
import { LocationAutocomplete } from "./LocationAutocomplete";

interface TripFormProps {
  isLoading: boolean;
  onSubmit: (request: TripRequest) => void;
}

export function TripForm({ isLoading, onSubmit }: TripFormProps) {
  const [origin, setOrigin] = useState("Lahore, Pakistan");
  const [destination, setDestination] = useState("Karachi, Pakistan");
  const [departure, setDeparture] = useState(defaultDepartureValue);
  const [cargoWeight, setCargoWeight] = useState("35000");
  const [interval, setInterval] = useState<10 | 25 | 50>(25);

  function swapLocations() {
    setOrigin(destination);
    setDestination(origin);
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit({
      origin: origin.trim(),
      destination: destination.trim(),
      departure_time: toApiDateTime(departure),
      cargo_weight_lb: Number(cargoWeight),
      checkpoint_interval_miles: interval,
    });
  }

  return (
    <form className="trip-form" onSubmit={submit}>
      <div className="form-heading">
        <span className="eyebrow">New trip analysis</span>
        <h1>Plan a safer haul</h1>
        <p>Compare truck routes against weather at the time you’ll reach it.</p>
      </div>

      <div className="location-fields">
        <LocationAutocomplete label="Origin" value={origin} onChange={setOrigin} />
        <button
          aria-label="Swap origin and destination"
          className="swap-button"
          onClick={swapLocations}
          type="button"
        >
          <ArrowDownUp size={17} />
        </button>
        <LocationAutocomplete
          label="Destination"
          value={destination}
          onChange={setDestination}
        />
      </div>

      <label className="field">
        <span className="field-label">Departure date & time</span>
        <span className="input-shell">
          <CalendarClock aria-hidden="true" size={18} />
          <input
            type="datetime-local"
            value={departure}
            onChange={(event) => setDeparture(event.target.value)}
            required
          />
        </span>
      </label>

      <label className="field">
        <span className="field-label">Cargo load</span>
        <span className="input-shell input-with-suffix">
          <Scale aria-hidden="true" size={18} />
          <input
            type="number"
            min="0"
            step="500"
            value={cargoWeight}
            onChange={(event) => setCargoWeight(event.target.value)}
            required
          />
          <span>lb</span>
        </span>
      </label>

      <fieldset className="interval-fieldset">
        <legend>Weather checkpoint spacing</legend>
        <div className="segmented-control">
          {([10, 25, 50] as const).map((value) => (
            <label key={value}>
              <input
                type="radio"
                name="checkpoint-interval"
                value={value}
                checked={interval === value}
                onChange={() => setInterval(value)}
              />
              <span>{value} mi</span>
            </label>
          ))}
        </div>
      </fieldset>

      <button className="primary-button" type="submit" disabled={isLoading}>
        {isLoading ? <span className="spinner" aria-hidden="true" /> : <Search size={18} />}
        {isLoading ? "Analyzing routes..." : "Analyze truck routes"}
      </button>
    </form>
  );
}
