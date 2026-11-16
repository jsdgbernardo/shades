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
            {temperature ?? "Temp. not available"}
            <span className="time-pill__dot">·</span>
            {heatIndex ? <>Heat index {heatIndex}</> : "Heat index not available"}
          </span>
        ) : <span className="time-pill__muted">—</span>}
      </div>
      {open && (
        <div className="time-popover">
          <label>
            Leave at
            <input type="datetime-local" value={travelInput} onChange={(event) => onChangeTime(event.target.value)} />
          </label>
          <div className="time-popover__actions">
            <button type="button" className="text-button" onClick={() => { onLeaveNow(); setOpen(false); }}>Leave now</button>
            <button type="button" className="solid-button" onClick={() => setOpen(false)}>Done</button>
          </div>
        </div>
      )}
    </div>
  );
}
