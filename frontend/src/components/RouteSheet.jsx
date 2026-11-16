import { useState } from "react";
import { formatDistance, formatMinutes, formatPercent, readingValue } from "../lib/format.js";
import { formatClock } from "../lib/time.js";
import { WalkIcon } from "./Icons.jsx";

function RouteCard({ route, selected, onSelect }) {
  const exposure = route.exposure;
  return (
    <button type="button" className={`route-card ${selected ? "route-card--selected" : ""}`} onClick={() => onSelect(route.id)} aria-pressed={selected}>
      <span className={`route-card__label route-card__label--${route.id}`}>{route.label}</span>
      <span className="route-card__score"><strong>{formatPercent(exposure.sun_percent)}</strong> in direct sun</span>
      <span className="route-card__line">{formatMinutes(exposure.sun_minutes)} in sun</span>
      <span className="route-card__line route-card__muted">{formatDistance(route.distance_m)} · {formatMinutes(route.duration_minutes)} walk</span>
      {exposure.unknown_percent > 0 && <span className="route-card__line route-card__unknown">{formatPercent(exposure.unknown_percent)} shade unknown</span>}
      {route.walkability && (
        <span className="route-card__walkability">
          Walkability {route.walkability.score == null ? "not rated yet" : `${route.walkability.score.toFixed(1)}/5`}
          {" · "}{formatPercent(route.walkability.rated_share_percent)} rated by users
        </span>
      )}
    </button>
  );
}

function Comparison({ comparison, note }) {
  if (!comparison) return note ? <p className="sheet-note">{note}</p> : null;
  const extra = comparison.extra_distance_m;
  return (
    <p className="comparison">
      The shadier route has <strong>{Math.round(comparison.sun_percent_points_less)} percentage points less sun</strong>
      {" "}and {formatMinutes(comparison.sun_minutes_less)} less in the sun, for {extra > 0 ? `${formatDistance(extra)} more walking` : "no extra distance"}
      {comparison.extra_minutes >= 1 ? ` (+${formatMinutes(comparison.extra_minutes)})` : ""}.
    </p>
  );
}

function ComfortWindow({ window }) {
  if (!window) return null;
  const now = window.times[0].sun_percent;
  const best = window.times.find((entry) => entry.offset_minutes === window.best_offset_minutes) ?? window.times[0];
  return (
    <section className="comfort" aria-label="Least sun in the next 30 minutes">
      <div className="comfort__times">
        {window.times.map((entry) => (
          <span key={entry.offset_minutes} className={`comfort__time ${entry.offset_minutes === window.best_offset_minutes ? "comfort__time--best" : ""}`}>
            <small>{entry.offset_minutes === 0 ? "Now" : `+${entry.offset_minutes} min`}</small>
            <strong>{formatPercent(entry.sun_percent)}</strong>
          </span>
        ))}
      </div>
      <p className="comfort__advice">
        {window.recommendation === "wait"
          ? <>Wait until <strong>{formatClock(best.time)}</strong> for the least sun: {Math.round(now - best.sun_percent)} points less than now.</>
          : <><strong>Walk now.</strong> Waiting up to 30 minutes would not cut the sun by 5 points or more.</>}
      </p>
    </section>
  );
}

function LiveWalk({ walk, route, onStart, onStop }) {
  if (!walk.active) {
    return <button type="button" className="solid-button solid-button--wide" onClick={onStart}><WalkIcon /> Start walk</button>;
  }
  const remaining = walk.remaining;
  return (
    <section className="live-walk" aria-live="polite">
      <div className="live-walk__header">
        <strong>Walking · {route.label}</strong>
        <button type="button" className="text-button" onClick={onStop}>End walk</button>
      </div>
      {remaining ? (
        <div className="live-walk__figures">
          <span><strong>{formatDistance(remaining.distance_m)}</strong><small>left</small></span>
          <span><strong>{formatPercent(remaining.sun_percent)}</strong><small>in sun ahead</small></span>
          <span><strong>{formatMinutes(remaining.sun_minutes)}</strong><small>in sun ahead</small></span>
        </div>
      ) : <p className="sheet-note">Waiting for your position…</p>}
      {walk.message && <p className="sheet-note sheet-note--warn">{walk.message}</p>}
    </section>
  );
}

export default function RouteSheet({ status, error, message, data, selectedId, onSelect, onRetry, walk, onStartWalk, onStopWalk, children }) {
  const [expanded, setExpanded] = useState(false);
  const routes = data?.routes ?? [];
  const selected = routes.find((route) => route.id === selectedId) ?? routes[0];
  const weather = data?.weather;
  const showDetails = expanded || walk.active;

  return (
    <section className={`route-sheet route-sheet--${status} ${showDetails ? "route-sheet--expanded" : ""}`} aria-label="Routes">
      <button type="button" className="sheet-handle" onClick={() => setExpanded((value) => !value)} aria-label={expanded ? "Show less" : "Show more"} aria-expanded={expanded} />
      {message && <p className="sheet-note sheet-note--warn">{message}</p>}
      {status === "idle" && <p className="sheet-hint">Search for a place or tap the map to set where you are going.</p>}
      {status !== "results" && children}
      {status === "loading" && <p className="sheet-hint">Checking sun and shade along the way…</p>}
      {status === "error" && (
        <div className="sheet-error">
          <p>{error}</p>
          <button type="button" className="text-button" onClick={onRetry}>Try again</button>
        </div>
      )}
      {status === "results" && selected && (
        <>
          <p className="sheet-eyebrow">Sun at {formatClock(data.travel_time)} · assumes a clear sky</p>
          <div className={`route-cards route-cards--${routes.length}`}>
            {routes.map((route) => (
              <RouteCard key={route.id} route={route} selected={route.id === selected.id} onSelect={onSelect} />
            ))}
          </div>
          <Comparison comparison={data.comparison} note={data.alternative_note} />
          {!showDetails && (
            <button type="button" className="more-button" onClick={() => setExpanded(true)}>
              Best time to leave, live walk and details
            </button>
          )}
          {showDetails && <>
          {selected.exposure.unknown_percent > 0 && (
            <p className="sheet-note">
              {formatPercent(selected.exposure.unknown_percent)} of this route has no building height data. Those sections are counted as direct sun, so the real figure may be lower.
            </p>
          )}
          <ComfortWindow window={selected.comfort_window} />
          <LiveWalk walk={walk} route={selected} onStart={onStartWalk} onStop={onStopWalk} />
          <p className="context-line">
            UV {weather?.uv?.status === "available" ? `${weather.uv.value} (${weather.uv.category})` : "not available"}
            {" · "}Humidity {readingValue(weather?.humidity_percent, "%") ?? "not available"}
            <span> Weather readings are for context only and do not change routes or scores.</span>
          </p>
          <details className="assumptions">
            <summary>About these figures</summary>
            <ul>{data.assumptions?.notes?.map((note) => <li key={note}>{note}</li>)}</ul>
          </details>
          </>}
          {children}
        </>
      )}
    </section>
  );
}
