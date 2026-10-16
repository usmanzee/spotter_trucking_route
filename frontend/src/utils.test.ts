import { describe, expect, it } from "vitest";

import type { Checkpoint } from "./types";
import { formatDuration, nearestForecast } from "./utils";

describe("formatDuration", () => {
  it("formats route seconds as hours and minutes", () => {
    expect(formatDuration(7_500)).toBe("2 hr 5 min");
  });
});

describe("nearestForecast", () => {
  it("selects the forecast closest to the slider time", () => {
    const checkpoint = {
      hourly_forecast: [
        { time: "2026-10-16T12:00:00Z" },
        { time: "2026-10-16T13:00:00Z" },
      ],
    } as Checkpoint;

    expect(
      nearestForecast(checkpoint, new Date("2026-10-16T12:40:00Z"))?.time,
    ).toBe("2026-10-16T13:00:00Z");
  });
});
