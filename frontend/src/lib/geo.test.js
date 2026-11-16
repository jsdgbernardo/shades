import { describe, expect, it } from "vitest";
import { OFF_ROUTE_METERS, haversineMeters, isOffRoute, projectOntoRoute, remainingFigures } from "./geo.js";

// A straight east-west route about 200 m long near ADMU, in [lon, lat].
const LAT = 14.64;
const metersToLon = (meters) => meters / (111_320 * Math.cos((LAT * Math.PI) / 180));
const at = (meters) => [121.07 + metersToLon(meters), LAT];
const north = ([lon, lat], meters) => [lon, lat + meters / 111_320];

const sections = [
  { label: "sun", geometry: [at(0), at(50)] },
  { label: "shaded", geometry: [at(50), at(120)] },
  { label: "unknown", geometry: [at(120), at(150)] },
  { label: "covered", geometry: [at(150), at(200)] },
];
const geometry = [at(0), at(50), at(120), at(150), at(200)];

describe("projectOntoRoute", () => {
  it("measures distance along and away from the route", () => {
    const result = projectOntoRoute(north(at(80), 12), geometry);
    expect(result.along).toBeCloseTo(80, 0);
    expect(result.distanceFromRoute).toBeCloseTo(12, 0);
  });

  it("clamps to the route ends", () => {
    expect(projectOntoRoute(at(-40), geometry).along).toBeCloseTo(0, 5);
    expect(projectOntoRoute(at(260), geometry).along).toBeCloseTo(haversineMeters(at(0), at(200)), 0);
  });
});

describe("remainingFigures", () => {
  it("covers the full route before the walk starts", () => {
    const result = remainingFigures(sections, 0);
    expect(result.distance_m).toBeCloseTo(200, 0);
    // sun (50) + unknown (30) count as direct sun; shaded and covered do not.
    expect(result.sun_m).toBeCloseTo(80, 0);
    expect(result.sun_percent).toBeCloseTo(40, 0);
    expect(result.sun_minutes).toBeCloseTo(1, 1);
  });

  it("matches a hand calculation part-way along", () => {
    // At 100 m: 20 m shaded + 30 m unknown + 50 m covered left.
    const result = remainingFigures(sections, 100);
    expect(result.distance_m).toBeCloseTo(100, 0);
    expect(result.sun_m).toBeCloseTo(30, 0);
    expect(result.sun_percent).toBeCloseTo(30, 0);
    expect(result.sun_minutes).toBeCloseTo(30 / 80, 2);
  });

  it("is zero at the end of the route", () => {
    const result = remainingFigures(sections, 500);
    expect(result.distance_m).toBe(0);
    expect(result.sun_percent).toBe(0);
  });
});

describe("isOffRoute", () => {
  it("uses the 30 m threshold", () => {
    expect(OFF_ROUTE_METERS).toBe(30);
    expect(isOffRoute(projectOntoRoute(north(at(100), 10), geometry).distanceFromRoute)).toBe(false);
    expect(isOffRoute(projectOntoRoute(north(at(100), 50), geometry).distanceFromRoute)).toBe(true);
  });
});
