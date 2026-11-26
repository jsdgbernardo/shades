const base = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

export const OriginIcon = () => (
  <svg viewBox="0 0 20 20" width="18" height="18" {...base}><circle cx="10" cy="10" r="6.5" /></svg>
);

export const PinIcon = () => (
  <svg viewBox="0 0 20 22" width="18" height="20" {...base}>
    <path d="M10 20.5S3 13.6 3 8.9a7 7 0 1 1 14 0c0 4.7-7 11.6-7 11.6Z" /><circle cx="10" cy="8.9" r="2.4" />
  </svg>
);

export const SwapIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" {...base}>
    <path d="M8 4v15M4.5 15.5 8 19l3.5-3.5M16 20V5M12.5 8.5 16 5l3.5 3.5" />
  </svg>
);

export const ClockIcon = () => (
  <svg viewBox="0 0 20 20" width="18" height="18" {...base}><circle cx="10" cy="10" r="7.5" /><path d="M10 5.8V10l2.8 1.8" /></svg>
);

export const ThermometerIcon = () => (
  <svg viewBox="0 0 20 22" width="16" height="19" {...base}>
    <path d="M8 13.2V4a2 2 0 1 1 4 0v9.2a4 4 0 1 1-4 0Z" /><path d="M10 9v6" />
  </svg>
);

export const LocateIcon = () => (
  <svg viewBox="0 0 28 28" width="28" height="28" {...base} strokeWidth="1.7">
    <circle cx="14" cy="14" r="7.5" /><circle cx="14" cy="14" r="2" fill="currentColor" />
    <path d="M14 2.5v4M14 21.5v4M2.5 14h4M21.5 14h4" />
  </svg>
);

/** North needle; `bearing` is the map's rotation in degrees, so the needle keeps pointing north. */
export const CompassIcon = ({ bearing = 0 }) => (
  <svg viewBox="0 0 28 28" width="28" height="28" aria-hidden="true" style={{ transform: `rotate(${-bearing}deg)` }}>
    <path d="M14 3.5 18 14h-8Z" fill="#c8402f" />
    <path d="M14 24.5 10 14h8Z" fill="#9aa0a6" />
    <circle cx="14" cy="14" r="1.6" fill="#fff" />
  </svg>
);

export const WalkIcon = () => (
  <svg viewBox="0 0 20 20" width="16" height="16" {...base}>
    <circle cx="11" cy="3.6" r="1.6" /><path d="m8 18 2-5.5 2.5 2.5V18M7 10l2-3.5 3 1 1.5 3M10 6.5 9 12" />
  </svg>
);
