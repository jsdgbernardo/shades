import { describe as group, expect, it } from "vitest";
import { addSample, describe, seconds, timingEnabled } from "./timing.js";

group("field-test timing", () => {
  it("turns on only with ?timing", () => {
    expect(timingEnabled("?timing")).toBe(true);
    expect(timingEnabled("?simulate-location&timing")).toBe(true);
    expect(timingEnabled("?simulate-location")).toBe(false);
    expect(timingEnabled("")).toBe(false);
  });

  it("keeps the last, the slowest and how many went over the limit", () => {
    let stat = addSample(null, 1200, 10_000);
    stat = addSample(stat, 11_500, 10_000);
    stat = addSample(stat, 800, 10_000);
    expect(stat).toEqual({ last: 800, max: 11_500, count: 3, over: 1 });
    expect(addSample(null, -5, 2000).last).toBe(0);
  });

  it("writes a readable line", () => {
    expect(seconds(1420)).toBe("1.42 s");
    expect(seconds(12_340)).toBe("12.3 s");
    expect(describe("Routes", { last: 1420, max: 2100, count: 3, over: 0 }, 10_000)).toBe("Routes 1.42 s (max 2.10 s, 0 of 3 over 10.0 s)");
    expect(describe("Routes", null, 10_000)).toBe("Routes –");
  });
});
