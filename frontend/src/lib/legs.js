// Walk, train, walk trips (PRD F-16 to F-19): the parts of a train option during a live walk.
// Leg 0 is the walk to the boarding station, leg 1 the ride, leg 2 the walk from the alighting station.

/** Within this distance of the alighting station, the ride is over and the second walk starts. */
export const RIDE_END_METERS = 200;

export function isTrain(route) {
  return route?.kind === "train" && Array.isArray(route.legs) && route.legs.length === 3;
}

/** The walk being guided: the whole route for a walking route; for a train option, leg 0 or 2 (null during the ride). */
export function walkingPart(route, leg = 0) {
  if (!isTrain(route)) return route ?? null;
  if (leg === 1) return null;
  const part = route.legs[leg === 2 ? 2 : 0];
  return { geometry: part.geometry, exposure: part.exposure, edges: part.edges, distance_m: part.distance_m };
}

/** Metres walked so far along the trip's walking parts, in the order of the trip's `edges`. */
export function walkedSoFar(route, leg = 0, along = 0) {
  if (!isTrain(route)) return along;
  const first = route.legs[0].distance_m;
  if (leg === 0) return Math.min(along, first);
  return leg === 1 ? first : first + along;
}

/**
 * The ride as steps to read on the way: ride a line, change at a station, get off. Ride times are
 * not shown on their own (F-17); only the trip's total is.
 */
export function rideSteps(ride) {
  const steps = [];
  ride.segments.forEach((segment, index) => {
    steps.push(`${index === 0 ? "Ride" : "Then ride"} ${segment.line_name} from ${segment.from} to ${segment.to}`);
    const transfer = ride.transfers[index];
    if (transfer) steps.push(`Change at ${transfer.from} to ${transfer.to_line}${transfer.to !== transfer.from ? ` (${transfer.to})` : ""}`);
  });
  steps.push(`Get off at ${ride.to}`);
  return steps;
}
