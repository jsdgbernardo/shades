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

/**
 * Streets from the walk to rate 1 to 5 (PRD S-08). `rated` maps street name to the rating given,
 * or to "error" when saving failed.
 */
function RateList({ streets, rated, onRate }) {
  if (!streets?.length) return null;
  return (
    <div className="rate-list" role="group" aria-label="Rate the streets you walked, 1 hard to 5 easy">
      <small className="rate-list__title">How walkable were they? 1 hard · 5 easy</small>
      {streets.map((street) => {
        const given = rated[street.name];
        return (
          <div className="rate-list__row" key={street.name}>
            <span className="rate-list__name">{street.name} <small>{navDistance(street.length_m)}</small></span>
            {typeof given === "number"
              ? <span className="rate-list__thanks">Thanks · {given}/5</span>
              : (
                <span className="rate-list__buttons">
                  {[1, 2, 3, 4, 5].map((value) => (
                    <button key={value} type="button" onClick={() => onRate(street, value)} aria-label={`Rate ${street.name} ${value} of 5`}>{value}</button>
                  ))}
                </span>
              )}
          </div>
        );
      })}
      {Object.values(rated).includes("error") && <small className="nav-bar__warn">Some ratings could not be saved. Try again.</small>}
    </div>
  );
}

/** Shown when the walk reaches the destination: the walk has ended, with a short summary. */
export function ArrivalCard({ arrival, rated = {}, onRate, onDone }) {
  // Skip while there are streets to rate and none rated yet; Done otherwise.
  const skipping = arrival.streets?.length > 0 && Object.keys(rated).length === 0;
  return (
    <section className="float-card arrival-card" role="status" aria-live="polite">
      <div className="arrival-card__top">
        <span className="arrival-card__icon"><ManeuverIcon kind="arrive" /></span>
        <span className="arrival-card__text">
          <strong>You've arrived{arrival.place ? ` at ${arrival.place}` : ""}</strong>
          <span>{formatMinutes(arrival.elapsedMinutes)} · {navDistance(arrival.distance_m)} · {formatMinutes(arrival.sun_minutes)} in sun ({formatPercent(arrival.sun_percent)})</span>
        </span>
        <button type="button" className={skipping ? "text-button" : "solid-button solid-button--small"} onClick={onDone}>{skipping ? "Skip" : "Done"}</button>
      </div>
      <RateList streets={arrival.streets} rated={rated} onRate={onRate} />
    </section>
  );
}

/** After ending a walk past halfway: the same short list of streets to rate. */
export function RateWalkCard({ streets, rated = {}, onRate, onDone }) {
  const any = Object.keys(rated).length > 0;
  return (
    <section className="float-card arrival-card" role="dialog" aria-label="Rate the streets you walked">
      <div className="arrival-card__top">
        <span className="arrival-card__text"><strong>Rate the streets you walked?</strong></span>
        <button type="button" className={any ? "solid-button solid-button--small" : "text-button"} onClick={onDone}>{any ? "Done" : "Skip"}</button>
      </div>
      <RateList streets={streets} rated={rated} onRate={onRate} />
    </section>
  );
}

/** Bottom bar while navigating: time and distance left, and sun on the rest of the route (F-13). */
export function NavBar({ remaining, message, onEnd, onCoveredHere, covered, onUndoCovered }) {
  const arrival = new Date(Date.now() + remaining.minutes * 60_000);
  return (
    <section className="float-card nav-bar" aria-live="polite" aria-label="Rest of the walk">
      <span className="nav-bar__main">
        <strong>{formatMinutes(remaining.minutes)}</strong>
        <span>{navDistance(remaining.distance_m)} · arrive {formatClock(arrival)}</span>
        <small>{formatPercent(remaining.sun_percent)} sun ahead · {formatMinutes(remaining.sun_minutes)} in sun</small>
        {covered?.state === "saved" && (
          <small className="nav-bar__covered">Marked as covered · <button type="button" className="text-button nav-bar__undo" onClick={onUndoCovered}>Undo</button></small>
        )}
        {covered?.state === "error" && <small className="nav-bar__warn">{covered.message}</small>}
        {message && <small className="nav-bar__warn">{message}</small>}
      </span>
      <span className="nav-bar__actions">
        {/* One tap while under a covered walkway marks the stretch being walked (PRD S-10). */}
        {onCoveredHere && (
          <button type="button" className="nav-bar__covered-here" onClick={onCoveredHere} disabled={covered?.state === "saving"}>Covered here</button>
        )}
        <button type="button" className="solid-button solid-button--small nav-bar__end" onClick={onEnd}>End</button>
      </span>
    </section>
  );
}
