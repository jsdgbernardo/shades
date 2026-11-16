import { describe, expect, it } from "vitest";
import { toInputValue, toOffsetIso } from "./time.js";

describe("travel time helpers", () => {
  it("uses local time, not UTC, for the default input value", () => {
    const date = new Date(2026, 9, 15, 9, 5);
    expect(toInputValue(date)).toBe("2026-10-15T09:05");
  });

  it("adds the device UTC offset so the API reads the intended local time", () => {
    const iso = toOffsetIso("2026-10-15T09:05");
    expect(iso.startsWith("2026-10-15T09:05:00")).toBe(true);
    expect(new Date(iso).getTime()).toBe(new Date(2026, 9, 15, 9, 5).getTime());
  });

  it("rejects an empty value", () => {
    expect(toOffsetIso("")).toBeNull();
  });
});
