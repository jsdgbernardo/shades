import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import L from "leaflet";
import { LABEL_TEXT, formatDistance } from "../lib/format.js";

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

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function pointIcon(kind) {
  return L.divIcon({ className: `map-point map-point--${kind}`, html: "<span></span>", iconSize: [22, 22], iconAnchor: [11, 11] });
}

const unknownIcon = L.divIcon({ className: "map-unknown", html: "?", iconSize: [18, 18], iconAnchor: [9, 9] });

const MapView = forwardRef(function MapView(
  { start, destination, routes, selectedId, userPosition, coveredSections = [], highlight, streetMode = false, onMapPick, onSelectRoute, onSectionTap },
  ref,
) {
  const containerRef = useRef(null);
  const [map, setMap] = useState(null);
  const handlers = useRef({});
  handlers.current = { onMapPick, onSelectRoute, onSectionTap, streetMode };

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
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(instance);
    instance.attributionControl.setPrefix(false);
    instance.on("click", (event) => handlers.current.onMapPick?.(event.latlng));
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

    // Unselected routes first, so the selected one draws on top.
    routes.filter((route) => route.id !== selectedId).forEach((route) => {
      const line = L.polyline(latLngs(route.geometry), { color: "#8d929b", weight: 6, opacity: 0.6, bubblingMouseEvents: false });
      line.on("click", () => handlers.current.onSelectRoute?.(route.id));
      add(line);
    });

    const selected = routes.find((route) => route.id === selectedId);
    selected?.exposure?.sections?.forEach((section, index) => {
      const points = latLngs(section.geometry);
      SECTION_STYLES[section.label]?.forEach((style) => {
        const line = L.polyline(points, { ...style, lineCap: style.lineCap ?? "round", bubblingMouseEvents: false });
        line.on("click", (event) => {
          if (handlers.current.streetMode) { handlers.current.onMapPick?.(event.latlng); return; }
          L.popup({ className: "section-popup", closeButton: false, autoPanPaddingTopLeft: [20, 180] })
            .setLatLng(event.latlng)
            .setContent(
              `<strong class="section-popup__label section-popup__label--${section.label}">${escapeHtml(LABEL_TEXT[section.label] ?? section.label)}</strong>` +
              `<span>${escapeHtml(section.reason)}</span><small>${formatDistance(section.length_m)} section</small>`,
            )
            .openOn(map);
          handlers.current.onSectionTap?.(section, index);
        });
        add(line);
      });
      if (section.label === "unknown") {
        add(L.marker(points[Math.floor(points.length / 2)], { icon: unknownIcon, interactive: false }));
      }
    });

    if (start) add(L.marker([start.latitude, start.longitude], { icon: pointIcon("start"), interactive: false }));
    if (destination) add(L.marker([destination.latitude, destination.longitude], { icon: pointIcon("destination"), interactive: false }));
    if (userPosition) add(L.marker([userPosition.latitude, userPosition.longitude], { icon: pointIcon("user"), interactive: false, zIndexOffset: 1000 }));
    return () => {
      layers.forEach((layer) => layer.remove());
    };
  }, [map, start, destination, routes, selectedId, userPosition, coveredSections, highlight]);

  return <div ref={containerRef} className="map" role="application" aria-label="Map of the Katipunan and Ateneo walking area" />;
});

export default MapView;
