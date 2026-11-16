const ITEMS = [
  { label: "sun", text: "Direct sun" },
  { label: "shaded", text: "Shaded" },
  { label: "unknown", text: "Shade unknown" },
  { label: "covered", text: "Covered" },
];

function Swatch({ label }) {
  return (
    <svg viewBox="0 0 28 10" width="28" height="10" aria-hidden="true">
      {label === "sun" && <line x1="3" y1="5" x2="25" y2="5" stroke="#e8892b" strokeWidth="6" strokeLinecap="round" />}
      {label === "shaded" && <>
        <line x1="3" y1="5" x2="25" y2="5" stroke="#16766f" strokeWidth="6" strokeLinecap="round" />
        <line x1="3" y1="5" x2="25" y2="5" stroke="#fff" strokeWidth="2" strokeDasharray="1 5" strokeLinecap="round" />
      </>}
      {label === "unknown" && <line x1="1" y1="5" x2="27" y2="5" stroke="#7b818c" strokeWidth="5" strokeDasharray="6 4" />}
      {label === "covered" && <>
        <line x1="3" y1="5" x2="25" y2="5" stroke="#6b4fc9" strokeWidth="8" strokeLinecap="round" />
        <line x1="3" y1="5" x2="25" y2="5" stroke="#fff" strokeWidth="2" />
      </>}
    </svg>
  );
}

export default function Legend() {
  return (
    <ul className="legend" aria-label="Map legend">
      {ITEMS.map((item) => <li key={item.label}><Swatch label={item.label} />{item.text}</li>)}
    </ul>
  );
}
