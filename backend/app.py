"""HTTP API for the Katipunan shade-routing prototype (Python standard library only)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from osm import FootprintIndex, load_osm
from places import PlaceIndex
from routing import WalkingGraph, edge_key
from shade import WALKING_SPEED_M_PER_MIN, ExposureModel, HeightRaster, analyze_route, shift_time
from storage import DEFAULT_PATH, Store, route_walkability, street_score
from weather import fetch_weather


STUDY_AREA = {
    "name": "Katipunan and Ateneo de Manila University",
    "south": 14.635,
    "north": 14.650,
    "west": 121.065,
    "east": 121.083,
}
STUDY_CENTER = ((STUDY_AREA["south"] + STUDY_AREA["north"]) / 2, (STUDY_AREA["west"] + STUDY_AREA["east"]) / 2)
SHADIER_SUN_WEIGHT = 3.0
COMFORT_OFFSETS_MINUTES = (0, 15, 30)
WAIT_THRESHOLD_POINTS = 5.0
ASSUMPTIONS = {
    "walking_speed_m_per_min": WALKING_SPEED_M_PER_MIN,
    "notes": [
        f"Walking time assumes {WALKING_SPEED_M_PER_MIN:g} m per minute.",
        "Shade comes from buildings only. Trees, awnings and clouds are not modeled; the sky is assumed clear.",
        "Sections without building height data are counted as direct sun.",
        "Covered walkways count only where users have marked them.",
    ],
}

OSM_DATA = load_osm()
ENCLOSED_BUILDINGS = FootprintIndex(OSM_DATA.building_footprints(enclosed_only=True))
WALKING_GRAPH = WalkingGraph.from_osm(OSM_DATA, ENCLOSED_BUILDINGS)
HEIGHT_RASTER = HeightRaster.from_file()
BUILDING_HEIGHT_REPORT = HEIGHT_RASTER.mark_unknown_footprints(OSM_DATA.building_footprints())


def is_in_study_area(latitude: float, longitude: float) -> bool:
    return (
        STUDY_AREA["south"] <= latitude <= STUDY_AREA["north"]
        and STUDY_AREA["west"] <= longitude <= STUDY_AREA["east"]
    )


PLACE_INDEX = PlaceIndex.from_osm(OSM_DATA, is_in_study_area)


STORE = Store(Path(os.environ.get("SHADES_DB", DEFAULT_PATH)))


def covered_edges_provider() -> set[str]:
    return STORE.covered_edges()


class RouteError(Exception):
    pass


def validate_point(point: Any, field_name: str) -> tuple[float, float]:
    if not isinstance(point, dict):
        raise ValueError(f"{field_name} must contain latitude and longitude")
    try:
        latitude = float(point["latitude"])
        longitude = float(point["longitude"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must contain numeric latitude and longitude") from error
    if not is_in_study_area(latitude, longitude):
        raise ValueError(f"The {field_name} is outside the Katipunan study area. Choose a point inside the test area.")
    return latitude, longitude


def exposure_cost(model: ExposureModel, covered: set[str]) -> Callable[[int, int, float], float]:
    """Route cost that makes sun-exposed or unknown metres SHADIER_SUN_WEIGHT times as costly."""
    graph = WALKING_GRAPH

    def cost(first: int, second: int, length: float) -> float:
        if edge_key(graph.edge_ways.get((first, second), 0), first, second) in covered:
            return length
        shaded, exposed = model.segment_lengths(graph.point(first), graph.point(second))
        return max(length, shaded + exposed * SHADIER_SUN_WEIGHT)

    return cost


def comfort_window(geometry: list[list[float]], covered_flags: list[bool], travel_time: str) -> dict[str, Any]:
    """Sun exposure now, +15 and +30 minutes, and whether to wait (PRD F-15). Uses sun exposure only."""
    times = []
    for offset in COMFORT_OFFSETS_MINUTES:
        when = shift_time(travel_time, offset)
        model = ExposureModel(HEIGHT_RASTER, when, STUDY_CENTER[0], STUDY_CENTER[1])
        exposure = analyze_route(geometry, when, HEIGHT_RASTER, covered_flags, model)
        times.append({"offset_minutes": offset, "time": when, "sun_percent": exposure["sun_percent"]})
    return {"times": times, **recommend(times)}


def recommend(times: list[dict[str, Any]]) -> dict[str, Any]:
    now = times[0]["sun_percent"]
    best = min(times[1:], key=lambda entry: entry["sun_percent"])
    if now - best["sun_percent"] >= WAIT_THRESHOLD_POINTS:
        return {"recommendation": "wait", "best_time": best["time"], "best_offset_minutes": best["offset_minutes"]}
    return {"recommendation": "walk_now", "best_time": times[0]["time"], "best_offset_minutes": 0}


def build_route(route_id: str, label: str, path: list[int], travel_time: str, model: ExposureModel, covered: set[str]) -> dict[str, Any]:
    geometry, distance_m = WALKING_GRAPH.route_geometry(path)
    edges = WALKING_GRAPH.path_edges(path)
    covered_flags = [edge["edge_key"] in covered for edge in edges]
    return {
        "id": route_id,
        "label": label,
        "geometry": geometry,
        "distance_m": round(distance_m, 1),
        "duration_minutes": round(distance_m / WALKING_SPEED_M_PER_MIN, 1),
        "exposure": analyze_route(geometry, travel_time, HEIGHT_RASTER, covered_flags, model),
        "comfort_window": comfort_window(geometry, covered_flags, travel_time),
        "edges": [{**edge, "length_m": round(edge["length_m"], 1)} for edge in edges],
    }


def compare(shortest: dict[str, Any], shadier: dict[str, Any]) -> dict[str, float]:
    """How much less sun the shadier route has than the shortest (PRD F-09)."""
    return {
        "sun_percent_points_less": round(shortest["exposure"]["sun_percent"] - shadier["exposure"]["sun_percent"], 1),
        "sun_minutes_less": round(shortest["exposure"]["sun_minutes"] - shadier["exposure"]["sun_minutes"], 1),
        "extra_distance_m": round(shadier["distance_m"] - shortest["distance_m"], 1),
        "extra_minutes": round(shadier["duration_minutes"] - shortest["duration_minutes"], 1),
    }


def build_routes(start: tuple[float, float], destination: tuple[float, float], travel_time: str) -> dict[str, Any]:
    start_node = WALKING_GRAPH.nearest_node(start)
    destination_node = WALKING_GRAPH.nearest_node(destination)
    if start_node == destination_node:
        raise RouteError("The start and destination are at the same spot on the walking network. Choose points farther apart.")
    shortest_path = WALKING_GRAPH.route_nodes(start_node, destination_node)
    if len(shortest_path) < 2:
        raise RouteError("No walking route was found between those points. Try moving the start or destination closer to a street or path.")

    covered = covered_edges_provider()
    model = ExposureModel(HEIGHT_RASTER, travel_time, STUDY_CENTER[0], STUDY_CENTER[1])
    shortest = build_route("shortest", "Shortest route", shortest_path, travel_time, model, covered)
    routes = [shortest]
    shadier_path = WALKING_GRAPH.route_nodes(start_node, destination_node, exposure_cost(model, covered))
    note = None
    if shadier_path and shadier_path != shortest_path:
        shadier = build_route("shadier", "Shadier route", shadier_path, travel_time, model, covered)
        if shadier["exposure"]["sun_percent"] < shortest["exposure"]["sun_percent"]:
            routes.append(shadier)
    if len(routes) == 1:
        note = "No shadier alternative was found for this trip at this time."
    # Walkability is shown for information only, after the routes are chosen (PRD S-09, C-02).
    stats = STORE.rating_stats([edge["way_id"] for route in routes for edge in route["edges"]])
    for route in routes:
        route["walkability"] = route_walkability(route["edges"], stats)
    return {
        "routes": routes,
        "comparison": compare(routes[0], routes[1]) if len(routes) == 2 else None,
        "alternative_note": note,
    }


def create_route_response(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    try:
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        start = validate_point(payload.get("start"), "start")
        destination = validate_point(payload.get("destination"), "destination")
        travel_time = payload.get("travel_time")
        if travel_time:
            datetime.fromisoformat(str(travel_time).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        return 400, {"error": str(error)}

    if not travel_time:
        travel_time = datetime.now().astimezone().isoformat(timespec="minutes")
    try:
        result = build_routes(start, destination, str(travel_time))
    except RouteError as error:
        return 422, {"error": str(error)}

    # Weather is fetched after routing and never feeds back into it (PRD F-07, F-10, F-11).
    weather = fetch_weather(start[0], start[1], str(travel_time))
    return 200, {
        "study_area": STUDY_AREA,
        "travel_time": travel_time,
        **result,
        "weather": weather,
        "assumptions": ASSUMPTIONS,
        "data": {"building_heights": BUILDING_HEIGHT_REPORT},
    }


def create_weather_response(query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    """Weather readings for the study area at a time, for the header before any route exists."""
    travel_time = (query.get("time") or [""])[0]
    try:
        if travel_time:
            datetime.fromisoformat(travel_time.replace("Z", "+00:00"))
        else:
            travel_time = datetime.now().astimezone().isoformat(timespec="minutes")
    except ValueError:
        return 400, {"error": "time must be an ISO date and time"}
    return 200, {"travel_time": travel_time, "weather": fetch_weather(STUDY_CENTER[0], STUDY_CENTER[1], travel_time)}


def create_places_response(query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    return 200, {"places": PLACE_INDEX.search((query.get("q") or [""])[0])}


def street_payload(way_id: int) -> dict[str, Any]:
    count, average = STORE.rating_stats([way_id]).get(way_id, (0, None))
    return {"way_id": way_id, "name": WALKING_GRAPH.way_names.get(way_id, "Street"), "walkability": {"basis": "user ratings", **street_score(count, average)}}


def create_street_response(way_id: int) -> tuple[int, dict[str, Any]]:
    if way_id not in WALKING_GRAPH.way_names:
        return 404, {"error": "That street is not on the walking network."}
    return 200, street_payload(way_id)


def create_nearest_street_response(query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    """Street section closest to a tapped map point (the tap, not the user's location)."""
    try:
        latitude = float((query.get("lat") or [""])[0])
        longitude = float((query.get("lon") or [""])[0])
    except ValueError:
        return 400, {"error": "lat and lon must be numbers"}
    edge = WALKING_GRAPH.nearest_edge((latitude, longitude))
    if edge is None:
        return 404, {"error": "No street or path here. Tap closer to a street."}
    covered = edge["edge_key"] in STORE.covered_edges()
    return 200, {**street_payload(edge["way_id"]), "section": {**edge, "covered": covered}}


def create_rating_response(way_id: int, payload: Any) -> tuple[int, dict[str, Any]]:
    if way_id not in WALKING_GRAPH.way_names:
        return 404, {"error": "That street is not on the walking network."}
    try:
        STORE.add_rating(way_id, payload.get("rating") if isinstance(payload, dict) else None)
    except ValueError as error:
        return 400, {"error": str(error)}
    return 200, street_payload(way_id)


def create_covered_list_response() -> tuple[int, dict[str, Any]]:
    sections = [WALKING_GRAPH.edge_from_key(key) for key in sorted(STORE.covered_edges())]
    return 200, {"covered": [section for section in sections if section]}


def create_covered_update_response(key: str, covered: bool) -> tuple[int, dict[str, Any]]:
    section = WALKING_GRAPH.edge_from_key(key)
    if section is None:
        return 404, {"error": "That street section is not on the walking network."}
    STORE.set_covered(key, covered)
    return 200, {**section, "covered": covered}


def parse_way_id(text: str) -> int | None:
    return int(text) if text.isdigit() else None


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Request lines can contain locations; do not log them (PRD C-04).
        return

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self._send_json(200, {"status": "ok", "study_area": STUDY_AREA})
        elif parsed.path == "/api/weather":
            self._send_json(*create_weather_response(query))
        elif parsed.path == "/api/places":
            self._send_json(*create_places_response(query))
        elif parsed.path == "/api/streets/nearest":
            self._send_json(*create_nearest_street_response(query))
        elif parsed.path.startswith("/api/streets/") and parse_way_id(parsed.path.rsplit("/", 1)[1]) is not None:
            self._send_json(*create_street_response(parse_way_id(parsed.path.rsplit("/", 1)[1])))
        elif parsed.path == "/api/covered":
            self._send_json(*create_covered_list_response())
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON"})
            return
        parts = path.strip("/").split("/")
        if path == "/api/routes":
            self._send_json(*create_route_response(payload))
        elif len(parts) == 4 and parts[:2] == ["api", "streets"] and parts[3] == "ratings" and parse_way_id(parts[2]) is not None:
            self._send_json(*create_rating_response(parse_way_id(parts[2]), payload))
        else:
            self._send_json(404, {"error": "Not found"})

    def _covered(self, covered: bool) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/covered/"):
            self._send_json(404, {"error": "Not found"})
            return
        self._send_json(*create_covered_update_response(unquote(path[len("/api/covered/"):]), covered))

    def do_PUT(self) -> None:
        self._covered(True)

    def do_DELETE(self) -> None:
        self._covered(False)


def main() -> None:
    port = int(os.environ.get("SHADES_API_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    print(f"Shades API listening on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
