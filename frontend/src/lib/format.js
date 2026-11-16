export function formatDistance(meters) {
  if (meters == null) return "—";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

export function formatMinutes(minutes) {
  if (minutes == null) return "—";
  if (minutes > 0 && minutes < 1) return "<1 min";
  return `${Math.round(minutes)} min`;
}

export function formatPercent(value) {
  return value == null ? "—" : `${Math.round(value)}%`;
}

/** Temperature-like reading from the API: {status, value}. */
export function readingValue(reading, unit = "°") {
  if (!reading || reading.status !== "available") return null;
  return `${Math.round(reading.value)}${unit}`;
}

export const LABEL_TEXT = {
  sun: "Direct sun",
  shaded: "Shaded",
  unknown: "Shade unknown",
  covered: "Covered",
};
