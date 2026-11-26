"""HTTP API for the Shades shade-routing prototype (Python standard library only)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from area import HOME, MAX_TRIP_M, MAX_WALK_M, STUDY_AREA, in_study_area
from places import PlaceIndex
from routing import WalkingGraph, edge_key, haversine_meters
from shade import WALKING_SPEED_M_PER_MIN, ExposureModel, HeightRaster, analyze_route, shift_time
from storage import StoreError, open_store, route_walkability, street_score
from tiles import TileStore
from weather import fetch_weather

DERIVED_DIR = Path(__file__).parents[1] / "datasets" / "derived"
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

# Prebuilt data (backend/build_tiles.py). Nothing is parsed at startup: graph tiles load on
# demand, place search reads a SQLite index, and buildings without heights come as raster cells.
BUILD_INFO = json.loads((DERIVED_DIR / "build-info.json").read_text(encoding="utf-8"))
WALKING_GRAPH = WalkingGraph(TileStore(), BUILD_INFO.get("indoor_edges_excluded", 0))
HEIGHT_RASTER = HeightRaster.from_file()
HEIGHT_RASTER.mark_unknown_cells(DERIVED_DIR / "unknown-height-cells.bin")
BUILDING_HEIGHT_REPORT = BUILD_INFO["building_heights"]
PLACE_INDEX = PlaceIndex(DERIVED_DIR / "places.db")


def is_in_study_area(latitude: float, longitude: float) -> bool:
    return in_study_area(latitude, longitude)


STORE = open_store()
SAVE_FAILED = "Ratings and covered marks can't be saved right now. Please try again."


def covered_edges_provider() -> set[str]:
    """Covered marks, or none when the store is unreachable, so routes still work."""
    try:
        return STORE.covered_edges()
    except StoreError:
        return set()


def rating_stats(way_ids: list[int]) -> dict[int, tuple[int, float]] | None:
    """Ratings per street, or None when the store is unreachable."""
    try:
        return STORE.rating_stats(way_ids)
    except StoreError:
        return None


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
        raise ValueError(f"The {field_name} is outside the study area ({STUDY_AREA['name']}). Choose a point inside it.")
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
        # Full exposure per time so the app can draw the route's sun/shade for that time.
        times.append({"offset_minutes": offset, "time": when, "sun_percent": exposure["sun_percent"], "exposure": exposure})
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
    # Walking trips only: keeps every request to the tiles along one corridor (user decision: 10 km).
    if haversine_meters(start, destination) > MAX_TRIP_M:
        raise RouteError(f"Too far for a walking route (over {MAX_TRIP_M // 1000} km). Choose points closer together.")
    start_node = WALKING_GRAPH.nearest_node(start)
    destination_node = WALKING_GRAPH.nearest_node(destination)
    if start_node is None or destination_node is None:
        which = "start" if start_node is None else "destination"
        raise RouteError(f"There is no walking path near the {which}. Choose a point closer to a street or path.")
    if start_node == destination_node:
        raise RouteError("The start and destination are at the same spot on the walking network. Choose points farther apart.")
    # Search limits keep a failing request from exploring the whole city. Detours around rivers
    # and gated villages can be long (a 337 m gap needed a 4.5 km walk), so the shortest search
    # allows 3x the straight-line distance + 5 km, up to MAX_WALK_M. The shadier search can never
    # beat 3x the shortest route's length (its worst edge cost is 3x length), so that bound loses nothing.
    straight = haversine_meters(WALKING_GRAPH.coordinates[start_node], WALKING_GRAPH.coordinates[destination_node])
    shortest_path = WALKING_GRAPH.route_nodes(start_node, destination_node, max_cost=min(3 * straight + 5000, MAX_WALK_M))
    if len(shortest_path) < 2:
        raise RouteError("No walking route was found between those points. Try moving the start or destination closer to a street or path.")

    covered = covered_edges_provider()
    model = ExposureModel(HEIGHT_RASTER, travel_time, STUDY_CENTER[0], STUDY_CENTER[1])
    shortest = build_route("shortest", "Shortest route", shortest_path, travel_time, model, covered)
    routes = [shortest]
    shadier_limit = SHADIER_SUN_WEIGHT * WALKING_GRAPH.path_cost(shortest_path) + 1
    shadier_path = WALKING_GRAPH.route_nodes(start_node, destination_node, exposure_cost(model, covered), max_cost=shadier_limit)
    note = None
    if shadier_path and shadier_path != shortest_path:
        shadier = build_route("shadier", "Shadier route", shadier_path, travel_time, model, covered)
        if shadier["exposure"]["sun_percent"] < shortest["exposure"]["sun_percent"]:
            routes.append(shadier)
    if len(routes) == 1:
        note = "No shadier alternative was found for this trip at this time."
    # Walkability is shown for information only, after the routes are chosen (PRD S-09, C-02).
    stats = rating_stats([edge["way_id"] for route in routes for edge in route["edges"]])
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
    # The exact start is never shared with the weather service (C-04): rounded to about 11 km.
    weather = fetch_weather(round(start[0], 1), round(start[1], 1), str(travel_time))
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


def create_places_response(payload: Any) -> tuple[int, dict[str, Any]]:
    """Place search; `near` ({latitude, longitude}) ranks same-named places (chain stores) by distance.

    Without it, results rank from HOME (Katipunan), where the map opens. It is a POST because
    hosts log query strings, and points must stay out of logs. The frontend never sends the
    user's own position here (PRD C-04).
    """
    payload = payload if isinstance(payload, dict) else {}
    try:
        near = validate_point(payload.get("near"), "near point")
    except ValueError:
        near = HOME
    return 200, {"places": PLACE_INDEX.search(str(payload.get("q") or ""), near=near)}


def street_payload(way_id: int) -> dict[str, Any]:
    stats = rating_stats([way_id])
    if stats is None:
        score = {"status": "not available", "rating_count": None, "average": None}
    else:
        score = street_score(*stats.get(way_id, (0, None)))
    return {
        "way_id": way_id,
        "name": WALKING_GRAPH.way_names.get(way_id, "Street"),
        # False when `name` is only the path type ("Footway"), as for unnamed ways.
        "named": WALKING_GRAPH.is_named(way_id),
        "walkability": {"basis": "user ratings", **score},
    }


def create_street_response(way_id: int) -> tuple[int, dict[str, Any]]:
    if way_id not in WALKING_GRAPH.way_names:
        return 404, {"error": "That street is not on the walking network."}
    return 200, street_payload(way_id)


def create_nearest_street_response(payload: Any) -> tuple[int, dict[str, Any]]:
    """Street section closest to a tapped map point. A POST, so the point stays out of URL logs (C-04)."""
    try:
        point = validate_point(payload, "point")
    except ValueError as error:
        return 400, {"error": str(error)}
    edge = WALKING_GRAPH.nearest_edge(point)
    if edge is None:
        return 404, {"error": "No street or path here. Tap closer to a street."}
    covered = edge["edge_key"] in covered_edges_provider()
    return 200, {**street_payload(edge["way_id"]), "section": {**edge, "covered": covered}}


def create_rating_response(way_id: int, payload: Any) -> tuple[int, dict[str, Any]]:
    if way_id not in WALKING_GRAPH.way_names:
        return 404, {"error": "That street is not on the walking network."}
    try:
        STORE.add_rating(way_id, payload.get("rating") if isinstance(payload, dict) else None)
    except ValueError as error:
        return 400, {"error": str(error)}
    except StoreError:
        return 503, {"error": SAVE_FAILED}
    return 200, street_payload(way_id)


def create_covered_list_response() -> tuple[int, dict[str, Any]]:
    sections = [WALKING_GRAPH.edge_from_key(key) for key in sorted(covered_edges_provider())]
    return 200, {"covered": [section for section in sections if section]}


def create_covered_update_response(key: str, covered: bool) -> tuple[int, dict[str, Any]]:
    section = WALKING_GRAPH.edge_from_key(key)
    if section is None:
        return 404, {"error": "That street section is not on the walking network."}
    try:
        STORE.set_covered(key, covered)
    except StoreError:
        return 503, {"error": SAVE_FAILED}
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
        elif path == "/api/places":
            self._send_json(*create_places_response(payload))
        elif path == "/api/streets/nearest":
            self._send_json(*create_nearest_street_response(payload))
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
