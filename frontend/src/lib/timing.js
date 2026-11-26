// Field-test timing readout (open the app with ?timing). Measures on the phone only; nothing is
// sent anywhere. P-01: tap Find routes -> routes drawn. P-02: GPS fix -> walk figures updated.

/** True when the address has ?timing. */
export function timingEnabled(search = typeof window === "undefined" ? "" : window.location.search) {
  return new URLSearchParams(search).has("timing");
}

/** Adds one measurement (milliseconds) to a running { last, max, count, over } record. */
export function addSample(stat, ms, limitMs) {
  const value = Math.max(0, ms);
  return {
    last: value,
    max: Math.max(stat?.max ?? 0, value),
    count: (stat?.count ?? 0) + 1,
    over: (stat?.over ?? 0) + (value > limitMs ? 1 : 0),
  };
}

export function seconds(ms) {
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

/** One line for the readout, such as "Routes 1.42 s (max 2.10 s, 0 of 3 over 10 s)". */
export function describe(label, stat, limitMs) {
  if (!stat) return `${label} –`;
  return `${label} ${seconds(stat.last)} (max ${seconds(stat.max)}, ${stat.over} of ${stat.count} over ${seconds(limitMs)})`;
}

/** Calls back after the browser has painted the current update (two animation frames). */
export function afterPaint(callback) {
  if (typeof requestAnimationFrame === "undefined") { callback(); return; }
  requestAnimationFrame(() => requestAnimationFrame(callback));
}
