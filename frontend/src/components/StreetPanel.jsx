import { formatDistance } from "../lib/format.js";

export function walkabilityText(walkability) {
  if (!walkability) return null;
  if (walkability.status === "rated") return `${walkability.average.toFixed(1)} / 5 from ${walkability.rating_count} ratings`;
  return `Not enough ratings yet (${walkability.rating_count} of 3 needed)`;
}

/** Rate a street 1–5 and mark or unmark a section as covered (PRD S-08, S-10). */
export default function StreetPanel({ street, busy, notice, onRate, onToggleCovered, onClose }) {
  return (
    <section className="street-panel" aria-label="Street">
      <div className="street-panel__header">
        <strong>Rate streets and mark covered walkways</strong>
        <button type="button" className="text-button" onClick={onClose}>Done</button>
      </div>
      {!street && <p className="sheet-hint">Tap a street or path on the map.</p>}
      {street && (
        <>
          <p className="street-panel__name">{street.name}</p>
          <p className="street-panel__score">
            Walkability: {walkabilityText(street.walkability)}
            <small> Based on user ratings only. It does not change routes or sun figures.</small>
          </p>
          <div className="rating-buttons" role="group" aria-label="Rate how walkable this street is, 1 to 5">
            {[1, 2, 3, 4, 5].map((value) => (
              <button key={value} type="button" disabled={busy} onClick={() => onRate(value)}>{value}</button>
            ))}
          </div>
          <p className="rating-scale"><span>1 hard to walk</span><span>5 easy to walk</span></p>
          <button type="button" className="covered-toggle" disabled={busy} onClick={onToggleCovered}>
            {street.section.covered ? "Remove covered mark from this section" : "Mark this section as covered"}
            <small>{formatDistance(street.section.length_m)} section, highlighted on the map</small>
          </button>
        </>
      )}
      {notice && <p className="sheet-note">{notice}</p>}
    </section>
  );
}
