import { useState } from "react";
import { readingValue } from "../lib/format.js";
import { formatClock } from "../lib/time.js";
import { ClockIcon, ThermometerIcon } from "./Icons.jsx";

/** "Leave Now" time control and the temperature / heat index readings (context only). */
export default function TimePill({ leaveNow, travelInput, onChangeTime, onLeaveNow, weather }) {
  const [open, setOpen] = useState(false);
  const temperature = readingValue(weather?.temperature_c);
  const heatIndex = readingValue(weather?.heat_index_c);
  const label = leaveNow ? "Leave Now" : `Leave ${formatClock(travelInput)}`;

  return (
    <div className="time-pill">
      <button type="button" className="time-pill__time" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <ClockIcon /><span>{label}</span>
      </button>
      <div className="time-pill__weather" title="Weather readings for context only. They do not change routes or scores.">
        <ThermometerIcon />
        {weather ? (
          <span>
            {/* Missing readings are muted, not red: they are absent data, not a warning (F-12). */}
            {temperature ?? <span className="time-pill__muted">Temp n/a</span>}
            <span className="time-pill__dot">·</span>
            {heatIndex ? <>Heat index {heatIndex}</> : <span className="time-pill__muted">Heat index n/a</span>}
          </span>
        ) : <span className="time-pill__muted">—</span>}
      </div>
      {open && (
        <div className="time-popover">
          <input type="datetime-local" aria-label="Leave at" value={travelInput} onChange={(event) => onChangeTime(event.target.value)} />
          <button type="button" className="text-button" onClick={() => { onLeaveNow(); setOpen(false); }}>Now</button>
          <button type="button" className="solid-button solid-button--small" onClick={() => setOpen(false)}>Done</button>
        </div>
      )}
    </div>
  );
}
