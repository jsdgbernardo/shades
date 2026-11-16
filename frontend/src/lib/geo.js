// Pure geometry helpers. Geometries are arrays of [longitude, latitude] like the API returns.

export const OFF_ROUTE_METERS = 30;
export const WALKING_SPEED_M_PER_MIN = 80;
const EARTH_RADIUS_M = 6_371_000;
const SUN_LABELS = new Set(["sun", "unknown"]);

export function haversineMeters([lon1, lat1], [lon2, lat2]) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

/** Local flat projection in metres around a reference latitude; fine for a few kilometres. */
function toXY([lon, lat], refLat) {
  const metersPerDegLat = 111_320;
  const metersPerDegLon = 111_320 * Math.cos((refLat * Math.PI) / 180);
  return [lon * metersPerDegLon, lat * metersPerDegLat];
}

/**
 * Project a [lon, lat] point onto a route polyline.
 * Returns the distance from the route and how far along the route the closest point is.
 */
export function projectOntoRoute(point, geometry) {
  if (!geometry || geometry.length < 2) return { distanceFromRoute: Infinity, along: 0 };
  const refLat = point[1];
  const p = toXY(point, refLat);
  let best = { distanceFromRoute: Infinity, along: 0 };
  let travelled = 0;
  for (let index = 0; index < geometry.length - 1; index += 1) {
    const a = toXY(geometry[index], refLat);
    const b = toXY(geometry[index + 1], refLat);
    const segX = b[0] - a[0];
    const segY = b[1] - a[1];
    const lengthSquared = segX * segX + segY * segY;
    const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * segX + (p[1] - a[1]) * segY) / lengthSquared));
    const closest = [a[0] + t * segX, a[1] + t * segY];
    const distance = Math.hypot(p[0] - closest[0], p[1] - closest[1]);
    const segmentLength = haversineMeters(geometry[index], geometry[index + 1]);
    if (distance < best.distanceFromRoute) {
      best = { distanceFromRoute: distance, along: travelled + t * segmentLength };
    }
    travelled += segmentLength;
  }
  return best;
}

function polylineLength(geometry) {
  let total = 0;
  for (let index = 0; index < geometry.length - 1; index += 1) total += haversineMeters(geometry[index], geometry[index + 1]);
  return total;
}

/**
 * Figures for the part of the route still ahead (PRD F-13).
 * `along` is metres already walked; sections are in route order.
 */
export function remainingFigures(sections, along = 0) {
  let start = 0;
  let remaining = 0;
  let sun = 0;
  for (const section of sections) {
    const length = polylineLength(section.geometry);
    const end = start + length;
    const ahead = Math.max(0, end - Math.max(start, along));
    remaining += ahead;
    if (SUN_LABELS.has(section.label)) sun += ahead;
    start = end;
  }
  return {
    distance_m: remaining,
    sun_m: sun,
    sun_percent: remaining > 0 ? (sun / remaining) * 100 : 0,
    sun_minutes: sun / WALKING_SPEED_M_PER_MIN,
    minutes: remaining / WALKING_SPEED_M_PER_MIN,
  };
}

export function isOffRoute(distanceFromRoute) {
  return distanceFromRoute > OFF_ROUTE_METERS;
}
