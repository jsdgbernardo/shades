// Choosing the origin or destination on the map with a fixed centre pin (PRD S-02).

/** The name a pinned point shows in its field. */
export function pinnedName(field, streetName = null) {
  if (streetName) return `Pinned · ${streetName}`;
  return field === "start" ? "Pinned origin" : "Pinned destination";
}

/**
 * What the pin card says about the spot under the pin, and whether it can be set.
 * `lookup` is { outside } or { loading } or { street } where street is the /api/streets/nearest
 * answer (null when no street is near).
 */
export function pinStatus(lookup) {
  if (!lookup || lookup.loading) return { text: "Finding the street…", canSet: true, streetName: null };
  if (lookup.outside) return { text: "Outside Metro Manila", canSet: false, streetName: null };
  const street = lookup.street;
  if (!street) return { text: "No street nearby", canSet: true, streetName: null };
  if (street.named) return { text: `Near ${street.name}`, canSet: true, streetName: street.name };
  // Unnamed ways carry their OSM type as the name ("Footway", "Service", "Primary link").
  return { text: `Near ${unnamedWay(street.name)}`, canSet: true, streetName: null };
}

const UNNAMED = {
  footway: "a footpath", path: "a path", steps: "steps", cycleway: "a bike path", pedestrian: "a pedestrian street",
  service: "a service road", residential: "an unnamed street", "living street": "an unnamed street",
};

/** Plain words for an unnamed way's type, such as "a service road". */
export function unnamedWay(label) {
  const type = String(label || "path").toLowerCase();
  return UNNAMED[type] ?? "an unnamed road";
}
