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

/**
 * This phone's ratings: way id -> { rating, token }. The token lets the phone change or remove
 * its own rating later (the server keeps only a hash of it). An older list of ids still reads.
 */
export function myRatings(storage = defaultStorage()) {
  try {
    const saved = JSON.parse(storage?.getItem(STORAGE_KEY) ?? "{}");
    if (Array.isArray(saved)) return Object.fromEntries(saved.filter(Number.isInteger).map((id) => [id, {}]));
    return saved && typeof saved === "object" ? saved : {};
  } catch {
    return {};
  }
}

/** Street (way) ids this phone has rated. Empty if storage is unavailable. */
export function ratedStreets(storage = defaultStorage()) {
  return new Set(Object.keys(myRatings(storage)).map(Number).filter(Number.isInteger));
}

/** This phone's rating of a street, or null. */
export function myRating(wayId, storage = defaultStorage()) {
  return myRatings(storage)[wayId] ?? null;
}

/** Remembers a rating on this phone only, so the street is not asked about again. */
export function rememberRated(wayId, details = {}, storage = defaultStorage()) {
  try {
    const saved = myRatings(storage);
    saved[wayId] = { ...saved[wayId], ...details };
    storage?.setItem(STORAGE_KEY, JSON.stringify(saved));
  } catch {
    // Storage blocked: the street may be asked about again, which is harmless.
  }
}

/** Forgets a removed rating, so the street can be asked about again. */
export function forgetRated(wayId, storage = defaultStorage()) {
  try {
    const saved = myRatings(storage);
    delete saved[wayId];
    storage?.setItem(STORAGE_KEY, JSON.stringify(saved));
  } catch {
    // Storage blocked: nothing to forget.
  }
}
