import { useCallback, useEffect, useRef, useState } from "react";
import MapView from "./components/MapView.jsx";
import LocationCard from "./components/LocationCard.jsx";
import TimePill from "./components/TimePill.jsx";
import RouteSheet from "./components/RouteSheet.jsx";
import Legend from "./components/Legend.jsx";
import { LocateIcon } from "./components/Icons.jsx";
import StreetPanel from "./components/StreetPanel.jsx";
import { ConnectionError, fetchCovered, fetchNearestStreet, fetchRoutes, fetchWeather, rateStreet, setCovered } from "./lib/api.js";
import { isOffRoute, projectOntoRoute, remainingFigures } from "./lib/geo.js";
import { MAX_ACCURACY_METERS, geolocation, locationProblem } from "./lib/location.js";
import { toInputValue, toOffsetIso } from "./lib/time.js";

const STUDY_AREA = { south: 14.635, north: 14.65, west: 121.065, east: 121.083 };
const inStudyArea = (latitude, longitude) =>
  latitude >= STUDY_AREA.south && latitude <= STUDY_AREA.north && longitude >= STUDY_AREA.west && longitude <= STUDY_AREA.east;
const OUTSIDE_MESSAGE = "That point is outside the Katipunan test area. Choose a point inside it.";
const GPS_OPTIONS = { enableHighAccuracy: true, timeout: 10_000, maximumAge: 0 };

export default function App() {
  const mapRef = useRef(null);
  const [start, setStart] = useState(null);
  const [destination, setDestination] = useState(null);
  const [activeField, setActiveField] = useState("destination");
  const [leaveNow, setLeaveNow] = useState(true);
  const [travelInput, setTravelInput] = useState(() => toInputValue());
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [weather, setWeather] = useState(null);
  const [message, setMessage] = useState("");
  const [online, setOnline] = useState(() => navigator.onLine);
  const [walk, setWalk] = useState({ active: false });
  const [userPosition, setUserPosition] = useState(null);
  const [offRoute, setOffRoute] = useState(null);
  const [streetMode, setStreetMode] = useState(false);
  const [street, setStreet] = useState(null);
  const [streetBusy, setStreetBusy] = useState(false);
  const [streetNotice, setStreetNotice] = useState("");
  const [covered, setCoveredSections] = useState([]);
  const requestCounter = useRef(0);
  const selectedRouteRef = useRef(null);
  const positionRef = useRef(null);
  const promptDismissedRef = useRef(false);

  const selectedRoute = data?.routes?.find((route) => route.id === selectedId) ?? data?.routes?.[0] ?? null;
  selectedRouteRef.current = selectedRoute;

  const travelTime = useCallback(
    () => toOffsetIso(leaveNow ? toInputValue(new Date()) : travelInput),
    [leaveNow, travelInput],
  );

  // Connection state (PRD O-03).
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); };
  }, []);

  // Current location as the default start (PRD S-12, E-04).
  const locate = useCallback((setAsStart) => {
    const geo = geolocation();
    if (!geo) { setMessage(locationProblem({ code: 2 })); return; }
    geo.getCurrentPosition(
      (position) => {
        const { latitude, longitude, accuracy } = position.coords;
        if (accuracy > MAX_ACCURACY_METERS) { setMessage(locationProblem({ code: "accuracy", accuracy })); return; }
        if (!inStudyArea(latitude, longitude)) { setMessage(locationProblem({ code: "outside" })); return; }
        setMessage("");
        mapRef.current?.panTo(latitude, longitude);
        if (setAsStart) setStart({ latitude, longitude, source: "gps" });
      },
      (failure) => setMessage(locationProblem(failure)),
      { ...GPS_OPTIONS, maximumAge: 30_000 },
    );
  }, []);

  useEffect(() => { locate(true); }, [locate]);

  const loadRoutes = useCallback(async () => {
    if (!start || !destination) { setStatus("idle"); setData(null); return; }
    const id = ++requestCounter.current;
    setStatus("loading");
    setError("");
    try {
      const payload = await fetchRoutes({
        start: { latitude: start.latitude, longitude: start.longitude },
        destination: { latitude: destination.latitude, longitude: destination.longitude },
        travelTime: travelTime(),
      });
      if (id !== requestCounter.current) return;
      setOnline(true);
      setData(payload);
      setWeather(payload.weather);
      setSelectedId((previous) => (payload.routes.some((route) => route.id === previous) ? previous : payload.routes.at(-1).id));
      setStatus("results");
      mapRef.current?.fitGeometry(payload.routes.flatMap((route) => route.geometry));
    } catch (failure) {
      if (id !== requestCounter.current) return;
      if (failure instanceof ConnectionError) setOnline(false);
      setData(null);
      setStatus("error");
      setError(failure.message);
    }
  }, [start, destination, travelTime]);

  useEffect(() => { loadRoutes(); }, [loadRoutes]);

  // Temperature and heat index for the pill before any route is requested.
  useEffect(() => {
    let cancelled = false;
    fetchWeather(travelTime()).then((payload) => { if (!cancelled) setWeather(payload.weather); }).catch(() => {});
    return () => { cancelled = true; };
  }, [travelTime]);

  // Covered marks shared by all users (PRD S-10, D-03).
  const loadCovered = useCallback(() => {
    fetchCovered().then((payload) => setCoveredSections(payload.covered ?? [])).catch(() => {});
  }, []);
  useEffect(() => { loadCovered(); }, [loadCovered]);

  const pickStreet = async (latitude, longitude) => {
    setStreetNotice("");
    try {
      setStreet(await fetchNearestStreet(latitude, longitude));
    } catch (failure) {
      setStreet(null);
      setStreetNotice(failure.message);
    }
  };

  const rate = async (value) => {
    setStreetBusy(true);
    try {
      const updated = await rateStreet(street.way_id, value);
      setStreet((current) => ({ ...current, walkability: updated.walkability }));
      setStreetNotice(`Thanks. You rated ${updated.name} ${value} out of 5.`);
      loadRoutes();
    } catch (failure) {
      setStreetNotice(failure.message);
    } finally {
      setStreetBusy(false);
    }
  };

  const toggleCovered = async () => {
    const next = !street.section.covered;
    setStreetBusy(true);
    try {
      await setCovered(street.section.edge_key, next);
      setStreet((current) => ({ ...current, section: { ...current.section, covered: next } }));
      setStreetNotice(next ? "Marked as covered. Routes through it now count it as shaded." : "Covered mark removed.");
      loadCovered();
      loadRoutes();
    } catch (failure) {
      setStreetNotice(failure.message);
    } finally {
      setStreetBusy(false);
    }
  };

  const closeStreetMode = () => { setStreetMode(false); setStreet(null); setStreetNotice(""); };

  const handleMapPick = useCallback(({ lat, lng }) => {
    if (!inStudyArea(lat, lng)) { setMessage(OUTSIDE_MESSAGE); return; }
    setMessage("");
    if (streetMode) { pickStreet(lat, lng); return; }
    const point = { latitude: lat, longitude: lng, source: "map" };
    if (activeField === "start") {
      setStart(point);
      setActiveField("destination");
    } else {
      setDestination(point);
    }
  }, [activeField, streetMode]);

  const handlePick = (field, place) => {
    const point = { latitude: place.latitude, longitude: place.longitude, name: place.name, source: "search" };
    setMessage("");
    if (field === "start") { setStart(point); setActiveField("destination"); } else { setDestination(point); }
    mapRef.current?.panTo(place.latitude, place.longitude);
  };

  const swap = () => { setStart(destination); setDestination(start); };

  // Live walk: position marker and figures for the route still ahead (PRD F-13, F-14, C-06).
  const handlePosition = useCallback((position) => {
    const { latitude, longitude, accuracy } = position.coords;
    const route = selectedRouteRef.current;
    positionRef.current = { latitude, longitude };
    setUserPosition({ latitude, longitude });
    if (!route) return;
    const projection = projectOntoRoute([longitude, latitude], route.geometry);
    const remaining = remainingFigures(route.exposure.sections, projection.along);
    setWalk((current) => (current.active ? {
      ...current,
      remaining,
      updatedAt: Date.now(),
      message: accuracy > MAX_ACCURACY_METERS ? `Your location is imprecise (about ±${Math.round(accuracy)} m).` : "",
    } : current));
    if (isOffRoute(projection.distanceFromRoute)) {
      if (!promptDismissedRef.current) setOffRoute({ distance: projection.distanceFromRoute });
    } else {
      promptDismissedRef.current = false;
      setOffRoute(null);
    }
  }, []);

  useEffect(() => {
    if (!walk.active) return undefined;
    const geo = geolocation();
    if (!geo) return undefined;
    let watchId = null;
    let timer = null;
    const failure = (problem) => setWalk((current) => ({ ...current, message: locationProblem(problem) }));
    const begin = () => {
      if (watchId !== null) return;
      watchId = geo.watchPosition(handlePosition, failure, GPS_OPTIONS);
      // Some devices only report on movement; poll so the marker refreshes at least every 5 s.
      timer = setInterval(() => geo.getCurrentPosition(handlePosition, () => {}, { ...GPS_OPTIONS, timeout: 4_000 }), 5_000);
    };
    const end = () => {
      if (watchId !== null) geo.clearWatch(watchId);
      clearInterval(timer);
      watchId = null;
      timer = null;
    };
    const onVisibility = () => (document.hidden ? end() : begin());
    if (!document.hidden) begin();
    document.addEventListener("visibilitychange", onVisibility);
    return () => { end(); document.removeEventListener("visibilitychange", onVisibility); };
  }, [walk.active, handlePosition]);

  const startWalk = () => { promptDismissedRef.current = false; setWalk({ active: true, remaining: null, message: "" }); };
  const stopWalk = () => { setWalk({ active: false }); setUserPosition(null); setOffRoute(null); positionRef.current = null; };

  const acceptReroute = () => {
    if (positionRef.current) setStart({ ...positionRef.current, source: "gps" });
    setOffRoute(null);
  };
  const declineReroute = () => { promptDismissedRef.current = true; setOffRoute(null); };

  const locateButton = () => {
    if (walk.active && userPosition) mapRef.current?.panTo(userPosition.latitude, userPosition.longitude);
    else locate(!start);
  };

  return (
    <main className="app-shell">
      <section className="phone">
        <MapView
          ref={mapRef}
          start={start}
          destination={destination}
          routes={data?.routes ?? []}
          selectedId={selectedRoute?.id}
          userPosition={userPosition}
          coveredSections={covered}
          highlight={streetMode ? street?.section?.geometry : null}
          streetMode={streetMode}
          onMapPick={handleMapPick}
          onSelectRoute={setSelectedId}
        />
        {!online && <div className="offline-banner" role="alert">No connection. Routes and weather need the internet.</div>}
        <div className="top-controls">
          <LocationCard
            start={start}
            destination={destination}
            activeField={activeField}
            onActivate={setActiveField}
            onPick={handlePick}
            onSwap={swap}
            onUseLocation={() => locate(true)}
          />
          <TimePill
            leaveNow={leaveNow}
            travelInput={travelInput}
            weather={weather}
            onChangeTime={(value) => { setTravelInput(value); setLeaveNow(false); }}
            onLeaveNow={() => { setTravelInput(toInputValue()); setLeaveNow(true); }}
          />
        </div>
        <div className="bottom-stack">
        <div className="bottom-stack__row">
          {status === "results" ? <Legend /> : <span />}
          <button type="button" className="locate-button" onClick={locateButton} aria-label="Show my location"><LocateIcon /></button>
        </div>
        <RouteSheet
          status={status}
          error={error}
          message={message}
          data={data}
          selectedId={selectedRoute?.id}
          onSelect={setSelectedId}
          onRetry={loadRoutes}
          walk={walk}
          onStartWalk={startWalk}
          onStopWalk={stopWalk}
        >
          {streetMode ? (
            <StreetPanel street={street} busy={streetBusy} notice={streetNotice} onRate={rate} onToggleCovered={toggleCovered} onClose={closeStreetMode} />
          ) : (
            <button type="button" className="more-button more-button--quiet" onClick={() => setStreetMode(true)}>
              Rate a street or mark a covered walkway
            </button>
          )}
        </RouteSheet>
        </div>
        {offRoute && (
          <div className="dialog-backdrop">
            <div className="dialog" role="alertdialog" aria-labelledby="off-route-title">
              <h2 id="off-route-title">You have left the route</h2>
              <p>You are about {Math.round(offRoute.distance)} m from it. Calculate a new route from where you are now?</p>
              <div className="dialog__actions">
                <button type="button" className="text-button" onClick={declineReroute}>Keep this route</button>
                <button type="button" className="solid-button" onClick={acceptReroute}>Recalculate</button>
              </div>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
