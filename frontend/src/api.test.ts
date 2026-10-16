import { afterEach, describe, expect, it, vi } from "vitest";

import { searchLocations } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("searchLocations", () => {
  it("requests encoded suggestions from the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          results: [
            {
              provider_id: "mock-lahore",
              label: "Lahore, Punjab, Pakistan",
              lat: 31.52,
              lng: 74.36,
              result_type: "city",
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const results = await searchLocations("Lahore, Pakistan");

    expect(results[0].provider_id).toBe("mock-lahore");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("locations/search/?q=Lahore%2C+Pakistan"),
      { signal: undefined },
    );
  });
});
