import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { AttributionControl, LngLatBounds, Map as MapLibreMap, Marker, setWorkerUrl } from "maplibre-gl";
// Vite pre-bundles the library, which breaks its own worker lookup, so point it at the file.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

setWorkerUrl(workerUrl);

export const MAP_CENTER = [14.6395, 121.0777];
// Metro Manila study area ([[south, west], [north, east]]), matching /api/health study_area.
export const STUDY_BOUNDS = [[14.35, 120.9], [14.79, 121.15]];
// Panning limit: the study area plus a small margin.
const MAX_BOUNDS = [[120.85, 14.3], [121.2, 14.85]];
// Vector basemap: free, no API key, sharp at any screen density, and it rotates natively.
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

const EMPTY = { type: "FeatureCollection", features: [] };
const line = (geometry, properties = {}) => ({ type: "Feature", properties, geometry: { type: "LineString", coordinates: geometry } });
const collection = (features) => ({ type: "FeatureCollection", features });

// Each label differs by pattern as well as colour so routes stay readable in grayscale (PRD S-04).
// Dash lengths in MapLibre are multiples of the line width.
export const SECTION_STYLES = {
  sun: [{ color: "#e8892b", width: 7 }],
  shaded: [
    { color: "#16766f", width: 7 },
    { color: "#ffffff", width: 2.5, opacity: 0.95, dash: [0.4, 3.2] },
  ],
  unknown: [{ color: "#7b818c", width: 6, dash: [1.5, 1.17], cap: "butt" }],
  covered: [
    { color: "#6b4fc9", width: 9 },
    { color: "#ffffff", width: 2.5 },
  ],
};
const SECTION_LAYERS = Object.entries(SECTION_STYLES).flatMap(([label, styles]) =>
  styles.map((style, index) => ({ id: `section-${label}-${index}`, label, style })));

const NAV_ZOOM = 18;
const NAV_TOP_PADDING = 0.2; // pads the top by 20% of the height, so the user sits 60% down
const TAP_SLOP = 6; // px around a tap that still counts as touching a line.

function lineLayer(id, source, { color, width, opacity = 1, dash, cap = "round" }, filter) {
  return {
    id, source, type: "line", ...(filter ? { filter } : {}),
    layout: { "line-cap": cap, "line-join": "round" },
    paint: { "line-color": color, "line-width": width, "line-opacity": opacity, ...(dash ? { "line-dasharray": dash } : {}) },
  };
}

function addRouteLayers(map) {
  ["covered", "highlight", "others", "selected", "sections"].forEach((id) => map.addSource(id, { type: "geojson", data: EMPTY }));
  // Drawn bottom to top.
  map.addLayer(lineLayer("covered-line", "covered", { color: "#6b4fc9", width: 6, opacity: 0.85 }));
  map.addLayer(lineLayer("covered-centre", "covered", { color: "#ffffff", width: 1.5 }));
  // Each route has a white casing underneath, like navigation apps, so it stands off the basemap.
  map.addLayer(lineLayer("others-casing", "others", { color: "#ffffff", width: 9, opacity: 0.9 }));
  map.addLayer(lineLayer("others-line", "others", { color: "#9aa0a8", width: 5, opacity: 0.9 }));
  map.addLayer(lineLayer("selected-casing", "selected", { color: "#ffffff", width: 12 }));
  SECTION_LAYERS.forEach(({ id, label, style }) => map.addLayer(lineLayer(id, "sections", style, ["==", ["get", "label"], label])));
  // The tapped street or section, on top so it shows even over the selected route's casing.
  map.addLayer(lineLayer("highlight-halo", "highlight", { color: "#202124", width: 14, opacity: 0.22 }));
  map.addLayer(lineLayer("highlight-line", "highlight", { color: "#202124", width: 3, dash: [1.33, 2], cap: "butt" }));
}

function pointElement(kind) {
  const element = document.createElement("div");
  element.className = `map-point map-point--${kind}`;
  element.innerHTML = "<span></span>";
  Object.assign(element.style, { width: "22px", height: "22px", pointerEvents: "none" });
  return element;
}

/** Arrow for the user while navigating; the marker is rotated to the heading on the map plane. */
function headingElement() {
  const element = document.createElement("div");
  element.className = "map-heading";
  element.style.pointerEvents = "none";
  element.innerHTML = '<svg viewBox="0 0 32 32" width="32" height="32"><circle cx="16" cy="16" r="13" fill="#1a73e8" stroke="#fff" stroke-width="3"/><path d="M16 8 22 21 16 18 10 21Z" fill="#fff"/></svg>';
  return element;
}

function unknownElement() {
  const element = document.createElement("div");
  element.className = "map-unknown";
  element.textContent = "?";
  Object.assign(element.style, { width: "18px", height: "18px", pointerEvents: "none" });
  return element;
}

/** Padding for fitBounds, shrunk on short screens so MapLibre never rejects it. */
function fitPadding(map) {
  const { clientHeight: height, clientWidth: width } = map.getContainer();
  const padding = { top: 190, bottom: 340, left: 24, right: 24 };
  const vertical = padding.top + padding.bottom;
  if (vertical > height - 60) {
    const scale = Math.max(0, height - 60) / vertical;
    padding.top = Math.round(padding.top * scale);
    padding.bottom = Math.round(padding.bottom * scale);
  }
  if (padding.left + padding.right > width - 40) padding.left = padding.right = 0;
  return padding;
}

const MapView = forwardRef(function MapView(
  { start, destination, routes, selectedId, userPosition, coveredSections = [], highlight, navigation = null, onTap, onSelectRoute },
  ref,
) {
  const containerRef = useRef(null);
  const [map, setMap] = useState(null);
  // The map whose style and route layers have loaded; data effects wait for it.
  const [loadedMap, setLoadedMap] = useState(null);
  const handlers = useRef({});
  // Taps on the map do nothing while navigating.
  handlers.current = navigation ? {} : { onTap, onSelectRoute };
  const sectionsRef = useRef([]);
  // The map that is currently mounted. A hot reload re-runs effects with a removed map still in
  // state, so effects check against this before touching the map.
  const liveMapRef = useRef(null);

  useImperativeHandle(ref, () => ({
    fitGeometry(geometry) {
      if (!map || !geometry?.length) return;
      const bounds = geometry.reduce((box, point) => box.extend(point), new LngLatBounds(geometry[0], geometry[0]));
      map.fitBounds(bounds, { padding: fitPadding(map), bearing: 0, maxZoom: 19, duration: 500 });
      // MapLibre opens the compact attribution until the first drag; fold it to its (i) button
      // once there is a route, so it does not sit on top of it.
      map.getContainer().querySelector(".maplibregl-compact-show")?.classList.remove("maplibregl-compact-show");
    },
    panTo(latitude, longitude, zoom = 17) {
      map?.easeTo({ center: [longitude, latitude], zoom, duration: 400 });
    },
    resetView() {
      map?.easeTo({ center: [MAP_CENTER[1], MAP_CENTER[0]], zoom: 17, bearing: 0 });
    },
  }), [map]);

  useEffect(() => {
    const instance = new MapLibreMap({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      center: [MAP_CENTER[1], MAP_CENTER[0]],
      zoom: 17,
      minZoom: 11,
      maxZoom: 19.5,
      maxBounds: MAX_BOUNDS,
      maxPitch: 0,
      pitchWithRotate: false,
      dragRotate: false,
      attributionControl: false,
    });
    // North-up outside navigation: no rotate or tilt gestures.
    instance.touchZoomRotate.disableRotation();
    instance.touchPitch.disable();
    instance.keyboard.disableRotation();
    // Top right, just under the top cards (see .maplibregl-ctrl-top-right), so the sheet never hides it.
    instance.addControl(new AttributionControl({ compact: true }), "top-right");
    instance.on("load", () => {
      addRouteLayers(instance);
      setLoadedMap(instance);
    });
    // Tapping a street opens the street details; points are set by search or location only.
    instance.on("click", (event) => {
      const { onTap: tap, onSelectRoute: select } = handlers.current;
      if (!tap && !select) return;
      const { x, y } = event.point;
      const box = [[x - TAP_SLOP, y - TAP_SLOP], [x + TAP_SLOP, y + TAP_SLOP]];
      const latlng = { lat: event.lngLat.lat, lng: event.lngLat.lng };
      if (instance.getLayer("others-line")) {
        const [hit] = instance.queryRenderedFeatures(box, { layers: SECTION_LAYERS.map((layer) => layer.id) });
        const section = hit && sectionsRef.current[hit.properties.index];
        if (section) return tap?.(latlng, section);
        const [other] = instance.queryRenderedFeatures(box, { layers: ["others-line"] });
        if (other) return select?.(other.properties.id);
      }
      return tap?.(latlng, null);
    });
    liveMapRef.current = instance;
    setMap(instance);
    return () => {
      liveMapRef.current = null;
      instance.remove();
    };
  }, []);

  useEffect(() => {
    if (!map || loadedMap !== map || map !== liveMapRef.current) return undefined;
    const selected = routes.find((route) => route.id === selectedId);
    const sections = selected?.exposure?.sections ?? [];
    sectionsRef.current = sections;
    map.getSource("covered").setData(collection(coveredSections.map((section) => line(section.geometry))));
    map.getSource("highlight").setData(highlight ? collection([line(highlight)]) : EMPTY);
    map.getSource("others").setData(collection(routes.filter((route) => route.id !== selectedId).map((route) => line(route.geometry, { id: route.id }))));
    map.getSource("selected").setData(selected ? collection([line(selected.geometry)]) : EMPTY);
    map.getSource("sections").setData(collection(sections.map((section, index) => line(section.geometry, { label: section.label, index }))));

    const markers = [];
    sections.filter((section) => section.label === "unknown").forEach((section) => {
      const middle = section.geometry[Math.floor(section.geometry.length / 2)];
      markers.push(new Marker({ element: unknownElement() }).setLngLat(middle).addTo(map));
    });
    if (start) markers.push(new Marker({ element: pointElement("start") }).setLngLat([start.longitude, start.latitude]).addTo(map));
    if (destination) markers.push(new Marker({ element: pointElement("destination") }).setLngLat([destination.longitude, destination.latitude]).addTo(map));
    return () => markers.forEach((marker) => marker.remove());
  }, [map, loadedMap, start, destination, routes, selectedId, coveredSections, highlight]);

  // The user's position: a dot, or a heading arrow while navigating. Kept as its own marker so a
  // GPS update every second only moves this marker instead of redrawing the route.
  const navigating = Boolean(navigation);
  const userMarkerRef = useRef(null);
  useEffect(() => {
    if (!map || map !== liveMapRef.current) return undefined;
    const marker = navigating
      ? new Marker({ element: headingElement(), rotationAlignment: "map" })
      : new Marker({ element: pointElement("user") });
    marker.getElement().style.zIndex = "2";
    userMarkerRef.current = marker;
    return () => {
      marker.remove();
      userMarkerRef.current = null;
    };
  }, [map, navigating]);
  useEffect(() => {
    const marker = userMarkerRef.current;
    if (!map || !marker || map !== liveMapRef.current) return;
    if (!userPosition) {
      marker.remove();
      return;
    }
    marker.setLngLat([userPosition.longitude, userPosition.latitude]);
    if (navigating) marker.setRotation(navigation.heading ?? 0);
    if (!marker.getElement().isConnected) marker.addTo(map);
  }, [map, navigating, userPosition, navigation?.heading]);

  // Navigation mode (PRD F-13, with GPS): follow the user and rotate the map so the direction of
  // travel points up. Panning and taps are off (the map follows the user). Pinch and wheel zoom
  // stay on around the centre, which is the user, so the zoom the user picks is kept.
  // On entering navigation the map zooms to NAV_ZOOM. Rapid GPS updates can cancel that animation,
  // so the zoom stays pending until it is reached or the user zooms by hand.
  const navZoomPendingRef = useRef(false);
  const gestureRef = useRef(false);
  useEffect(() => {
    if (!map || map !== liveMapRef.current) return undefined;
    const onZoomStart = (event) => {
      if (!event.originalEvent) return;
      gestureRef.current = true;
      navZoomPendingRef.current = false;
    };
    const onZoomEnd = () => { gestureRef.current = false; };
    map.on("zoomstart", onZoomStart);
    map.on("zoomend", onZoomEnd);
    return () => {
      map.off("zoomstart", onZoomStart);
      map.off("zoomend", onZoomEnd);
    };
  }, [map]);
  useEffect(() => {
    if (!map || !navigating || map !== liveMapRef.current) return undefined;
    navZoomPendingRef.current = true;
    map.dragPan.disable();
    map.keyboard.disable();
    map.boxZoom.disable();
    map.scrollZoom.enable({ around: "center" });
    map.touchZoomRotate.enable({ around: "center" });
    map.touchZoomRotate.disableRotation();
    return () => {
      if (map !== liveMapRef.current) return;
      map.dragPan.enable();
      map.keyboard.enable();
      map.keyboard.disableRotation();
      map.boxZoom.enable();
      map.scrollZoom.enable();
      map.touchZoomRotate.enable();
      map.touchZoomRotate.disableRotation();
      // Drop the navigation padding at once (an interrupted animation could leave some behind and
      // offset later fits), then turn back to north-up.
      map.stop();
      map.setPadding({ top: 0, bottom: 0, left: 0, right: 0 });
      map.easeTo({ bearing: 0, duration: 450 });
    };
  }, [map, navigating]);

  useEffect(() => {
    if (!map || !navigation || map !== liveMapRef.current) return;
    // Do not fight a pinch in progress; the next GPS update catches up.
    if (gestureRef.current) return;
    const height = map.getContainer().clientHeight;
    if (Math.abs(map.getZoom() - NAV_ZOOM) < 0.05) navZoomPendingRef.current = false;
    const zooming = navZoomPendingRef.current;
    map.easeTo({
      center: [navigation.longitude, navigation.latitude],
      bearing: navigation.heading ?? map.getBearing(),
      padding: { top: Math.round(height * NAV_TOP_PADDING), bottom: 0, left: 0, right: 0 },
      // Once reached, updates keep whatever zoom the user pinched to.
      ...(zooming ? { zoom: NAV_ZOOM } : {}),
      duration: zooming ? 600 : 450,
      essential: true,
    });
  }, [map, navigation?.latitude, navigation?.longitude, navigation?.heading]);

  return <div ref={containerRef} className="map" role="application" aria-label="Map of the Katipunan and Ateneo walking area" />;
});

export default MapView;
