import { useEffect } from "react";
import { LABEL_TEXT, formatDistance } from "../lib/format.js";

export function walkabilityText(walkability) {
  if (!walkability) return "";
  if (walkability.status === "rated") return `${walkability.average.toFixed(1)}/5 · ${walkability.rating_count} user ratings`;
  return `${walkability.rating_count}/3 user ratings`;
}

/**
 * Compact, non-blocking card for a tapped street or route section: why the section is
 * labeled as it is (PRD I-01), walkability from user ratings (S-08, S-09), and the
 * covered mark (S-10). No scrim, so the map stays visible and tappable (SKILL.md §12).
 */
export default function StreetModal({ tap, busy, notice, onRate, onToggleCovered, onClose }) {
  const { street, section, loading } = tap;

  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <section className="float-card street-card" role="dialog" aria-label={street?.name ?? "Route section"}>
      <div className="street-card__header">
        <strong>{street?.name ?? (loading ? "…" : "Route section")}</strong>
        {street && <span className="street-card__score">{walkabilityText(street.walkability)}</span>}
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close">×</button>
      </div>

      {section && (
        <p className={`section-reason section-reason--${section.label}`} aria-label={`${LABEL_TEXT[section.label] ?? section.label}. ${section.reason}`}>
          {section.reason} <small>{formatDistance(section.length_m)}</small>
        </p>
      )}

      {street && (
        <div className="street-card__actions">
          <div className="rating-buttons" role="group" aria-label="Rate walkability, 1 hard to 5 easy">
            {[1, 2, 3, 4, 5].map((value) => (
              <button key={value} type="button" disabled={busy} onClick={() => onRate(value)} aria-label={`Rate ${value} of 5`}>{value}</button>
            ))}
          </div>
          <button type="button" className={`covered-toggle ${street.section.covered ? "covered-toggle--on" : ""}`} disabled={busy} onClick={onToggleCovered}
            aria-pressed={street.section.covered} title={`${formatDistance(street.section.length_m)} stretch highlighted on the map`}>
            Covered
          </button>
        </div>
      )}
      {notice && <p className="street-card__notice">{notice}</p>}
    </section>
  );
}
