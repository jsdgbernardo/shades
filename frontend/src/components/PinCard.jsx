import { pinStatus } from "../lib/pin.js";

/** Bottom card while choosing a point on the map: what is under the pin, then Cancel or Set. */
export default function PinCard({ field, lookup, onCancel, onSet }) {
  const status = pinStatus(lookup);
  const label = field === "start" ? "origin" : "destination";
  return (
    <section className="float-card pin-card" aria-label={`Choose the ${label} on the map`} aria-live="polite">
      <span className="pin-card__text">
        <small>{field === "start" ? "Origin" : "Destination"}</small>
        <strong>{status.text}</strong>
      </span>
      <div className="pin-card__actions">
        <button type="button" className="text-button" onClick={onCancel}>Cancel</button>
        <button type="button" className="solid-button solid-button--small" disabled={!status.canSet} onClick={() => onSet(status.streetName)}>
          Set {label}
        </button>
      </div>
    </section>
  );
}
