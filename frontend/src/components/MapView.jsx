import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import L from "leaflet";

export const MAP_CENTER = [14.6395, 121.0777];
export const STUDY_BOUNDS = [[14.635, 121.065], [14.65, 121.083]];

// Each label differs by pattern as well as colour so routes stay readable in grayscale (PRD S-04).
export const SECTION_STYLES = {
  sun: [{ color: "#e8892b", weight: 7, opacity: 1 }],
  shaded: [
    { color: "#16766f", weight: 7, opacity: 1 },
    { color: "#ffffff", weight: 2.5, opacity: 0.95, dashArray: "1 8" },
  ],
  unknown: [{ color: "#7b818c", weight: 6, opacity: 1, dashArray: "9 7", lineCap: "butt" }],
  covered: [
    { color: "#6b4fc9", weight: 9, opacity: 1 },
    { color: "#ffffff", weight: 2.5, opacity: 1 },
  ],
};

const latLngs = (geometry) => geometry.map(([longitude, latitude]) => [latitude, longitude]);

function pointIcon(kind) {
  return L.divIcon({ className: `map-point map-point--${kind}`, html: "<span></span>", iconSize: [22, 22], iconAnchor: [11, 11] });
}

const NAV_ZOOM = 18;
const NAV_ANCHOR_Y = 0.6; // the user sits 60% down the screen, leaving more map ahead

/** Arrow for the user while navigating, pointing along the direction of travel. */
function headingIcon(heading) {
  return L.divIcon({
    className: "map-heading",
    html: `<svg viewBox="0 0 32 32" width="32" height="32" style="transform: rotate(${heading}deg)"><circle cx="16" cy="16" r="13" fill="#1a73e8" stroke="#fff" stroke-width="3"/><path d="M16 8 22 21 16 18 10 21Z" fill="#fff"/></svg>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

const unknownIcon = L.divIcon({ className: "map-unknown", html: "?", iconSize: [18, 18], iconAnchor: [9, 9] });

const MapView = forwardRef(function MapView(
  { start, destination, routes, selectedId, userPosition, coveredSections = [], highlight, navigation = null, onTap, onSelectRoute },
  ref,
) {
  const containerRef = useRef(null);
  const tilesRef = useRef(null);
  const [map, setMap] = useState(null);
  const handlers = useRef({});
  // Taps on the map do nothing while navigating.
  handlers.current = navigation ? {} : { onTap, onSelectRoute };

  useImperativeHandle(ref, () => ({
    fitGeometry(geometry) {
      if (map && geometry?.length) map.fitBounds(L.latLngBounds(latLngs(geometry)), { paddingTopLeft: [24, 190], paddingBottomRight: [24, 340] });
    },
    panTo(latitude, longitude, zoom = 17) {
      map?.setView([latitude, longitude], zoom);
    },
    resetView() {
      map?.setView(MAP_CENTER, 17);
    },
  }), [map]);

  useEffect(() => {
    const instance = L.map(containerRef.current, {
      zoomControl: false,
      attributionControl: true,
      maxBounds: L.latLngBounds(STUDY_BOUNDS).pad(0.6),
      minZoom: 15,
    }).setView(MAP_CENTER, 17);
    // OSM tiles, made monotone with a CSS filter (see .leaflet-tile-pane in styles.css) so the
    // coloured route stands out. Keyless grey basemaps such as CARTO Positron now need an API key.
    tilesRef.current = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(instance);
    instance.attributionControl.setPrefix(false);
    // Tapping a street opens the street details; points are set by search or location only.
    instance.on("click", (event) => handlers.current.onTap?.(event.latlng, null));
    setMap(instance);
    return () => instance.remove();
  }, []);

  useEffect(() => {
    if (!map) return undefined;
    const layers = [];
    const add = (layer) => layers.push(layer.addTo(map));

    // User-marked covered sections are always visible (PRD S-10).
    coveredSections.forEach((section) => {
      add(L.polyline(latLngs(section.geometry), { color: "#6b4fc9", weight: 6, opacity: 0.85, interactive: false }));
      add(L.polyline(latLngs(section.geometry), { color: "#ffffff", weight: 1.5, opacity: 1, interactive: false }));
    });
    if (highlight) {
      add(L.polyline(latLngs(highlight), { color: "#202124", weight: 12, opacity: 0.25, interactive: false }));
      add(L.polyline(latLngs(highlight), { color: "#202124", weight: 3, opacity: 1, dashArray: "4 6", interactive: false }));
    }

    // Unselected routes first, so the selected one draws on top. Each route has a white casing
    // underneath, like navigation apps, so it stands off the grey basemap.
    routes.filter((route) => route.id !== selectedId).forEach((route) => {
      add(L.polyline(latLngs(route.geometry), { color: "#ffffff", weight: 9, opacity: 0.9, lineCap: "round", lineJoin: "round", interactive: false }));
      const line = L.polyline(latLngs(route.geometry), { color: "#9aa0a8", weight: 5, opacity: 0.9, lineCap: "round", lineJoin: "round", bubblingMouseEvents: false });
      line.on("click", () => handlers.current.onSelectRoute?.(route.id));
      add(line);
    });

    const selected = routes.find((route) => route.id === selectedId);
    if (selected) {
      add(L.polyline(latLngs(selected.geometry), { color: "#ffffff", weight: 12, opacity: 1, lineCap: "round", lineJoin: "round", interactive: false }));
    }
    selected?.exposure?.sections?.forEach((section) => {
      const points = latLngs(section.geometry);
      SECTION_STYLES[section.label]?.forEach((style) => {
        const line = L.polyline(points, { ...style, lineCap: style.lineCap ?? "round", bubblingMouseEvents: false });
        line.on("click", (event) => handlers.current.onTap?.(event.latlng, section));
        add(line);
      });
      if (section.label === "unknown") {
        add(L.marker(points[Math.floor(points.length / 2)], { icon: unknownIcon, interactive: false }));
      }
    });

    if (start) add(L.marker([start.latitude, start.longitude], { icon: pointIcon("start"), interactive: false }));
    if (destination) add(L.marker([destination.latitude, destination.longitude], { icon: pointIcon("destination"), interactive: false }));
    return () => {
      layers.forEach((layer) => layer.remove());
    };
  }, [map, start, destination, routes, selectedId, coveredSections, highlight]);

  // The user's position: a dot, or a heading arrow while navigating. Kept as its own layer so a
  // GPS update every second only moves this marker instead of redrawing the route.
  const userMarkerRef = useRef(null);
  const navigating = Boolean(navigation);
  useEffect(() => {
    if (!map) return undefined;
    if (!userPosition) {
      userMarkerRef.current?.remove();
      userMarkerRef.current = null;
      return undefined;
    }
    const latLng = [userPosition.latitude, userPosition.longitude];
    const icon = navigating ? headingIcon(navigation.heading) : pointIcon("user");
    if (!userMarkerRef.current) {
      userMarkerRef.current = L.marker(latLng, { icon, interactive: false, zIndexOffset: 1000 }).addTo(map);
    } else {
      userMarkerRef.current.setLatLng(latLng).setIcon(icon);
    }
    return undefined;
  }, [map, userPosition, navigating, navigation?.heading]);
  useEffect(() => () => userMarkerRef.current?.remove(), []);

  // Navigation mode (PRD F-13, with GPS): follow the user and rotate the map so the direction of
  // travel points up. Leaflet cannot rotate, so the map element is made into a square big enough
  // to cover the phone at any angle, centred on the user's on-screen spot, and rotated with CSS.
  // Panning and taps are off (the map follows the user). Zoom stays on in Leaflet's "center" mode:
  // it zooms around the map centre, which is the user, and pinch distance does not depend on
  // rotation, so pinch-zoom stays correct on the rotated map.
  // The basemap is washed out further while rotated, so tilted labels recede behind the route.
  const rotationRef = useRef(0);
  useEffect(() => {
    if (!map) return undefined;
    const element = containerRef.current;
    const frame = element.parentElement;
    const panning = ["dragging", "boxZoom", "keyboard"];
    const zooming = ["touchZoom", "doubleClickZoom", "scrollWheelZoom"];
    if (!navigating) return undefined;
    const width = frame.clientWidth;
    const height = frame.clientHeight;
    const centerX = width / 2;
    const centerY = height * NAV_ANCHOR_Y;
    const radius = Math.ceil(Math.hypot(Math.max(centerX, width - centerX), Math.max(centerY, height - centerY)));
    Object.assign(element.style, {
      inset: "auto", width: `${radius * 2}px`, height: `${radius * 2}px`,
      left: `${centerX - radius}px`, top: `${centerY - radius}px`, transformOrigin: "50% 50%",
    });
    element.classList.add("map--navigating");
    panning.forEach((name) => map[name]?.disable());
    zooming.forEach((name) => { map.options[name] = "center"; map[name]?.enable(); });
    map.invalidateSize({ pan: false });
    map.setZoom(NAV_ZOOM, { animate: false });
    return () => {
      ["inset", "width", "height", "left", "top", "transform", "transformOrigin"].forEach((key) => { element.style[key] = ""; });
      element.classList.remove("map--navigating");
      rotationRef.current = 0;
      panning.forEach((name) => map[name]?.enable());
      zooming.forEach((name) => { map.options[name] = true; });
      map.invalidateSize({ pan: false });
    };
  }, [map, navigating]);

  useEffect(() => {
    if (!map || !navigation) return;
    // Keep whatever zoom the user pinched to; only the position follows the GPS.
    map.setView([navigation.latitude, navigation.longitude], map.getZoom(), { animate: true, duration: 0.5 });
    // Rotate the shortest way round, keeping a running angle so 359° → 1° does not spin backwards.
    const current = ((rotationRef.current % 360) + 360) % 360;
    const delta = ((navigation.heading - current + 540) % 360) - 180;
    rotationRef.current += delta;
    containerRef.current.style.transform = `rotate(${-rotationRef.current}deg)`;
  }, [map, navigation?.latitude, navigation?.longitude, navigation?.heading]);

  return <div ref={containerRef} className="map" role="application" aria-label="Map of the Katipunan and Ateneo walking area" />;
});

export default MapView;
