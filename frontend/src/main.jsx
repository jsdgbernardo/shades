import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { DomEvent } from "leaflet";
import { CircleMarker, MapContainer, Polyline, TileLayer, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./styles.css";

const MAP_CENTER = [14.6407, 121.0748];
const SHADE_COLORS = ["#d9f0f2", "#9fd5d1", "#5fafa8", "#2d7f80", "#1f4f5a"];
const LIGHT_SHADE_COLORS = ["#5fafa8", "#3f8f8e", "#2d7277", "#1f5964", "#16414e"];
const SUN_COLOR = "#f6c15a";
const LIGHT_SUN_COLOR = "#a66a18";
const START_COLOR = "#ffe19a";
const DESTINATION_COLOR = "#d78232";

function localDateTime() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 16);
}

function MapClickHandler({ onMapClick }) {
  useMapEvents({
    click: (event) => {
      if (event.originalEvent?.target?.classList?.contains("leaflet-interactive")) return;
      onMapClick(event.latlng);
    },
  });
  return null;
}

function RouteMap({ start, destination, routes, selectedRouteId, onMapClick, onRouteClick, mapTheme }) {
  return (
    <div className={`map-shell ${mapTheme}-map`}>
      <MapContainer center={MAP_CENTER} zoom={15} minZoom={14} maxZoom={18} className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapClickHandler onMapClick={onMapClick} />
        {start && <CircleMarker center={[start.latitude, start.longitude]} radius={9} pathOptions={{ color: START_COLOR, fillColor: START_COLOR, fillOpacity: 1 }} />}
        {destination && <CircleMarker center={[destination.latitude, destination.longitude]} radius={9} pathOptions={{ color: DESTINATION_COLOR, fillColor: DESTINATION_COLOR, fillOpacity: 1 }} />}
        {routes.flatMap((route) => (route.exposure?.segments || []).map((segment, index) => (
          <Polyline
            key={`${route.id}-${index}`}
            positions={segment.geometry.map(([longitude, latitude]) => [latitude, longitude])}
            eventHandlers={{ click: (event) => { DomEvent.stopPropagation(event.originalEvent); onRouteClick(route.id); } }}
            pathOptions={{
              color: segment.status === "sun-exposed" ? (mapTheme === "light" ? LIGHT_SUN_COLOR : SUN_COLOR) : (mapTheme === "light" ? LIGHT_SHADE_COLORS : SHADE_COLORS)[Math.min(SHADE_COLORS.length - 1, Math.max(0, (segment.shade_level ?? 1) - 1))],
              opacity: selectedRouteId === route.id ? 1 : mapTheme === "light" ? 0.8 : 0.5,
              weight: selectedRouteId === route.id ? 8 : 5,
            }}
          />
        )))}
      </MapContainer>
    </div>
  );
}

function App() {
  const [start, setStart] = useState(null);
  const [destination, setDestination] = useState(null);
  const [travelTime, setTravelTime] = useState(localDateTime);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [mapTheme, setMapTheme] = useState("dark");
  const [selectedRouteId, setSelectedRouteId] = useState(null);
  const [plannerMinimized, setPlannerMinimized] = useState(false);
  const [routesMinimized, setRoutesMinimized] = useState(false);

  function selectPoint({ lat, lng }) {
    const point = { latitude: Number(lat.toFixed(6)), longitude: Number(lng.toFixed(6)) };
    if (!start || destination) {
      setStart(point);
      setDestination(null);
      setResult(null);
      return;
    }
    setDestination(point);
  }

  function resetPoints() {
    setStart(null);
    setDestination(null);
    setResult(null);
    setError("");
  }

  async function submitRoute(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await fetch("http://127.0.0.1:8000/api/routes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start, destination, travel_time: travelTime }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "The route request failed.");
      setResult(body);
      setSelectedRouteId(body.routes[0]?.id || null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={`navigation-shell ${mapTheme}-app`}>
      <RouteMap
        start={start}
        destination={destination}
        routes={result?.routes || []}
        selectedRouteId={selectedRouteId}
        onMapClick={selectPoint}
        onRouteClick={setSelectedRouteId}
        mapTheme={mapTheme}
      />

      <div className="map-wash" />
      <header className="topbar">
        <div className="brand-lockup"><span className="brand-mark">S</span><span><strong>SHADES</strong><small>Katipunan / ADMU</small></span></div>
        <button type="button" className="map-theme-button" onClick={() => setMapTheme(mapTheme === "dark" ? "light" : "dark")}>{mapTheme === "dark" ? "Light mode" : "Dark mode"}</button>
      </header>

      <form onSubmit={submitRoute} className="planner-panel overlay-panel">
        <div className="panel-header"><div className="panel-kicker">Route planner</div><button type="button" className="panel-toggle" aria-label={plannerMinimized ? "Expand route planner" : "Minimize route planner"} title={plannerMinimized ? "Expand route planner" : "Minimize route planner"} onClick={() => setPlannerMinimized(!plannerMinimized)}>{plannerMinimized ? "+" : "−"}</button></div>
        {!plannerMinimized && <>
          <h1>Walk in the shade.</h1>
          <p className="panel-copy">Choose two points on the map to compare sun exposure.</p>
          <div className="selection-status">
            <div><span className="point-dot start-dot" />Start <strong>{start ? "Selected" : "Click the map"}</strong></div>
            <div><span className="point-dot destination-dot" />Destination <strong>{destination ? "Selected" : "Click the map"}</strong></div>
          </div>
          <label>
            Travel time
            <input type="datetime-local" value={travelTime} onChange={(event) => setTravelTime(event.target.value)} required />
          </label>
          <button type="submit" disabled={loading || !start || !destination}>{loading ? "Calculating..." : "Preview route"}</button>
          <button type="button" className="secondary-button" onClick={resetPoints}>Reset selection</button>
          <p className="hint">Click once for start and again for destination. A third click begins a new selection.</p>
        </>}
      </form>

      <aside className="routes-panel overlay-panel" aria-live="polite">
        <div className="routes-heading"><div><div className="panel-kicker">Available routes</div><h2>{result ? `${result.routes.length} ways to go` : "Your routes"}</h2></div><div className="routes-heading-actions"><span className="route-count">{result ? "LIVE" : "READY"}</span><button type="button" className="panel-toggle" aria-label={routesMinimized ? "Expand route options" : "Minimize route options"} title={routesMinimized ? "Expand route options" : "Minimize route options"} onClick={() => setRoutesMinimized(!routesMinimized)}>{routesMinimized ? "+" : "−"}</button></div></div>
        {!routesMinimized && <>
          {!result && !error && <p className="empty-state">Your route options will appear here.</p>}
          {error && <p className="error">{error}</p>}
          {result && <>
          <p className="result-note">{result.message}</p>
          <div className="uv-context"><div><span className="panel-kicker">UV context</span><strong>{result.uv_context?.status === "available" ? `UV ${result.uv_context.index}` : "Unavailable"}</strong></div><small>{result.uv_context?.status === "available" ? `${result.uv_context.category} · ${result.uv_context.source}` : result.uv_context?.message}</small><em>Context only, not a shade measurement.</em></div>
          <div className="route-list">
            {result.routes.map((route, index) => (
              <button type="button" className={`route-option ${selectedRouteId === route.id ? "selected" : ""}`} key={route.id} onClick={() => setSelectedRouteId(route.id)}>
                <span className="route-number">0{index + 1}</span>
                <span className="route-option-main"><strong>{route.label}</strong><small>{route.distance_m} m · {route.duration_minutes} min</small></span>
                <span className="route-option-score"><strong>{route.exposure.shaded_percent}%</strong><small>shade</small></span>
              </button>
            ))}
          </div>
          {selectedRouteId && (() => {
            const route = result.routes.find((item) => item.id === selectedRouteId);
            return route ? <div className="route-detail"><span className="panel-kicker">Selected route</span><h3>{route.label}</h3><div className="detail-grid"><div><strong>{route.exposure.shaded_percent}%</strong><small>shaded</small></div><div><strong>{route.exposure.sun_exposed_percent}%</strong><small>sun-exposed</small></div><div><strong>{route.distance_m} m</strong><small>distance</small></div></div></div> : null;
          })()}
          </>}
        </>}
      </aside>

      <div className="map-legend"><span><i className="legend-dot start-dot" />Start</span><span><i className="legend-dot destination-dot" />Destination</span><span><i className="legend-line sun-line" />Sun</span><span className="shade-scale" aria-label="Least to most shaded"><small>Shade</small>{SHADE_COLORS.map((color) => <i key={color} style={{ backgroundColor: color }} />)}</span></div>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);