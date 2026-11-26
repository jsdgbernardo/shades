import { describe, expect, it } from "vitest";
import { pinStatus, pinnedName } from "./pin.js";

describe("choose on map", () => {
  it("names a pinned point after its street, or by its field", () => {
    expect(pinnedName("destination", "Katipunan Avenue")).toBe("Pinned · Katipunan Avenue");
    expect(pinnedName("start")).toBe("Pinned origin");
    expect(pinnedName("destination", null)).toBe("Pinned destination");
  });

  it("describes the spot under the pin", () => {
    expect(pinStatus({ street: { name: "Katipunan Avenue", named: true } }))
      .toEqual({ text: "Near Katipunan Avenue", canSet: true, streetName: "Katipunan Avenue" });
    expect(pinStatus({ street: { name: "Footway", named: false } }))
      .toEqual({ text: "Near a footpath", canSet: true, streetName: null });
    expect(pinStatus({ street: { name: "Service", named: false } }).text).toBe("Near a service road");
    expect(pinStatus({ street: { name: "Residential", named: false } }).text).toBe("Near an unnamed street");
    expect(pinStatus({ street: { name: "Primary link", named: false } }).text).toBe("Near an unnamed road");
    expect(pinStatus({ street: null })).toEqual({ text: "No street nearby", canSet: true, streetName: null });
  });

  it("refuses points outside the study area and waits politely while looking up", () => {
    expect(pinStatus({ outside: true }).canSet).toBe(false);
    expect(pinStatus({ outside: true }).text).toBe("Outside Metro Manila");
    expect(pinStatus({ loading: true }).text).toBe("Finding the street…");
    expect(pinStatus(null).canSet).toBe(true);
  });
});
