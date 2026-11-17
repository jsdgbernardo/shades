import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { formatDistance, formatMinutes, formatPercent, readingValue } from "../lib/format.js";
import { animateSpring, nearest, project, releaseVelocity, rubberband } from "../lib/spring.js";
import { formatClock } from "../lib/time.js";
import { WalkIcon } from "./Icons.jsx";

const SLIVER_PX = 26;

const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function RouteCard({ route, selected, onSelect }) {
  const exposure = route.exposure;
  // Two columns: text on the left, the sun share pinned top-right in line with the route name.
  return (
    <button type="button" className={`route-card ${selected ? "route-card--selected" : ""}`} onClick={() => onSelect(route.id)} aria-pressed={selected}>
      <span className="route-card__text">
        <span className={`route-card__label route-card__label--${route.id}`}>{route.label.replace(" route", "")}</span>
        <span className="route-card__line">{formatMinutes(route.duration_minutes)} walk · {formatDistance(route.distance_m)}</span>
        <span className="route-card__line route-card__muted">{formatMinutes(exposure.sun_minutes)} in sun</span>
        {exposure.unknown_percent > 0 && <span className="route-card__unknown">{formatPercent(exposure.unknown_percent)} shade unknown, counted as sun</span>}
        {route.walkability?.score != null && (
          <span className="route-card__walkability">Walkability {route.walkability.score.toFixed(1)}/5 (user ratings)</span>
        )}
      </span>
      <strong className="route-card__score" title="Share of the route in direct sun">{formatPercent(exposure.sun_percent)}</strong>
    </button>
  );
}

/** Shadier vs shortest differences (PRD F-09), shown in the pulled-up details. */
function ComparisonLine({ comparison }) {
  if (!comparison) return null;
  const extra = comparison.extra_distance_m;
  return (
    <p className="sheet-note">
      Shadier route: {Math.round(comparison.sun_percent_points_less)} percentage points less sun, {formatMinutes(comparison.sun_minutes_less)} less in sun, {extra > 0 ? `${formatDistance(extra)} longer` : "same distance"}.
    </p>
  );
}

function bestTime(window) {
  if (!window) return null;
  const now = window.times[0].sun_percent;
  const best = window.times.find((entry) => entry.offset_minutes === window.best_offset_minutes) ?? window.times[0];
  return window.recommendation === "wait"
    ? <>Less sun at <strong>{formatClock(best.time)}</strong> (−{Math.round(now - best.sun_percent)} pts)</>
    : <>Now is the least sunny time</>;
}

/**
 * Bottom stack: legend + locate row, then a draggable sheet (peek ↔ expanded) or a
 * compact overlay card (street details, off-route prompt). Drag follows SKILL.md:
 * 1:1 tracking, rubber-band at the ends, momentum projection, interruptible spring.
 */
export default function RouteSheet({ status, error, message, onDismissMessage, data, selectedId, onSelect, onRetry, walk, onStartWalk, onStopWalk, accessory, overlay, timeOffset = 0, onSelectTime, canFind = false, onFind }) {
  const stackRef = useRef(null);
  const sheetRef = useRef(null);
  const peekRef = useRef(null);
  const offsetRef = useRef(0);
  const maxRef = useRef(0);
  const collapsedRef = useRef(true);
  const cancelRef = useRef(null);
  const dragRef = useRef(null);
  const [, forceRender] = useState(0);
  // Fade the bottom edge of the details while more content is below (scroll edge effect).
  const bodyRef = useRef(null);
  const [moreBelow, setMoreBelow] = useState(false);
  const checkMoreBelow = useCallback(() => {
    const body = bodyRef.current;
    setMoreBelow(Boolean(body) && body.scrollHeight - body.scrollTop - body.clientHeight > 2);
  }, []);
  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return undefined;
    const observer = new ResizeObserver(checkMoreBelow);
    observer.observe(body);
    checkMoreBelow();
    return () => observer.disconnect();
  });

  const routes = data?.routes ?? [];
  const selected = routes.find((route) => route.id === selectedId) ?? routes[0];
  const weather = data?.weather;
  const draggable = status === "results" && selected && !overlay;

  const apply = useCallback((offset) => {
    offsetRef.current = offset;
    const stack = stackRef.current;
    if (!stack) return;
    stack.style.transform = `translateY(${offset}px)`;
    // 0 = collapsed, 1 = open. The grabber bends with it so it always points where the sheet can go.
    const progress = maxRef.current > 0 ? Math.min(1, Math.max(0, 1 - offset / maxRef.current)) : 1;
    stack.style.setProperty("--sheet-progress", progress.toFixed(3));
  }, []);

  const settle = useCallback((target, velocity = 0) => {
    cancelRef.current?.();
    cancelRef.current = null;
    collapsedRef.current = target > 0;
    if (prefersReducedMotion()) { apply(target); return; }
    // Bounce only when the gesture carried momentum; otherwise critically damped.
    const damping = Math.abs(velocity) > 300 ? 0.8 : 1;
    cancelRef.current = animateSpring({ from: offsetRef.current, to: target, velocity, damping, response: 0.3, onUpdate: apply, onDone: () => { cancelRef.current = null; } });
  }, [apply]);

  // The collapsed offset hides everything below the peek; recompute when content changes.
  useLayoutEffect(() => {
    if (!draggable) { cancelRef.current?.(); cancelRef.current = null; maxRef.current = 0; apply(0); return undefined; }
    const measure = () => {
      const sheet = sheetRef.current;
      const peek = peekRef.current;
      if (!sheet || !peek) return;
      // Leave a sliver of the details showing under the peek, so it reads as "more below".
      const sliver = Math.min(SLIVER_PX, Math.max(0, sheet.offsetHeight - (peek.offsetTop + peek.offsetHeight)));
      maxRef.current = Math.max(0, sheet.offsetHeight - (peek.offsetTop + peek.offsetHeight) - sliver);
      if (collapsedRef.current && !dragRef.current && !cancelRef.current) apply(maxRef.current);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(sheetRef.current);
    measure();
    return () => observer.disconnect();
  }, [draggable, apply]);

  // New routes start collapsed so the map stays visible, with one small upward nudge that
  // springs back, showing the sheet can be pulled up (skipped for reduced motion).
  useEffect(() => {
    collapsedRef.current = true;
    cancelRef.current?.();
    cancelRef.current = null;
    apply(maxRef.current);
    forceRender((n) => n + 1);
    if (!data || prefersReducedMotion() || maxRef.current <= 0) return undefined;
    const timer = setTimeout(() => {
      if (dragRef.current || !collapsedRef.current) return;
      cancelRef.current = animateSpring({
        from: maxRef.current, to: maxRef.current, velocity: -380, damping: 0.55, response: 0.4,
        onUpdate: apply, onDone: () => { cancelRef.current = null; },
      });
    }, 350);
    return () => clearTimeout(timer);
  }, [data, apply]);

  const onPointerDown = (event) => {
    if (!draggable) return;
    cancelRef.current?.();
    cancelRef.current = null;
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* pointer already gone */ }
    dragRef.current = { y: event.clientY, offset: offsetRef.current, moved: false, samples: [{ t: event.timeStamp, y: event.clientY }] };
  };
  const onPointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    const dy = event.clientY - drag.y;
    if (!drag.moved && Math.abs(dy) < 8) return; // small hysteresis before committing to a drag
    drag.moved = true;
    const raw = drag.offset + dy;
    const max = maxRef.current;
    const offset = raw < 0 ? rubberband(raw, max || 1) : raw > max ? max + rubberband(raw - max, max || 1) : raw;
    apply(offset);
    drag.samples = [...drag.samples.slice(-5), { t: event.timeStamp, y: event.clientY }];
  };
  const onPointerUp = (event) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag) return;
    if (!drag.moved) { settle(collapsedRef.current ? 0 : maxRef.current); return; }
    const velocity = releaseVelocity([...drag.samples, { t: event.timeStamp, y: event.clientY }]);
    const target = nearest([0, maxRef.current], offsetRef.current + project(velocity));
    settle(target, velocity);
  };

  const row = <div className="bottom-stack__row">{accessory}</div>;

  if (overlay) {
    return <div className="bottom-stack" ref={stackRef}>{row}{overlay}</div>;
  }
  if (status !== "results" || !selected) {
    const note = status === "error" ? error : message;
    const showFind = canFind && status !== "error";
    return (
      <div className="bottom-stack" ref={stackRef}>
        {row}
        {note && (
          <div className="toast toast--warn" role="status">
            <span>{note}</span>
            {status === "error" && <button type="button" className="text-button" onClick={onRetry}>Retry</button>}
            {status !== "error" && message && <button type="button" className="icon-button" onClick={onDismissMessage} aria-label="Dismiss">×</button>}
          </div>
        )}
        {showFind && (
          <div className="find-bar">
            <button type="button" className="solid-button find-button" onClick={onFind} disabled={status === "loading"}>
              {status === "loading" ? "Finding routes…" : "Find routes"}
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="bottom-stack" ref={stackRef}>
      {row}
      <section className="route-sheet" ref={sheetRef} aria-label="Routes">
        <div
          className="sheet-grab"
          role="button"
          tabIndex={0}
          aria-label={collapsedRef.current ? "Show details" : "Hide details"}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") settle(collapsedRef.current ? 0 : maxRef.current); }}
        />
        <div className="sheet-peek" ref={peekRef}>
          {message && <p className="sheet-note sheet-note--warn">{message}</p>}
          <div className={`route-cards route-cards--${routes.length}`}>
            {routes.map((route) => (
              <RouteCard key={route.id} route={route} selected={route.id === selected.id} onSelect={onSelect} />
            ))}
          </div>
          {walk.active ? (
            <div className="walk-row" aria-live="polite">
              {walk.remaining
                ? <span><strong>{formatDistance(walk.remaining.distance_m)}</strong> left · <strong>{formatPercent(walk.remaining.sun_percent)}</strong> sun · {formatMinutes(walk.remaining.sun_minutes)}</span>
                : <span>Locating…</span>}
              <button type="button" className="text-button" onClick={onStopWalk}>End</button>
            </div>
          ) : (
            <div className="walk-row">
              <span className="walk-row__hint">{bestTime(selected.comfort_window)}</span>
              <button type="button" className="solid-button solid-button--small" onClick={onStartWalk}><WalkIcon /> Start</button>
            </div>
          )}
          {walk.active && walk.message && <p className="sheet-note sheet-note--warn">{walk.message}</p>}
        </div>
        {/* The wrapper fades the sliver of details that shows under the collapsed peek;
            the inner body fades its own bottom edge while more content is below. */}
        <div className="sheet-body-wrap">
        <div className={`sheet-body ${moreBelow ? "sheet-body--more" : ""}`} ref={bodyRef} onScroll={checkMoreBelow}>
          {data.comparison ? <ComparisonLine comparison={data.comparison} /> : data.alternative_note && <p className="sheet-note">{data.alternative_note}</p>}
          <div className="comfort__times" role="group" aria-label="Share of the route in direct sun now and in the next 30 minutes; choose one to show it on the map">
            {selected.comfort_window.times.map((entry) => (
              <button
                key={entry.offset_minutes}
                type="button"
                className={`comfort__time ${entry.offset_minutes === timeOffset ? "comfort__time--selected" : ""}`}
                aria-pressed={entry.offset_minutes === timeOffset}
                onClick={() => onSelectTime(entry.offset_minutes)}
              >
                <small>{entry.offset_minutes === 0 ? "Now" : `+${entry.offset_minutes} min`}</small>
                <strong>{formatPercent(entry.sun_percent)}</strong>
              </button>
            ))}
          </div>
          <p className="context-line">
            UV {weather?.uv?.status === "available" ? `${weather.uv.value} (${weather.uv.category})` : "not available"}
            {" · "}Humidity {readingValue(weather?.humidity_percent, "%") ?? "not available"}
          </p>
          {/* Required limits in one line: clear sky / buildings only (C-05) and the walking speed (F-06). */}
          <p className="assumptions" title={data.assumptions?.notes?.join(" ")}>
            Clear sky · building shade only · {data.assumptions?.walking_speed_m_per_min ?? 80} m/min
          </p>
        </div>
        </div>
      </section>
    </div>
  );
}
