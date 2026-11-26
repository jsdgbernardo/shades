// Turn-by-turn helpers for the live walk. Geometries are [lon, lat] arrays like the API returns.
import { haversineMeters } from "./geo.js";

const LOOK_M = 12; // smooth bearings over this distance so tiny OSM kinks are not "turns"
const MIN_TURN_DEG = 30;
const MERGE_M = 15; // turns closer than this are one manoeuvre

/** Compass bearing from a to b in degrees, clockwise from north (0–360). */
export function bearing([lon1, lat1], [lon2, lat2]) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const y = Math.sin(toRad(lon2 - lon1)) * Math.cos(toRad(lat2));
  const x = Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) - Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lon2 - lon1));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

/** Signed smallest difference b − a in degrees, in (−180, 180]. Positive means a right turn. */
export function turnAngle(a, b) {
  const diff = ((b - a + 540) % 360) - 180;
  return diff === -180 ? 180 : diff;
}

/** Cumulative distance (m) at each vertex. */
export function cumulative(geometry) {
  const out = [0];
  for (let index = 1; index < geometry.length; index += 1) out.push(out[index - 1] + haversineMeters(geometry[index - 1], geometry[index]));
  return out;
}

/** Point on the route `along` metres from the start (clamped to the ends). */
export function pointAt(geometry, along, distances = cumulative(geometry)) {
  if (along <= 0) return geometry[0];
  const total = distances[distances.length - 1];
  if (along >= total) return geometry[geometry.length - 1];
  let index = 1;
  while (distances[index] < along) index += 1;
  const span = distances[index] - distances[index - 1] || 1;
  const t = (along - distances[index - 1]) / span;
  const [a, b] = [geometry[index - 1], geometry[index]];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/** Direction of travel along the route at `along` metres, for course-up map rotation. */
export function headingAt(geometry, along, distances = cumulative(geometry)) {
  const total = distances[distances.length - 1];
  const from = Math.min(along, Math.max(0, total - LOOK_M));
  return bearing(pointAt(geometry, from, distances), pointAt(geometry, from + LOOK_M, distances));
}

export function turnKind(angle) {
  const size = Math.abs(angle);
  const side = angle > 0 ? "right" : "left";
  if (size >= 150) return "uturn";
  if (size >= 110) return `sharp-${side}`;
  if (size >= 50) return side;
  return `slight-${side}`;
}

/**
 * Manoeuvres along the route: [{ along, angle, kind, name }].
 * `edges[i]` describes the segment from geometry[i] to geometry[i + 1]; `name` is the street
 * the walker turns onto.
 */
export function buildManeuvers(geometry, edges = []) {
  if (!geometry || geometry.length < 3) return [];
  const distances = cumulative(geometry);
  const total = distances[distances.length - 1];
  const found = [];
  for (let index = 1; index < geometry.length - 1; index += 1) {
    const at = distances[index];
    if (at < LOOK_M / 2 || total - at < LOOK_M / 2) continue;
    const inBearing = bearing(pointAt(geometry, at - LOOK_M, distances), geometry[index]);
    const outBearing = bearing(geometry[index], pointAt(geometry, at + LOOK_M, distances));
    const angle = turnAngle(inBearing, outBearing);
    if (Math.abs(angle) < MIN_TURN_DEG) continue;
    // Only real street names are announced; an unnamed path ("Footway") is left out, like nav apps do.
    const edge = edges[index];
    const name = edge && edge.named !== false ? edge.name ?? null : null;
    const turn = { along: at, angle, kind: turnKind(angle), name };
    const previous = found[found.length - 1];
    if (previous && at - previous.along < MERGE_M) {
      if (Math.abs(angle) > Math.abs(previous.angle)) found[found.length - 1] = turn;
    } else {
      found.push(turn);
    }
  }
  return found;
}

/** The next manoeuvre ahead of `along`, or arrival when none is left. */
export function nextManeuver(maneuvers, along, total) {
  const next = maneuvers.find((turn) => turn.along > along + 2);
  if (!next) return { kind: "arrive", distance: Math.max(0, total - along), name: null };
  return { ...next, distance: next.along - along };
}

/**
 * The route edge (API `edges[i]`, the stretch from geometry point i to i + 1) at `along` metres
 * from the start, given the cumulative `distances` of the geometry. Null without edges.
 */
export function edgeAt(edges, distances, along) {
  if (!edges?.length) return null;
  let index = 0;
  while (index < edges.length - 1 && distances[index + 1] <= along) index += 1;
  return edges[index];
}

/** Within this distance of the end of the route, the walk counts as arrived. */
export const ARRIVE_METERS = 30;

/**
 * Arrived when the distance left along the route is within ARRIVE_METERS while on the route, or
 * when the end is that close in a straight line (cutting a corner, or reaching it from another side).
 */
export function hasArrived(distanceLeft, distanceToEnd = Number.POSITIVE_INFINITY, onRoute = true) {
  const near = (meters) => Number.isFinite(meters) && meters <= ARRIVE_METERS;
  return (onRoute && near(distanceLeft)) || near(distanceToEnd);
}

/** Summary shown when the walk ends at the destination. */
export function arrivalSummary(route, startedAt, endedAt = Date.now()) {
  return {
    elapsedMinutes: Math.max(0, (endedAt - startedAt) / 60_000),
    distance_m: route.distance_m,
    sun_percent: route.exposure.sun_percent,
    sun_minutes: route.exposure.sun_minutes,
  };
}

export function maneuverText(maneuver) {
  const labels = {
    arrive: "Arrive at destination",
    uturn: "Turn around",
    left: "Turn left",
    right: "Turn right",
    "slight-left": "Bear left",
    "slight-right": "Bear right",
    "sharp-left": "Sharp left",
    "sharp-right": "Sharp right",
  };
  return labels[maneuver.kind] ?? "Continue";
}
