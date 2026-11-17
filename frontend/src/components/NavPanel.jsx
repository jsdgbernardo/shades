import { formatMinutes, formatPercent } from "../lib/format.js";
import { maneuverText } from "../lib/nav.js";
import { formatClock } from "../lib/time.js";

const ARROW_ROTATION = {
  "slight-right": 45, right: 90, "sharp-right": 135, uturn: 180,
  "slight-left": -45, left: -90, "sharp-left": -135,
};

function ManeuverIcon({ kind }) {
  if (kind === "arrive") {
    return (
      <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
        <path d="M9 28V5m0 1h14l-3 5 3 5H9" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  const rotation = ARROW_ROTATION[kind] ?? 0;
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <g transform={`rotate(${rotation} 16 16)`}>
        <path d="M16 27V7M9 13l7-7 7 7" fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

/** Rounded the way navigation apps call distances: 5 m steps up close, 10 m further out. */
export function navDistance(meters) {
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)} km`;
  const step = meters >= 100 ? 10 : 5;
  return `${Math.max(0, Math.round(meters / step) * step)} m`;
}

/** Top banner while navigating: next manoeuvre, its distance and the street. */
export function NavBanner({ maneuver }) {
  if (!maneuver) return null;
  return (
    <section className="nav-banner" aria-live="polite" aria-label="Next direction">
      <span className="nav-banner__icon"><ManeuverIcon kind={maneuver.kind} /></span>
      <span className="nav-banner__text">
        <strong>{navDistance(maneuver.distance)}</strong>
        <span>{maneuverText(maneuver)}{maneuver.name ? <> onto <b>{maneuver.name}</b></> : null}</span>
      </span>
    </section>
  );
}

/** Shown when the walk reaches the destination: the walk has ended, with a short summary. */
export function ArrivalCard({ arrival, onDone }) {
  return (
    <section className="float-card arrival-card" role="status" aria-live="polite">
      <span className="arrival-card__icon"><ManeuverIcon kind="arrive" /></span>
      <span className="arrival-card__text">
        <strong>You've arrived{arrival.place ? ` at ${arrival.place}` : ""}</strong>
        <span>{formatMinutes(arrival.elapsedMinutes)} · {navDistance(arrival.distance_m)} · {formatMinutes(arrival.sun_minutes)} in sun ({formatPercent(arrival.sun_percent)})</span>
      </span>
      <button type="button" className="solid-button solid-button--small" onClick={onDone}>Done</button>
    </section>
  );
}

/** Bottom bar while navigating: time and distance left, and sun on the rest of the route (F-13). */
export function NavBar({ remaining, message, onEnd }) {
  const arrival = new Date(Date.now() + remaining.minutes * 60_000);
  return (
    <section className="float-card nav-bar" aria-live="polite" aria-label="Rest of the walk">
      <span className="nav-bar__main">
        <strong>{formatMinutes(remaining.minutes)}</strong>
        <span>{navDistance(remaining.distance_m)} · arrive {formatClock(arrival)}</span>
        <small>{formatPercent(remaining.sun_percent)} sun ahead · {formatMinutes(remaining.sun_minutes)} in sun</small>
        {message && <small className="nav-bar__warn">{message}</small>}
      </span>
      <button type="button" className="solid-button solid-button--small nav-bar__end" onClick={onEnd}>End</button>
    </section>
  );
}
