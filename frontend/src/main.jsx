import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { DomEvent } from "leaflet";
import { CircleMarker, MapContainer, Polyline, TileLayer, useMap, useMapEvents } from "react-leaflet";
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

function MapViewportController({ location }) {
  const map = useMap();

  useEffect(() => {
    if (location) {
      map.flyTo([location.latitude, location.longitude], Math.max(map.getZoom(), 16), { duration: 0.4 });
    }
  }, [location, map]);

  return null;
}

function RouteMap({ start, destination, location, routes, selectedRouteId, onMapClick, onRouteClick, mapTheme }) {
  return (
    <div className={`map-shell ${mapTheme}-map`}>
      <MapContainer center={MAP_CENTER} zoom={15} minZoom={14} maxZoom={18} zoomControl={false} className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapClickHandler onMapClick={onMapClick} />
        <MapViewportController location={location} />
        {location && <CircleMarker center={[location.latitude, location.longitude]} radius={7} pathOptions={{ color: "#ffffff", fillColor: "#2c9bd6", fillOpacity: 1, weight: 3 }} />}
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

function formatPoint(point) {
  return point ? `${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}` : "";
}

function parsePoint(value) {
  const parts = value.split(",").map((part) => Number(part.trim()));
  if (parts.length !== 2 || parts.some((part) => !Number.isFinite(part))) return null;
  return { latitude: parts[0], longitude: parts[1] };
}

function App() {
  const [start, setStart] = useState(null);
  const [destination, setDestination] = useState(null);
  const [startQuery, setStartQuery] = useState("");
  const [destinationQuery, setDestinationQuery] = useState("");
  const [location, setLocation] = useState(null);
  const [travelTime, setTravelTime] = useState(localDateTime);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [locationError, setLocationError] = useState("");
  const [loading, setLoading] = useState(false);
  const [mapTheme, setMapTheme] = useState("light");
  const [selectedRouteId, setSelectedRouteId] = useState(null);
  const [activeModal, setActiveModal] = useState(null);
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      const savedSearches = JSON.parse(localStorage.getItem("shades-recent-searches") || "[]");
      return Array.isArray(savedSearches) ? savedSearches : [];
    } catch {
      return [];
    }
  });

  function selectPoint({ lat, lng }) {
    const point = { latitude: Number(lat.toFixed(6)), longitude: Number(lng.toFixed(6)) };
    if (!start || destination) {
      setStart(point);
      setStartQuery(formatPoint(point));
      setDestination(null);
      setDestinationQuery("");
      setResult(null);
      return;
    }
    setDestination(point);
    setDestinationQuery(formatPoint(point));
  }

  function resetPoints() {
    setStart(null);
    setDestination(null);
    setStartQuery("");
    setDestinationQuery("");
    setResult(null);
    setError("");
  }

  function swapPoints() {
    setStartQuery(destinationQuery);
    setDestinationQuery(startQuery);
    setStart(destination);
    setDestination(start);
  }

  function applyPointQueries() {
    const parsedStart = parsePoint(startQuery);
    const parsedDestination = parsePoint(destinationQuery);
    if (!parsedStart || !parsedDestination) {
      setError("Enter both points as latitude, longitude or tap the map to set them.");
      return null;
    }
    setStart(parsedStart);
    setDestination(parsedDestination);
    return { parsedStart, parsedDestination };
  }

  async function requestRoutes(startPoint, destinationPoint) {
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await fetch("http://127.0.0.1:8000/api/routes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: startPoint, destination: destinationPoint, travel_time: travelTime }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "The route request failed.");
      setResult(body);
      setSelectedRouteId(body.routes[0]?.id || null);
      const recentSearch = { start: startQuery, destination: destinationQuery };
      const updatedSearches = [recentSearch, ...recentSearches.filter((item) => item.start !== recentSearch.start || item.destination !== recentSearch.destination)].slice(0, 3);
      setRecentSearches(updatedSearches);
      localStorage.setItem("shades-recent-searches", JSON.stringify(updatedSearches));
      setActiveModal("routes");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  function submitRoute(event) {
    event.preventDefault();
    const points = applyPointQueries();
    if (points) requestRoutes(points.parsedStart, points.parsedDestination);
  }

  function centerOnLocation() {
    if (!navigator.geolocation) {
      setLocationError("Location is not available in this browser.");
      return;
    }
    setLocationError("");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const currentLocation = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        setLocation(currentLocation);
        if (!startQuery) {
          setStart(currentLocation);
          setStartQuery(formatPoint(currentLocation));
        }
      },
      () => setLocationError("Location access was not granted."),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  }

  return (
    <main className={`navigation-shell ${mapTheme}-app`}>
      <RouteMap
        start={start}
        destination={destination}
        location={location}
        routes={result?.routes || []}
        selectedRouteId={selectedRouteId}
        onMapClick={selectPoint}
        onRouteClick={setSelectedRouteId}
        mapTheme={mapTheme}
      />

      <div className="map-wash" />
      <header className="topbar">
        <div className="brand-lockup"><span className="brand-mark">S</span><span><strong>SHADES</strong><small>Katipunan / ADMU</small></span></div>
        <div className="topbar-actions">
          <button type="button" className="map-theme-button" onClick={() => setMapTheme(mapTheme === "dark" ? "light" : "dark")}>{mapTheme === "dark" ? "Light" : "Dark"}</button>
        </div>
      </header>

      <button type="button" className="route-search-bar overlay-panel" onClick={() => setActiveModal("planner")} aria-label="Open route search">
        <span className="route-search-field"><small>From</small><strong>{startQuery || "Choose origin"}</strong></span>
        <span className="route-search-divider" />
        <span className="route-search-field"><small>To</small><strong>{destinationQuery || "Choose destination"}</strong></span>
        <span className="search-submit" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12h13M13 6l6 6-6 6" /></svg></span>
      </button>

      <div className="map-actions">
        {result && <button type="button" className="map-action-button result-action" onClick={() => setActiveModal("routes")}>Routes <span>{result.routes.length}</span></button>}
      </div>
      <button type="button" className="location-button" aria-label="Center on current location" title="Center on current location" onClick={centerOnLocation}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="5.5" /><path d="M12 2v4M12 18v4M2 12h4M18 12h4" /></svg>
      </button>

      {activeModal && <div className="modal-scrim" onClick={() => setActiveModal(null)}>
        {activeModal === "planner" && <section className="planner-popover" onClick={(event) => event.stopPropagation()}>
          <div className="planner-location-card overlay-panel">
            <div className="planner-popover-header"><div className="panel-kicker">Route</div><button type="button" className="close-button" aria-label="Close route details" onClick={() => setActiveModal(null)}>×</button></div>
            <div className="location-input-row"><span className="location-dot origin-dot" /><label><span>Origin</span><input value={startQuery} onChange={(event) => setStartQuery(event.target.value)} placeholder="Choose origin" aria-label="Origin" /></label><button type="button" className="swap-button" aria-label="Swap origin and destination" onClick={swapPoints}>↕</button></div>
            <div className="location-input-row"><span className="location-dot destination-dot" /><label><span>Destination</span><input value={destinationQuery} onChange={(event) => setDestinationQuery(event.target.value)} placeholder="Choose destination" aria-label="Destination" /></label></div>
            {recentSearches.length > 0 && <div className="recent-searches"><span className="panel-kicker">Recent searches</span>{recentSearches.slice(0, 3).map((search, index) => <button type="button" className="recent-search" key={`${search.start}-${search.destination}-${index}`} onClick={() => { setStartQuery(search.start); setDestinationQuery(search.destination); }}><span>{search.start}</span><strong>→</strong><span>{search.destination}</span></button>)}</div>}
          </div>
          <div className="planner-details-card overlay-panel">
            <div className="planner-popover-header"><div className="panel-kicker">When are you going?</div></div>
            <label className="time-field">Travel time<input type="datetime-local" value={travelTime} onChange={(event) => setTravelTime(event.target.value)} required /></label>
            <div className="temperature-card"><span>Temperature</span><strong>{result?.uv_context?.temperature_c != null ? `${result.uv_context.temperature_c}°C` : "Not available"}</strong></div>
            {error && <p className="error">{error}</p>}
            {locationError && <p className="error">{locationError}</p>}
            <div className="planner-actions">
              <button type="button" className="quiet-primary" disabled={loading} onClick={submitRoute}>{loading ? "Calculating..." : "Preview route"}</button>
              <button type="button" className="quiet-secondary" onClick={resetPoints}>Reset points</button>
            </div>
          </div>
        </section>}

        {activeModal === "routes" && <aside className="modal-sheet routes-sheet overlay-panel" aria-live="polite" onClick={(event) => event.stopPropagation()}>
          <div className="sheet-handle" />
          <div className="modal-header"><div><div className="panel-kicker">Available routes</div><h2>{result ? `${result.routes.length} ways to go` : "Your routes"}</h2></div><button type="button" className="close-button" aria-label="Close routes" onClick={() => setActiveModal(null)}>×</button></div>
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
        </aside>}
      </div>}

      <div className="map-legend"><span><i className="legend-dot start-dot" />Start</span><span><i className="legend-dot destination-dot" />Destination</span><span><i className="legend-line sun-line" />Sun</span><span className="shade-scale" aria-label="Least to most shaded"><small>Shade</small>{SHADE_COLORS.map((color) => <i key={color} style={{ backgroundColor: color }} />)}</span></div>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);