import { describe, it, expect, vi } from "vitest";
import { api } from "./client";

describe("api client", () => {
  it("throws ApiError with detail on 502", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "binance unreachable" }), { status: 502 })),
    );
    await expect(api.getIntervals()).rejects.toMatchObject({ status: 502, detail: "binance unreachable" });
  });

  it("returns parsed json on 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ intervals: ["1d"] }), { status: 200 })),
    );
    expect(await api.getIntervals()).toEqual({ intervals: ["1d"] });
  });

  it("posts JSON bodies with content-type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ symbols: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.calculateDca({ symbol: "BTCUSDT", amount: 1, day: 1, start_date: "2024-01-01", end_date: null });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/dca/calculate");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
  });
});
