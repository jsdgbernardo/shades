import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "./components/MapView.jsx";
import LocationCard from "./components/LocationCard.jsx";
import TimePill from "./components/TimePill.jsx";
import RouteSheet from "./components/RouteSheet.jsx";
import Legend from "./components/Legend.jsx";
import { LocateIcon } from "./components/Icons.jsx";
import StreetModal from "./components/StreetPanel.jsx";
import { ConnectionError, fetchNearestStreet, fetchRoutes, fetchWeather, rateStreet, setCovered } from "./lib/api.js";
import { isOffRoute, projectOntoRoute, remainingFigures } from "./lib/geo.js";
import { arrivalSummary, buildManeuvers, cumulative, hasArrived, headingAt, nextManeuver } from "./lib/nav.js";
import { ArrivalCard, NavBanner, NavBar } from "./components/NavPanel.jsx";
import { MAX_ACCURACY_METERS, geolocation, locationProblem } from "./lib/location.js";
import { toInputValue, toOffsetIso } from "./lib/time.js";

const STUDY_AREA = { south: 14.635, north: 14.65, west: 121.065, east: 121.083 };
const inStudyArea = (latitude, longitude) =>
  latitude >= STUDY_AREA.south && latitude <= STUDY_AREA.north && longitude >= STUDY_AREA.west && longitude <= STUDY_AREA.east;
const GPS_OPTIONS = { enableHighAccuracy: true, timeout: 10_000, maximumAge: 0 };

export default function App() {
  const mapRef = useRef(null);
  const phoneRef = useRef(null);
  const topControlsRef = useRef(null);
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
  const [locationUsable, setLocationUsable] = useState(true);
  const [online, setOnline] = useState(() => navigator.onLine);
  const [walk, setWalk] = useState({ active: false });
  const [userPosition, setUserPosition] = useState(null);
  const [offRoute, setOffRoute] = useState(null);
  // Tapped street or route section shown in the modal: { section, street, loading }.
  const [tap, setTap] = useState(null);
  const [streetBusy, setStreetBusy] = useState(false);
  const [streetNotice, setStreetNotice] = useState("");
  const requestCounter = useRef(0);
  const selectedRouteRef = useRef(null);
  const positionRef = useRef(null);
  const promptDismissedRef = useRef(false);

  const selectedRoute = data?.routes?.find((route) => route.id === selectedId) ?? data?.routes?.[0] ?? null;
  // Which comfort-window time the map shows for the selected route: 0 (now), 15 or 30 minutes.
  const [timeOffset, setTimeOffset] = useState(0);
  const selectedRouteId = selectedRoute?.id;
  const mapRoutes = useMemo(() => (data?.routes ?? []).map((route) => {
    if (route.id !== selectedRouteId || timeOffset === 0) return route;
    const entry = route.comfort_window?.times?.find((time) => time.offset_minutes === timeOffset);
    return entry?.exposure ? { ...route, exposure: entry.exposure } : route;
  }), [data, selectedRouteId, timeOffset]);
  // Covered marks are not drawn on their own; they show as part of a route that uses them.
  // The one exception is the street section open in the street card, so a new mark is
  // visible on the map as soon as it is saved (PRD S-10).
  const openSection = tap?.street?.section;
  const openCoveredSection = useMemo(() => (openSection?.covered ? [openSection] : []), [openSection]);
  // Legend lists only the styles on the map: the selected route's sections (at the chosen time)
  // plus the open covered section, if any.
  const legendLabels = useMemo(() => {
    const labels = new Set(mapRoutes.find((route) => route.id === selectedRouteId)?.exposure?.sections?.map((section) => section.label) ?? []);
    if (openCoveredSection.length) labels.add("covered");
    return labels;
  }, [mapRoutes, selectedRouteId, openCoveredSection.length]);
  selectedRouteRef.current = selectedRoute;
  // Manoeuvres for the selected route, used for turn-by-turn during the walk.
  const routeNav = useMemo(() => {
    if (!selectedRoute) return { maneuvers: [], distances: [0], total: 0 };
    const distances = cumulative(selectedRoute.geometry);
    return { maneuvers: buildManeuvers(selectedRoute.geometry, selectedRoute.edges), distances, total: distances[distances.length - 1] };
  }, [selectedRoute]);
  const routeNavRef = useRef(routeNav);
  routeNavRef.current = routeNav;

  const travelTime = useCallback(
    () => toOffsetIso(leaveNow ? toInputValue(new Date()) : travelInput),
    [leaveNow, travelInput],
  );

  // Keep the bottom sheet below the top cards at every window size.
  useEffect(() => {
    const phone = phoneRef.current;
    const top = topControlsRef.current;
    if (!phone || !top || typeof ResizeObserver === "undefined") return undefined;
    const update = () => {
      const clearance = top.getBoundingClientRect().bottom - phone.getBoundingClientRect().top + 10;
      phone.style.setProperty("--top-clearance", `${Math.ceil(clearance)}px`);
    };
    const observer = new ResizeObserver(update);
    observer.observe(top);
    observer.observe(phone);
    update();
    return () => observer.disconnect();
  }, []);

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
    // When location can't be used, the start field asks for an "Origin" instead of promising "Your Location".
    const fail = (problem) => { setMessage(locationProblem(problem)); setLocationUsable(false); };
    if (!geo) { fail({ code: 2 }); return; }
    geo.getCurrentPosition(
      (position) => {
        const { latitude, longitude, accuracy } = position.coords;
        if (accuracy > MAX_ACCURACY_METERS) { fail({ code: "accuracy", accuracy }); return; }
        if (!inStudyArea(latitude, longitude)) { fail({ code: "outside" }); return; }
        setMessage("");
        setLocationUsable(true);
        mapRef.current?.panTo(latitude, longitude);
        if (setAsStart) setStart({ latitude, longitude, source: "gps" });
      },
      fail,
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
      setTimeOffset(0);
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

  // Routes are computed only when the user asks (Find routes). Changing the start, destination
  // or time clears old results; accepting a reroute during a walk computes straight away.
  const autoComputeRef = useRef(false);
  useEffect(() => {
    if (autoComputeRef.current) {
      autoComputeRef.current = false;
      loadRoutes();
      return;
    }
    requestCounter.current += 1; // ignore any request still in flight for the old inputs
    setData(null);
    setStatus("idle");
    setError("");
    setWalk({ active: false });
    setUserPosition(null);
    setOffRoute(null);
    setArrival(null);
  }, [loadRoutes]);

  // Temperature and heat index for the pill before any route is requested.
  useEffect(() => {
    let cancelled = false;
    fetchWeather(travelTime()).then((payload) => { if (!cancelled) setWeather(payload.weather); }).catch(() => {});
    return () => { cancelled = true; };
  }, [travelTime]);


  // Tapping a route section or any street opens the street modal (PRD I-01, S-08, S-10).
  const tapCounter = useRef(0);
  const handleTap = useCallback(async ({ lat, lng }, section) => {
    if (!inStudyArea(lat, lng)) return;
    const id = ++tapCounter.current;
    setStreetNotice("");
    // A route section opens at once with its reason; a plain map tap opens only if a street is near.
    if (section) setTap({ section, street: null, loading: true });
    try {
      const street = await fetchNearestStreet(lat, lng);
      if (id === tapCounter.current) setTap({ section, street, loading: false });
    } catch {
      if (id !== tapCounter.current) return;
      if (section) setTap({ section, street: null, loading: false });
    }
  }, []);

  const street = tap?.street ?? null;
  const setStreet = (update) => setTap((current) => (current ? { ...current, street: update(current.street) } : current));

  const rate = async (value) => {
    setStreetBusy(true);
    try {
      const updated = await rateStreet(street.way_id, value);
      setStreet((current) => ({ ...current, walkability: updated.walkability }));
      setStreetNotice(`Thanks. You rated ${updated.name} ${value} out of 5.`);
      if (data) loadRoutes(); // refresh routes already shown; never start a new search
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
      if (data) loadRoutes();
    } catch (failure) {
      setStreetNotice(failure.message);
    } finally {
      setStreetBusy(false);
    }
  };

  const closeTap = useCallback(() => { tapCounter.current += 1; setTap(null); setStreetNotice(""); }, []);

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
    // Turn-by-turn and course-up heading, from the route itself (works while standing still).
    const nav = routeNavRef.current;
    const heading = headingAt(route.geometry, projection.along, nav.distances);
    const maneuver = nextManeuver(nav.maneuvers, projection.along, nav.total);
    // Arrived: within 15 m of the end while on the route. End the walk and show the summary.
    if (!isOffRoute(projection.distanceFromRoute) && hasArrived(remaining.distance_m)) {
      arriveRef.current?.(route);
      return;
    }
    setWalk((current) => (current.active ? {
      ...current,
      remaining,
      heading,
      maneuver,
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
    // Losing GPS drops back from navigation to the normal sheet (with the message) instead of
    // freezing the rotated map on an old fix.
    // A timeout (code 3) can just mean the walker is standing still, so it keeps navigation.
    const failure = (problem) => {
      if (problem?.code === 3) return;
      setUserPosition(null);
      positionRef.current = null;
      setWalk((current) => ({ ...current, message: locationProblem(problem) }));
    };
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

  const startWalk = () => {
    promptDismissedRef.current = false;
    closeTap();
    setArrival(null);
    setWalk({ active: true, remaining: null, message: "", startedAt: Date.now() });
  };
  // Navigation view only once the walk has a GPS fix; otherwise the normal sheet shows "Locating…".
  const navigation = walk.active && userPosition && walk.remaining && walk.heading != null
    ? { latitude: userPosition.latitude, longitude: userPosition.longitude, heading: walk.heading }
    : null;
  const stopWalk = () => {
    setWalk({ active: false });
    setUserPosition(null);
    setOffRoute(null);
    positionRef.current = null;
    // Back from the rotated navigation view: show the whole route again once the map has reset.
    const geometry = selectedRouteRef.current?.geometry;
    if (geometry) setTimeout(() => mapRef.current?.fitGeometry(geometry), 60);
  };

  // Arrival: stop following GPS, leave the navigation view and show a short summary.
  const [arrival, setArrival] = useState(null);
  const arriveRef = useRef(null);
  arriveRef.current = (route) => {
    if (!walk.active) return;
    setArrival({ ...arrivalSummary(route, walk.startedAt ?? Date.now()), place: destination?.name ?? null });
    stopWalk();
  };

  const acceptReroute = () => {
    if (positionRef.current) {
      autoComputeRef.current = true; // the user just asked to recalculate
      setStart({ ...positionRef.current, source: "gps" });
    }
    setOffRoute(null);
  };
  const declineReroute = () => { promptDismissedRef.current = true; setOffRoute(null); };

  const locateButton = () => {
    if (walk.active && userPosition) mapRef.current?.panTo(userPosition.latitude, userPosition.longitude);
    else locate(!start);
  };

  return (
    <main className="app-shell">
      <section className="phone" ref={phoneRef}>
        <MapView
          ref={mapRef}
          start={start}
          destination={destination}
          routes={mapRoutes}
          selectedId={selectedRoute?.id}
          userPosition={userPosition}
          coveredSections={openCoveredSection}
          highlight={street?.section?.geometry ?? null}
          navigation={navigation}
          onTap={handleTap}
          onSelectRoute={setSelectedId}
        />
        {!online && <div className="offline-banner" role="alert">No connection. Routes and weather need the internet.</div>}
        {navigation && <div className="nav-attribution">© OpenStreetMap contributors</div>}
        <div className="top-controls" ref={topControlsRef}>
          {navigation ? <NavBanner maneuver={walk.maneuver} /> : <>
          <LocationCard
            start={start}
            destination={destination}
            activeField={activeField}
            onActivate={setActiveField}
            onPick={handlePick}
            onSwap={swap}
            onUseLocation={() => locate(true)}
            locationUsable={locationUsable}
          />
          <TimePill
            leaveNow={leaveNow}
            travelInput={travelInput}
            weather={weather}
            onChangeTime={(value) => { setTravelInput(value); setLeaveNow(false); }}
            onLeaveNow={() => { setTravelInput(toInputValue()); setLeaveNow(true); }}
          />
          </>}
        </div>
        <RouteSheet
          status={status}
          error={error}
          message={message}
          onDismissMessage={() => setMessage("")}
          data={data}
          selectedId={selectedRoute?.id}
          onSelect={setSelectedId}
          onRetry={loadRoutes}
          canFind={Boolean(start && destination)}
          onFind={loadRoutes}
          walk={walk}
          onStartWalk={startWalk}
          onStopWalk={stopWalk}
          timeOffset={timeOffset}
          onSelectTime={setTimeOffset}
          accessory={<>
            {status === "results" ? <Legend labels={legendLabels} /> : <span />}
            {/* The map already follows the user while navigating. */}
            {!navigation && <button type="button" className="locate-button" onClick={locateButton} aria-label="Show my location"><LocateIcon /></button>}
          </>}
          overlay={offRoute ? (
            <section className="float-card reroute-card" role="alertdialog" aria-label="Off route">
              <span>About <strong>{Math.round(offRoute.distance)} m</strong> off the route. Recalculate from here?</span>
              <div className="reroute-card__actions">
                <button type="button" className="text-button" onClick={declineReroute}>Keep</button>
                <button type="button" className="solid-button solid-button--small" onClick={acceptReroute}>Recalculate</button>
              </div>
            </section>
          ) : arrival ? (
            <ArrivalCard arrival={arrival} onDone={() => setArrival(null)} />
          ) : navigation ? (
            <NavBar remaining={walk.remaining} message={walk.message} onEnd={stopWalk} />
          ) : tap ? (
            <StreetModal tap={tap} busy={streetBusy} notice={streetNotice} onRate={rate} onToggleCovered={toggleCovered} onClose={closeTap} />
          ) : null}
        />
      </section>
    </main>
  );
}
