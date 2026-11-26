import { useEffect, useRef, useState } from "react";
import { searchPlaces } from "../lib/api.js";
import { OriginIcon, PinIcon, SwapIcon } from "./Icons.jsx";

// Search results: the name, then "kind · address" on one line that ends in an ellipsis.
const RESULT_STYLE = { flexDirection: "column", alignItems: "stretch", justifyContent: "flex-start", gap: 1 };
const DETAIL_STYLE = { flex: "none", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textTransform: "none" };

function displayName(point, field) {
  if (!point) return "";
  if (point.source === "gps") return "Your Location";
  return point.name || (field === "start" ? "Pinned start" : "Pinned destination");
}

function Field({ field, point, other, active, onActivate, onPick, onUseLocation, onChooseOnMap, locationUsable = true }) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const [results, setResults] = useState([]);
  const [searchError, setSearchError] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    if (!editing || query.trim().length < 2) {
      setResults([]);
      return undefined;
    }
    const timer = setTimeout(() => {
      // Rank results near the other end of the trip, so "7-Eleven" finds the branch close by.
      // The user's own position is never sent for this: only route requests may carry it (C-04).
      searchPlaces(query.trim(), other?.source === "gps" ? null : other)
        .then((payload) => { setResults(payload.places ?? []); setSearchError(""); })
        .catch((error) => { setResults([]); setSearchError(error.message); });
    }, 200);
    return () => clearTimeout(timer);
  }, [query, editing, other]);

  const close = () => { setEditing(false); setQuery(""); setResults([]); setSearchError(""); };
  const placeholder = field === "start" ? (locationUsable ? "Your Location" : "Origin") : "Destination";
  const name = displayName(point, field);

  return (
    <div className={`location-row location-row--${field} ${active ? "location-row--active" : ""}`}>
      <span className="location-row__icon">{field === "start" ? <OriginIcon /> : <PinIcon />}</span>
      <input
        ref={inputRef}
        className="location-row__input"
        value={editing ? query : name}
        placeholder={placeholder}
        aria-label={field === "start" ? "Start point" : "Destination"}
        onFocus={() => { setEditing(true); onActivate(field); }}
        onBlur={() => setTimeout(close, 150)}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") inputRef.current?.blur();
          if (event.key === "Enter" && results[0]) { onPick(field, results[0]); inputRef.current?.blur(); }
        }}
      />
      {editing && (field === "start" || onChooseOnMap || query.trim().length >= 2) && (
        <ul className="place-results" role="listbox">
          {field === "start" && (
            <li><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => { onUseLocation(); inputRef.current?.blur(); }}>
              <strong>Current location</strong>
            </button></li>
          )}
          {onChooseOnMap && (
            <li><button type="button" className="place-results__pin" onMouseDown={(event) => event.preventDefault()} onClick={() => { inputRef.current?.blur(); onChooseOnMap(field); }}>
              <PinIcon /><strong>Choose on map</strong>
            </button></li>
          )}
          {results.map((place) => (
            <li key={place.id}><button type="button" style={RESULT_STYLE} onMouseDown={(event) => event.preventDefault()} onClick={() => { onPick(field, place); inputRef.current?.blur(); }}>
              <strong>{place.name}</strong>
              {/* Kind and a short address, so two branches of the same chain can be told apart. */}
              <small style={DETAIL_STYLE}>
                <span style={{ textTransform: "capitalize" }}>{place.kind}</span>
                {place.address ? ` · ${place.address}` : ""}
              </small>
            </button></li>
          ))}
          {query.trim().length >= 2 && !results.length && !searchError && <li className="place-results__empty">No places found in Metro Manila</li>}
          {searchError && <li className="place-results__empty">{searchError}</li>}
        </ul>
      )}
    </div>
  );
}

export default function LocationCard({ start, destination, activeField, onActivate, onPick, onSwap, onUseLocation, onChooseOnMap, locationUsable }) {
  return (
    <section className="location-card" aria-label="Trip">
      <div className="location-card__rows">
        <Field field="start" point={start} other={destination} active={activeField === "start"} onActivate={onActivate} onPick={onPick} onUseLocation={onUseLocation} onChooseOnMap={onChooseOnMap} locationUsable={locationUsable} />
        <span className="location-card__connector" aria-hidden="true" />
        <Field field="destination" point={destination} other={start} active={activeField === "destination"} onActivate={onActivate} onPick={onPick} onUseLocation={onUseLocation} onChooseOnMap={onChooseOnMap} locationUsable={locationUsable} />
      </div>
      <button type="button" className="swap-button" onClick={onSwap} aria-label="Swap start and destination"><SwapIcon /></button>
    </section>
  );
}
