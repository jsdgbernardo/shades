// Asking for street ratings at the end of a walk (PRD S-08), without asking twice.

const STORAGE_KEY = "shades.ratedStreets";
export const MIN_STREET_M = 30;

/**
 * Up to `limit` named streets from the walked part of a route, longest first, leaving out short
 * stretches and streets this phone has already rated. `edges` are the route's API edges
 * ({ way_id, name, named, length_m }) in walking order.
 *
 * One street is often several OSM ways (Katipunan Avenue in pieces), so streets are grouped by
 * name; `way_ids` lists the walked, not yet rated pieces, and one rating goes to each of them.
 */
export function streetsToRate(edges, walkedMeters, ratedIds = new Set(), limit = 3) {
  const streets = new Map();
  let start = 0;
  for (const edge of edges ?? []) {
    const walked = Math.max(0, Math.min(edge.length_m, walkedMeters - start));
    start += edge.length_m;
    if (walked <= 0 || !edge.named || ratedIds.has(edge.way_id)) continue;
    const street = streets.get(edge.name) ?? { name: edge.name, way_ids: [], length_m: 0 };
    if (!street.way_ids.includes(edge.way_id)) street.way_ids.push(edge.way_id);
    street.length_m += walked;
    streets.set(edge.name, street);
  }
  return [...streets.values()]
    .filter((street) => street.length_m >= MIN_STREET_M)
    .sort((a, b) => b.length_m - a.length_m)
    .slice(0, limit);
}

function defaultStorage() {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // blocked (private mode, disabled site data)
  }
}

/** Street (way) ids this phone has rated. Empty if storage is unavailable. */
export function ratedStreets(storage = defaultStorage()) {
  try {
    const ids = JSON.parse(storage?.getItem(STORAGE_KEY) ?? "[]");
    return new Set(Array.isArray(ids) ? ids.filter(Number.isInteger) : []);
  } catch {
    return new Set();
  }
}

/** Remembers a rated street on this phone only, so it is not asked about again. */
export function rememberRated(wayId, storage = defaultStorage()) {
  try {
    const ids = ratedStreets(storage);
    ids.add(wayId);
    storage?.setItem(STORAGE_KEY, JSON.stringify([...ids]));
  } catch {
    // Storage blocked: the street may be asked about again, which is harmless.
  }
}
