import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "./components/MapView.jsx";
import LocationCard from "./components/LocationCard.jsx";
import TimePill from "./components/TimePill.jsx";
import RouteSheet from "./components/RouteSheet.jsx";
import Legend from "./components/Legend.jsx";
import { CompassIcon, LocateIcon } from "./components/Icons.jsx";
import StreetModal from "./components/StreetPanel.jsx";
import PinCard from "./components/PinCard.jsx";
import { pinnedName } from "./lib/pin.js";
import { ConnectionError, fetchHealth, fetchNearestStreet, fetchRoutes, fetchWeather, rateStreet, removeRating, setCovered } from "./lib/api.js";
import { haversineMeters, isOffRoute, projectOntoRoute, remainingFigures } from "./lib/geo.js";
import { arrivalSummary, buildManeuvers, cumulative, edgeAt, hasArrived, headingAt, nextManeuver } from "./lib/nav.js";
import { ArrivalCard, NavBanner, NavBar, RateWalkCard } from "./components/NavPanel.jsx";
import { forgetRated, myRating, rememberRated, ratedStreets, streetsToRate } from "./lib/ratePrompt.js";
import { MAX_ACCURACY_METERS, geolocation, locationProblem } from "./lib/location.js";
import { requestCompassPermission, watchHeading } from "./lib/compass.js";
import { addSample, afterPaint, describe as describeTiming, timingEnabled } from "./lib/timing.js";
import { toInputValue, toOffsetIso } from "./lib/time.js";

// Metro Manila until /api/health answers; the API's backend/area.py is the source of truth.
let studyArea = { south: 14.35, north: 14.79, west: 120.9, east: 121.15 };
const inStudyArea = (latitude, longitude) =>
  latitude >= studyArea.south && latitude <= studyArea.north && longitude >= studyArea.west && longitude <= studyArea.east;
// Notices from locationProblem() in lib/location.js.
const LOCATION_NOTICE = /^(Location (access denied|too imprecise|unavailable)|You are outside)/;
// Field-test timing readout (P-01, P-02), shown only with ?timing.
const TIMING = timingEnabled();
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

  useEffect(() => {
    fetchHealth().then((payload) => { if (payload.study_area) studyArea = payload.study_area; }).catch(() => {});
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
    const requestedAt = performance.now();
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
      // P-01 field timing: request until the routes are drawn (only with ?timing).
      if (TIMING) afterPaint(() => setTiming((current) => ({ ...current, routes: addSample(current.routes, performance.now() - requestedAt, 10_000) })));
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
  // Swiping the route sheet away: hide the routes but keep the trip, so Find routes is one tap away.
  const dismissResults = useCallback(() => {
    requestCounter.current += 1;
    setData(null);
    setStatus("idle");
    setError("");
  }, []);

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
      // This phone's earlier rating of the street is replaced, not added to (PRD S-08).
      const updated = await rateStreet(street.way_id, value, myRating(street.way_id)?.token);
      rememberRated(street.way_id, { rating: value, token: updated.token }); // not asked about again after a walk
      setStreet((current) => ({ ...current, walkability: updated.walkability }));
      setStreetNotice(`Thanks. You rated ${updated.name} ${value} out of 5.`);
      if (data) loadRoutes(); // refresh routes already shown; never start a new search
    } catch (failure) {
      setStreetNotice(failure.message);
    } finally {
      setStreetBusy(false);
    }
  };

  // Removes the rating this phone made for the open street (it keeps the token for that).
  const removeMyRating = async () => {
    const mine = myRating(street.way_id);
    if (!mine?.token) return;
    setStreetBusy(true);
    try {
      const updated = await removeRating(street.way_id, mine.token);
      forgetRated(street.way_id);
      setStreet((current) => ({ ...current, walkability: updated.walkability }));
      setStreetNotice("Your rating was removed.");
      if (data) loadRoutes();
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

  // Choose on map (PRD S-02): a pin fixed at the centre of the map while the user drags the map
  // under it. Ordinary taps still open street details and never move a point.
  const [picking, setPicking] = useState(null); // null, "start" or "destination"
  const [pickLookup, setPickLookup] = useState(null);
  const [pinLifted, setPinLifted] = useState(false);
  const pickCounter = useRef(0);
  const pickTimer = useRef(null);
  const lookUpPin = useCallback((center) => {
    setPinLifted(false);
    clearTimeout(pickTimer.current);
    const id = ++pickCounter.current;
    if (!center) return;
    if (!inStudyArea(center.latitude, center.longitude)) { setPickLookup({ outside: true, center }); return; }
    setPickLookup({ loading: true, center });
    // Wait for the map to settle; an older answer is ignored.
    pickTimer.current = setTimeout(async () => {
      let street = null;
      try { street = await fetchNearestStreet(center.latitude, center.longitude); } catch { street = null; }
      if (id === pickCounter.current) setPickLookup({ street, center });
    }, 250);
  }, []);
  const chooseOnMap = (field) => {
    closeTap();
    setMessage("");
    setPicking(field);
    setPickLookup(null);
    const point = (field === "start" ? start : destination) ?? userPosition;
    // Look up the starting spot directly too: if the map is already there it does not move, and
    // no move-end would trigger the lookup.
    if (point) {
      mapRef.current?.centerOn(point.latitude, point.longitude);
      lookUpPin({ latitude: point.latitude, longitude: point.longitude });
    } else {
      lookUpPin(mapRef.current?.getCenter());
    }
  };
  const cancelPick = () => { pickCounter.current += 1; clearTimeout(pickTimer.current); setPicking(null); setPinLifted(false); };
  const setPin = (streetName) => {
    const center = pickLookup?.center ?? mapRef.current?.getCenter();
    if (!center) return;
    const point = { latitude: center.latitude, longitude: center.longitude, name: pinnedName(picking, streetName), source: "pin" };
    if (picking === "start") { setStart(point); setActiveField("destination"); } else { setDestination(point); }
    cancelPick();
  };

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
    // Arrived: within ARRIVE_METERS of the end, along the route or in a straight line (for cutting
    // a corner or reaching it from another side). End the walk and show the summary.
    const toEnd = haversineMeters([longitude, latitude], route.geometry[route.geometry.length - 1]);
    if (hasArrived(remaining.distance_m, toEnd, !isOffRoute(projection.distanceFromRoute))) {
      arriveRef.current?.(route);
      return;
    }
    setWalk((current) => (current.active ? {
      ...current,
      remaining,
      heading,
      maneuver,
      along: projection.along,
      onRoute: !isOffRoute(projection.distanceFromRoute),
      updatedAt: Date.now(),
      fixAt: performance.now(),
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

  // The live blue dot outside walks: follows the user while the page is visible, until location
  // permission is refused. A slow or failed first fix does not stop it. It never changes the start
  // point, and positions stay on the device (PRD C-04).
  useEffect(() => {
    if (walk.active) return undefined;
    const geo = geolocation();
    if (!geo) return undefined;
    let watchId = null;
    const onFix = ({ coords: { latitude, longitude, accuracy } }) => {
      if (accuracy > MAX_ACCURACY_METERS || !inStudyArea(latitude, longitude)) return;
      setUserPosition({ latitude, longitude });
      // A good fix after a failed first try: location works after all, so clear the location
      // notice and use it as the start if none is set yet (as the first try would have).
      setLocationUsable(true);
      setMessage((current) => (LOCATION_NOTICE.test(current) ? "" : current));
      setStart((current) => current ?? { latitude, longitude, source: "gps" });
    };
    const onError = (problem) => {
      if (problem?.code !== 1) return;
      setUserPosition(null);
      end();
    };
    const begin = () => { if (watchId === null) watchId = geo.watchPosition(onFix, onError, GPS_OPTIONS); };
    const end = () => { if (watchId !== null) geo.clearWatch(watchId); watchId = null; };
    const onVisibility = () => (document.hidden ? end() : begin());
    if (!document.hidden) begin();
    document.addEventListener("visibilitychange", onVisibility);
    return () => { end(); document.removeEventListener("visibilitychange", onVisibility); };
  }, [walk.active]);

  // Field timing: P-02 measures a GPS fix until the walk figures are on screen.
  const [timing, setTiming] = useState({});
  useEffect(() => {
    if (!TIMING || !walk.fixAt) return;
    const fixAt = walk.fixAt;
    afterPaint(() => setTiming((current) => ({ ...current, fix: addSample(current.fix, performance.now() - fixAt, 2_000) })));
  }, [walk.fixAt]);

  // Which way the phone points, for the cone on the dot. Paused while the page is hidden.
  const [heading, setHeading] = useState(null);
  useEffect(() => {
    let stop = null;
    const begin = () => { if (!stop) stop = watchHeading(setHeading); };
    const end = () => { stop?.(); stop = null; };
    const onVisibility = () => (document.hidden ? end() : begin());
    if (!document.hidden) begin();
    document.addEventListener("visibilitychange", onVisibility);
    return () => { end(); document.removeEventListener("visibilitychange", onVisibility); };
  }, []);

  const startWalk = () => {
    requestCompassPermission();
    setRateWalk(null);
    setCoveredHere(null);
    setFollowing(true);
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
    setFollowing(true);
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
    setRated({});
    setArrival({
      ...arrivalSummary(route, walk.startedAt ?? Date.now()),
      place: destination?.name ?? null,
      // A few streets from the walk to rate, never ones this phone already rated (PRD S-08).
      streets: streetsToRate(route.edges, Number.POSITIVE_INFINITY, ratedStreets()),
    });
    stopWalk();
  };

  // Ending a walk past halfway also asks about the streets walked so far; earlier, nothing.
  const [rateWalk, setRateWalk] = useState(null);
  const [rated, setRated] = useState({});
  const endWalk = () => {
    const route = selectedRouteRef.current;
    const total = routeNavRef.current.total;
    const walked = walk.along ?? 0;
    const streets = route && total > 0 && walked >= total / 2 ? streetsToRate(route.edges, walked, ratedStreets()) : [];
    setRated({});
    setRateWalk(streets.length ? { streets } : null);
    stopWalk();
  };
  const rateWalked = async (street, value) => {
    try {
      // One rating for each walked piece of the street (OSM often splits one street into several ways).
      for (const wayId of street.way_ids) {
        const saved = await rateStreet(wayId, value, myRating(wayId)?.token);
        rememberRated(wayId, { rating: value, token: saved.token });
      }
      setRated((current) => ({ ...current, [street.name]: value }));
      if (data) loadRoutes(); // refresh routes already shown; never start a new search
    } catch {
      setRated((current) => ({ ...current, [street.name]: "error" }));
    }
  };

  // "Covered here": marks the route edge being walked as covered (PRD S-10), with a short Undo.
  const [coveredHere, setCoveredHere] = useState(null);
  const coveredTimer = useRef(null);
  const markCoveredHere = async () => {
    const route = selectedRouteRef.current;
    const edge = route && edgeAt(route.edges, routeNavRef.current.distances, walk.along ?? 0);
    if (!edge) return;
    clearTimeout(coveredTimer.current);
    setCoveredHere({ state: "saving", key: edge.edge_key });
    try {
      await setCovered(edge.edge_key, true);
      setCoveredHere({ state: "saved", key: edge.edge_key });
      coveredTimer.current = setTimeout(() => setCoveredHere(null), 5_000);
    } catch (failure) {
      setCoveredHere({ state: "error", message: failure.message });
      coveredTimer.current = setTimeout(() => setCoveredHere(null), 5_000);
    }
  };
  const undoCoveredHere = async () => {
    const key = coveredHere?.key;
    clearTimeout(coveredTimer.current);
    setCoveredHere(null);
    if (key) {
      try { await setCovered(key, false); } catch (failure) { setCoveredHere({ state: "error", message: failure.message }); }
    }
  };

  const acceptReroute = () => {
    if (positionRef.current) {
      autoComputeRef.current = true; // the user just asked to recalculate
      setStart({ ...positionRef.current, source: "gps" });
    }
    setOffRoute(null);
  };
  const declineReroute = () => { promptDismissedRef.current = true; setOffRoute(null); };

  // Map rotation (compass) and, while navigating, whether the map follows the user (Re-center).
  const [bearing, setBearing] = useState(0);
  const [following, setFollowing] = useState(true);
  const resetNorth = () => {
    // During navigation, north-up means looking around: stop following so GPS does not turn it back.
    if (navigation) setFollowing(false);
    mapRef.current?.resetNorth();
  };
  const rotated = Math.abs(((bearing % 360) + 540) % 360 - 180) > 2;

  const locateButton = () => {
    requestCompassPermission(); // iPhone asks for the compass only after a tap
    if (userPosition) mapRef.current?.panTo(userPosition.latitude, userPosition.longitude);
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
          heading={heading}
          coveredSections={openCoveredSection}
          highlight={street?.section?.geometry ?? null}
          navigation={navigation}
          picking={Boolean(picking)}
          onMoveStart={() => setPinLifted(true)}
          onMoveEnd={lookUpPin}
          following={following}
          onUserMovedMap={() => setFollowing(false)}
          onBearingChange={setBearing}
          onTap={handleTap}
          onSelectRoute={setSelectedId}
        />
        {TIMING && (
          <div className="timing-readout" aria-live="off">
            {describeTiming("Routes", timing.routes, 10_000)}<br />{describeTiming("Fix→figures", timing.fix, 2_000)}
          </div>
        )}
        {picking && (
          <div className={`pick-pin pick-pin--${picking} ${pinLifted ? "pick-pin--lifted" : ""}`} aria-hidden="true">
            <svg viewBox="0 0 30 40" width="30" height="40"><path d="M15 39S2 23.5 2 14.5a13 13 0 1 1 26 0C28 23.5 15 39 15 39Z" /><circle cx="15" cy="14.5" r="5" fill="#fff" /></svg>
            <span className="pick-pin__shadow" />
          </div>
        )}
        {!online && <div className="offline-banner" role="alert">No connection. Routes and weather need the internet.</div>}
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
            onChooseOnMap={walk.active ? null : chooseOnMap}
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
          onClose={dismissResults}
          walk={walk}
          onStartWalk={startWalk}
          onStopWalk={stopWalk}
          timeOffset={timeOffset}
          onSelectTime={setTimeOffset}
          accessory={<>
            {status === "results" ? <Legend labels={legendLabels} /> : <span />}
            <div className="map-buttons">
              {rotated && <button type="button" className="compass-button" onClick={resetNorth} aria-label="Turn the map north up"><CompassIcon bearing={bearing} /></button>}
              {/* While navigating the map follows the user, until they move it: then Re-center. */}
              {navigation
                ? !following && <button type="button" className="recenter-button" onClick={() => setFollowing(true)}><LocateIcon /> Re-center</button>
                : <button type="button" className="locate-button" onClick={locateButton} aria-label="Show my location"><LocateIcon /></button>}
            </div>
          </>}
          overlay={picking ? (
            <PinCard field={picking} lookup={pickLookup} onCancel={cancelPick} onSet={setPin} />
          ) : offRoute ? (
            <section className="float-card reroute-card" role="alertdialog" aria-label="Off route">
              <span>About <strong>{Math.round(offRoute.distance)} m</strong> off the route. Recalculate from here?</span>
              <div className="reroute-card__actions">
                <button type="button" className="text-button" onClick={declineReroute}>Keep</button>
                <button type="button" className="solid-button solid-button--small" onClick={acceptReroute}>Recalculate</button>
              </div>
            </section>
          ) : arrival ? (
            <ArrivalCard arrival={arrival} rated={rated} onRate={rateWalked} onDone={() => setArrival(null)} />
          ) : rateWalk ? (
            <RateWalkCard streets={rateWalk.streets} rated={rated} onRate={rateWalked} onDone={() => setRateWalk(null)} />
          ) : navigation ? (
            <NavBar
              remaining={walk.remaining}
              message={walk.message}
              onEnd={endWalk}
              onCoveredHere={walk.onRoute ? markCoveredHere : null}
              covered={coveredHere}
              onUndoCovered={undoCoveredHere}
            />
          ) : tap ? (
            <StreetModal
              tap={tap}
              busy={streetBusy}
              notice={streetNotice}
              mine={street ? myRating(street.way_id) : null}
              onRate={rate}
              onRemoveRating={removeMyRating}
              onToggleCovered={toggleCovered}
              onClose={closeTap}
            />
          ) : null}
        />
      </section>
    </main>
  );
}
