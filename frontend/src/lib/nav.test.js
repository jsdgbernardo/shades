import { describe, expect, it } from "vitest";
import { ARRIVE_METERS, arrivalSummary, bearing, buildManeuvers, hasArrived, headingAt, maneuverText, nextManeuver, turnAngle, turnKind } from "./nav.js";

describe("arrival", () => {
  it("counts as arrived within 15 m of the end", () => {
    expect(ARRIVE_METERS).toBe(15);
    expect(hasArrived(0)).toBe(true);
    expect(hasArrived(15)).toBe(true);
    expect(hasArrived(16)).toBe(false);
    expect(hasArrived(Number.NaN)).toBe(false);
  });

  it("summarises the walk", () => {
    const route = { distance_m: 526, exposure: { sun_percent: 12, sun_minutes: 0.8 } };
    const summary = arrivalSummary(route, 0, 7 * 60_000);
    expect(summary).toEqual({ elapsedMinutes: 7, distance_m: 526, sun_percent: 12, sun_minutes: 0.8 });
  });
});

const LAT = 14.64;
const metersLon = (m) => m / (111_320 * Math.cos((LAT * Math.PI) / 180));
const metersLat = (m) => m / 111_320;
const at = (east, north) => [121.07 + metersLon(east), LAT + metersLat(north)];

describe("bearings", () => {
  it("measures compass bearings", () => {
    expect(bearing(at(0, 0), at(0, 100))).toBeCloseTo(0, 0);
    expect(bearing(at(0, 0), at(100, 0))).toBeCloseTo(90, 0);
    expect(bearing(at(0, 0), at(0, -100))).toBeCloseTo(180, 0);
    expect(bearing(at(0, 0), at(-100, 0))).toBeCloseTo(270, 0);
  });

  it("gives signed turn angles, positive to the right", () => {
    expect(turnAngle(0, 90)).toBe(90);
    expect(turnAngle(90, 0)).toBe(-90);
    expect(turnAngle(350, 10)).toBe(20);
    expect(turnKind(90)).toBe("right");
    expect(turnKind(-35)).toBe("slight-left");
    expect(turnKind(-170)).toBe("uturn");
  });
});

describe("manoeuvres", () => {
  // North 100 m, then east 80 m (a right turn), then north 60 m (a left turn).
  const geometry = [at(0, 0), at(0, 50), at(0, 100), at(40, 100), at(80, 100), at(80, 160)];
  const edges = [
    { name: "College Lane" }, { name: "College Lane" },
    { name: "University Road" }, { name: "University Road" },
    { name: "Footway" },
  ];
  const maneuvers = buildManeuvers(geometry, edges);

  it("finds each real turn with its direction and the street turned onto", () => {
    expect(maneuvers.map((turn) => turn.kind)).toEqual(["right", "left"]);
    expect(maneuvers[0].name).toBe("University Road");
    expect(maneuvers[0].along).toBeCloseTo(100, 0);
    expect(maneuvers[1].along).toBeCloseTo(180, 0);
  });

  it("leaves out unnamed paths instead of saying 'onto Footway'", () => {
    const unnamed = edges.map((edge) => ({ ...edge, named: edge.name !== "Footway" }));
    const turns = buildManeuvers(geometry, unnamed);
    expect(turns[0].name).toBe("University Road");
    expect(turns[1].name).toBeNull();
  });

  it("ignores small kinks along a straight street", () => {
    const wobbly = [at(0, 0), at(1, 30), at(0, 60), at(1, 90)];
    expect(buildManeuvers(wobbly)).toEqual([]);
  });

  it("reports distance to the next turn, then arrival", () => {
    const first = nextManeuver(maneuvers, 30, 240);
    expect(first.kind).toBe("right");
    expect(first.distance).toBeCloseTo(70, 0);
    expect(nextManeuver(maneuvers, 150, 240).kind).toBe("left");
    const last = nextManeuver(maneuvers, 200, 240);
    expect(last.kind).toBe("arrive");
    expect(last.distance).toBeCloseTo(40, 5);
    expect(maneuverText(last)).toBe("Arrive at destination");
  });

  it("gives the travel direction for a course-up map", () => {
    expect(headingAt(geometry, 20)).toBeCloseTo(0, 0);
    expect(headingAt(geometry, 130)).toBeCloseTo(90, 0);
  });
});
