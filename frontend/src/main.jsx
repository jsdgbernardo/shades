import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./styles.css";

const API_URL = "http://127.0.0.1:8000";
const DEFAULT_START = { latitude: 14.6417, longitude: 121.0761 };
const DEFAULT_DESTINATION = null;
const MAP_CENTER = [14.6417, 121.0761];

function formatDistance(meters) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

function markerIcon(kind) {
  return L.divIcon({
    className: `map-marker map-marker--${kind}`,
    html: `<span></span>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

function MapView({ start, destination, routes, selectedId, onMapPick }) {
  const [map, setMap] = useState(null);

  useEffect(() => {
    const instance = L.map("map", { zoomControl: false }).setView(MAP_CENTER, 17);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(instance);
    instance.on("click", (event) => onMapPick(event.latlng));
    setMap(instance);
    return () => instance.remove();
  }, [onMapPick]);

  useEffect(() => {
    if (!map) return undefined;
    const layers = [];
    if (start) layers.push(L.marker([start.latitude, start.longitude], { icon: markerIcon("start") }).addTo(map));
    if (destination) layers.push(L.marker([destination.latitude, destination.longitude], { icon: markerIcon("destination") }).addTo(map));

    routes.forEach((route) => {
      const selected = route.id === selectedId;
      const segments = route.exposure?.segments ?? [];
      if (segments.length) {
        segments.forEach((segment) => {
          const color = segment.status === "shaded" ? "#3d8d78" : "#df7c37";
          layers.push(L.polyline(segment.geometry.map(([longitude, latitude]) => [latitude, longitude]), {
            color,
            weight: selected ? 7 : 4,
            opacity: selected ? 0.96 : 0.38,
            dashArray: segment.status === "shaded" ? undefined : "2 8",
            lineCap: "round",
          }).addTo(map));
        });
      } else {
        layers.push(L.polyline(route.geometry.map(([longitude, latitude]) => [latitude, longitude]), {
          color: selected ? "#df7c37" : "#9c9b96",
          weight: selected ? 6 : 3,
          opacity: selected ? 0.95 : 0.4,
        }).addTo(map));
      }
    });
    return () => layers.forEach((layer) => layer.remove());
  }, [map, start, destination, routes, selectedId]);

  return <div id="map" className="map" aria-label="Interactive walking map" />;
}

function ContextChip({ uvContext, travelTime }) {
  const hour = new Date(travelTime).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const temperature = uvContext?.temperature_c == null ? "34°" : `${Math.round(uvContext.temperature_c)}°`;
  if (!uvContext) {
    return (
      <div className="context-chip context-chip--reference">
        <span className="context-icon">◷</span><strong>Leave Now</strong>
        <span className="context-divider" />
        <span className="context-icon context-icon--thermometer" aria-hidden="true" /><strong>Feels like {temperature}</strong>
      </div>
    );
  }
  return (
    <div className="context-chip">
      <span className="context-icon">◷</span>
      <span><strong>{hour}</strong><small>Travel time</small></span>
      <span className="context-divider" />
      <span className="context-icon context-icon--sun">◌</span>
      <span><strong>{temperature}</strong><small>{uvContext?.category ?? "Weather"}</small></span>
    </div>
  );
}

function RouteCard({ route, selected, onSelect, comparison }) {
  const exposure = route.exposure ?? {};
  const sunPercent = exposure.sun_exposed_percent ?? 0;
  const sunMinutes = route.duration_minutes * sunPercent / 100;
  return (
    <button className={`route-card ${selected ? "route-card--selected" : ""}`} onClick={onSelect}>
      <div className="route-card__top">
        <div>
          <span className="route-label">{route.label}</span>
          {selected && <span className="recommended">Recommended</span>}
        </div>
        <span className="route-arrow">›</span>
      </div>
      <div className="route-stats">
        <div><strong>{Math.round(route.duration_minutes)} min</strong><small>{formatDistance(route.distance_m)}</small></div>
        <div><strong className={sunPercent < 50 ? "stat-good" : ""}>{Math.round(sunPercent)}%</strong><small>in direct sun</small></div>
        <div><strong>{Math.round(sunMinutes)} min</strong><small>sun exposure</small></div>
      </div>
      {comparison && <p className="route-note">{comparison}</p>}
    </button>
  );
}

function App() {
  const [start, setStart] = useState(DEFAULT_START);
  const [destination, setDestination] = useState(DEFAULT_DESTINATION);
  const [travelTime, setTravelTime] = useState(() => new Date().toISOString().slice(0, 16));
  const [routes, setRoutes] = useState([]);
  const [uvContext, setUvContext] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [inputMode, setInputMode] = useState("destination");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inputModeRef = useRef(inputMode);

  useEffect(() => {
    inputModeRef.current = inputMode;
  }, [inputMode]);

  const selectedRoute = routes.find((route) => route.id === selectedId) ?? routes[0];
  const comparison = useMemo(() => {
    if (routes.length < 2) return null;
    const difference = (routes[0].exposure?.sun_exposed_percent ?? 0) - (routes[1].exposure?.sun_exposed_percent ?? 0);
    return difference > 0 ? `${Math.round(difference)} percentage points less sun than the shortest route` : null;
  }, [routes]);

  const requestRoutes = async () => {
    if (!start || !destination) {
      setError("Tap the map to choose a destination first.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/routes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start, destination, travel_time: travelTime }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not calculate a route.");
      setRoutes(payload.routes ?? []);
      setSelectedId(payload.routes?.[0]?.id ?? null);
      setUvContext(payload.uv_context);
    } catch (requestError) {
      setError(requestError.message || "The route service is unavailable.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (destination) requestRoutes();
  }, [destination]);

  const handleMapPick = useCallback(({ lat, lng }) => {
    const point = { latitude: lat, longitude: lng };
    if (inputModeRef.current === "start") setStart(point);
    else setDestination(point);
    setRoutes([]);
  }, []);

  return (
    <main className="app-shell">
      <section className="phone">
        <MapView start={start} destination={destination} routes={routes} selectedId={selectedRoute?.id} onMapPick={handleMapPick} />
        <div className="map-wash" />
        <div className="search-card">
          <button className="location-field" onClick={() => setInputMode("start")}><svg className="field-icon field-icon--origin" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="6.5" /></svg><span className="field-content"><strong className={inputMode === "start" ? "field-active" : ""}>{start ? "Your Location" : "Your Location"}</strong></span></button>
          <span className="swap-icon" aria-hidden="true">⇅</span>
          <button className="location-field" onClick={() => setInputMode("destination")}><svg className="field-icon field-icon--destination" viewBox="0 0 18 22" aria-hidden="true"><path d="M9 20.25S2.5 13.45 2.5 8.9a6.5 6.5 0 1 1 13 0c0 4.55-6.5 11.35-6.5 11.35Z" /><circle cx="9" cy="8.9" r="2.25" /></svg><span className="field-content"><strong className={inputMode === "destination" ? "field-active" : ""}>Destination</strong></span></button>
        </div>
        <ContextChip uvContext={uvContext} travelTime={travelTime} />
        <button className="recenter" onClick={() => window.dispatchEvent(new Event("resize"))} aria-label="Recenter map">⌖</button>
        {routes.length > 0 && <div className="legend"><span><i className="legend-line legend-line--shade" /> Shaded</span><span><i className="legend-line legend-line--sun" /> Direct sun</span></div>}
        <section className={`route-sheet ${routes.length ? "route-sheet--results" : "route-sheet--planner"}`}>
          <div className="sheet-handle" />
          {routes.length === 0 ? (
            <div className="planner">
              <p className="eyebrow">PLAN A COOLER WALK</p>
              <h1>Find a little more shade.</h1>
              <p className="intro">Compare walking routes around Katipunan and Ateneo based on the sun at the time you leave.</p>
              <label className="time-field">Leave at<input type="datetime-local" value={travelTime} onChange={(event) => setTravelTime(event.target.value)} /></label>
              <button className="primary-button" onClick={requestRoutes} disabled={loading}>{loading ? "Finding routes..." : "Preview routes"} <span>→</span></button>
              {error && <p className="error">{error}</p>}
            </div>
          ) : (
            <div className="results">
              <div className="results-header"><div><p className="eyebrow">YOUR ROUTES</p><h2>{routes.length} ways to get there</h2></div><button className="text-button" onClick={() => setRoutes([])}>Edit</button></div>
              <p className="route-summary">At {new Date(travelTime).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}, your selected route is <strong>{selectedRoute?.exposure?.rating?.toLowerCase() ?? "computed"}</strong>.</p>
              {routes.map((route, index) => <RouteCard key={route.id} route={route} selected={route.id === selectedRoute?.id} onSelect={() => setSelectedId(route.id)} comparison={index === 1 ? comparison : null} />)}
              <button className="primary-button primary-button--small" onClick={requestRoutes}>Refresh for this time <span>↻</span></button>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
