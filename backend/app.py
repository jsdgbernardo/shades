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
from rail import RIDE_SPEED_KMH, TRANSFER_MINUTES, RailNetwork
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
    # Train option (stretch, F-18, C-07): estimates only, no schedules or service status.
    "train_notes": [
        f"Train times are estimates: ride distance at {RIDE_SPEED_KMH:g} km/h (from published end-to-end times) plus {TRANSFER_MINUTES:g} min per transfer.",
        "Train service status, schedules, delays and crowding are not checked.",
        "The second walk is scored at the time you are expected to reach it, so its figures are approximate.",
    ],
}

# Walk, train, walk option (PRD F-16): each walk at most this long, and the stations searched.
TRAIN_WALK_MAX_M = 2000.0  # user decision 2026-11-26 (was 1 km, PRD F-16 proposed)
TRAIN_STATIONS_PER_END = 3

# Prebuilt data (backend/build_tiles.py). Nothing is parsed at startup: graph tiles load on
# demand, place search reads a SQLite index, and buildings without heights come as raster cells.
BUILD_INFO = json.loads((DERIVED_DIR / "build-info.json").read_text(encoding="utf-8"))
WALKING_GRAPH = WalkingGraph(TileStore(), BUILD_INFO.get("indoor_edges_excluded", 0))
HEIGHT_RASTER = HeightRaster.from_file()
HEIGHT_RASTER.mark_unknown_cells(DERIVED_DIR / "unknown-height-cells.bin")
BUILDING_HEIGHT_REPORT = BUILD_INFO["building_heights"]
PLACE_INDEX = PlaceIndex(DERIVED_DIR / "places.db")
RAIL = RailNetwork(DERIVED_DIR / "rail.json")


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


class _Models:
    """One exposure model per travel time, shared by every walk scored at that time."""

    def __init__(self) -> None:
        self._models: dict[str, ExposureModel] = {}

    def at(self, when: str) -> ExposureModel:
        if when not in self._models:
            self._models[when] = ExposureModel(HEIGHT_RASTER, when, STUDY_CENTER[0], STUDY_CENTER[1])
        return self._models[when]


def walk_leg(path: list[int], when: str, models: _Models, covered: set[str], approximate: bool = False) -> dict[str, Any]:
    """One walking part of a train option, scored at `when`."""
    geometry, length = WALKING_GRAPH.route_geometry(path)
    edges = WALKING_GRAPH.path_edges(path)
    flags = [edge["edge_key"] in covered for edge in edges]
    return {
        "type": "walk",
        "geometry": geometry,
        "distance_m": round(length, 1),
        "duration_minutes": round(length / WALKING_SPEED_M_PER_MIN, 1),
        "time": when,
        "approximate": approximate,
        "exposure": analyze_route(geometry, when, HEIGHT_RASTER, flags, models.at(when)),
        "edges": [{**edge, "length_m": round(edge["length_m"], 1)} for edge in edges],
        "_flags": flags,
    }


def combine_walks(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """F-17: sun figures of a train option count the two walks only."""
    total = first["distance_m"] + second["distance_m"]
    exposures = (first["exposure"], second["exposure"])
    sun = sum(exposure["sun_length_m"] for exposure in exposures)
    unknown = sum(exposure["unknown_length_m"] for exposure in exposures)
    covered = sum(exposure["covered_percent"] / 100 * walk["distance_m"] for exposure, walk in zip(exposures, (first, second)))
    sections = first["exposure"]["sections"] + [{**section, "approximate": True} for section in second["exposure"]["sections"]]
    return {
        "status": "computed",
        "sun_percent": round(sun / total * 100, 1) if total else 0.0,
        "sun_minutes": round(sun / WALKING_SPEED_M_PER_MIN, 1),
        "shaded_percent": round((total - sun) / total * 100, 1) if total else 0.0,
        "unknown_percent": round(unknown / total * 100, 1) if total else 0.0,
        "covered_percent": round(covered / total * 100, 1) if total else 0.0,
        "sun_length_m": round(sun, 1),
        "unknown_length_m": round(unknown, 1),
        "sections": sections,
        "second_walk_approximate": True,
    }


def train_candidates(start_node: int, destination_node: int, travel_time: str, covered: set[str], models: _Models) -> list[dict[str, Any]]:
    """Every qualifying walk, train, walk option (F-16), with its figures. Empty when none qualifies.

    Qualifies: both walks are TRAIN_WALK_MAX_M or less on foot, and the alighting station is nearer
    the destination than the boarding station. The first walk is scored at the chosen time; the
    second at that time plus the first walk and the estimated ride (F-19).
    """
    start_point = WALKING_GRAPH.coordinates[start_node]
    end_point = WALKING_GRAPH.coordinates[destination_node]

    def walks(near: tuple[float, float], to_station: bool) -> list[tuple[Any, list[int]]]:
        found = []
        for station, entrance, _ in RAIL.stations_near(near, TRAIN_WALK_MAX_M)[:TRAIN_STATIONS_PER_END]:
            node = WALKING_GRAPH.nearest_node(entrance, max_distance_m=150)
            if node is None:
                continue
            first, second = (start_node, node) if to_station else (node, destination_node)
            path = [first] if first == second else WALKING_GRAPH.route_nodes(first, second, max_cost=TRAIN_WALK_MAX_M)
            if len(path) >= 2 and WALKING_GRAPH.path_cost(path) <= TRAIN_WALK_MAX_M:
                found.append((station, path))
        return found

    boardings, alightings = walks(start_point, True), walks(end_point, False)
    options = []
    first_walks: dict[str, dict[str, Any]] = {}
    for boarding, first_path in boardings:
        for alighting, second_path in alightings:
            if alighting.id == boarding.id:
                continue
            if haversine_meters((alighting.lat, alighting.lon), end_point) >= haversine_meters((boarding.lat, boarding.lon), end_point):
                continue
            ride = RAIL.ride(boarding.id, alighting.id)
            if ride is None:
                continue
            if boarding.id not in first_walks:
                first_walks[boarding.id] = walk_leg(first_path, travel_time, models, covered)
            first = first_walks[boarding.id]
            reach = shift_time(travel_time, round(first["duration_minutes"] + ride.minutes))
            second = walk_leg(second_path, reach, models, covered, approximate=True)
            total = first["duration_minutes"] + ride.minutes + second["duration_minutes"]
            options.append({
                "boarding": boarding, "alighting": alighting, "ride": ride, "walks": (first, second),
                "sun_minutes": round(first["exposure"]["sun_minutes"] + second["exposure"]["sun_minutes"], 1),
                "total_minutes": round(total, 1),
            })
    return options


def beats_walking(option: dict[str, Any], walking: list[dict[str, Any]]) -> bool:
    """False when a train option is no better than walking in sun minutes nor in total time (user
    decision, PRD F-16): with walks of up to 2 km, a short trip could otherwise get a longer, sunnier
    train trip. With no walking route (trips over 10 km), any option counts."""
    if not walking:
        return True
    least_sun = min(route["exposure"]["sun_minutes"] for route in walking)
    least_time = min(route["total_minutes"] for route in walking)
    return option["sun_minutes"] < least_sun or option["total_minutes"] < least_time


def best_train_option(options: list[dict[str, Any]], walking: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """F-16: among options that beat walking in sun or time, the fewest minutes in sun across the
    two walks; ties go to the shorter total time."""
    useful = [option for option in options if beats_walking(option, walking or [])]
    return min(useful, key=lambda option: (option["sun_minutes"], option["total_minutes"]), default=None)


def train_route(option: dict[str, Any], travel_time: str, covered: set[str], models: _Models) -> dict[str, Any]:
    first, second = option["walks"]
    ride = option["ride"]
    exposure = combine_walks(first, second)
    ride_leg = {
        "type": "ride",
        "from": option["boarding"].name,
        "to": option["alighting"].name,
        "segments": ride.segments,
        "transfers": ride.transfers,
        "geometry": [point for segment in ride.segments for point in segment["geometry"]],
    }
    walking_m = first["distance_m"] + second["distance_m"]
    lines = " → ".join(dict.fromkeys(segment["line_name"].replace("Line ", "-").replace(" -", "-") for segment in ride.segments))
    return {
        "id": "train",
        "kind": "train",
        "label": f"Train · {lines}",
        "summary": f"{option['boarding'].name} → {option['alighting'].name}",
        # Map and fit use the whole trip; the sections cover the walks only.
        "geometry": first["geometry"] + ride_leg["geometry"] + second["geometry"],
        "distance_m": round(walking_m, 1),
        "duration_minutes": round(walking_m / WALKING_SPEED_M_PER_MIN, 1),
        "total_minutes": option["total_minutes"],
        "total_is_estimate": True,
        "exposure": exposure,
        "comfort_window": train_comfort_window(first, second, ride.minutes, travel_time, covered, models),
        "legs": [_public(first), ride_leg, _public(second)],
        "edges": first["edges"] + second["edges"],
    }


def _public(leg: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in leg.items() if not key.startswith("_")}


def train_comfort_window(first: dict[str, Any], second: dict[str, Any], ride_minutes: float, travel_time: str,
                         covered: set[str], models: _Models) -> dict[str, Any]:
    """F-15 for a train option: each later start also shifts the second walk (F-19)."""
    times = []
    for offset in COMFORT_OFFSETS_MINUTES:
        when = shift_time(travel_time, offset)
        reach = shift_time(when, round(first["duration_minutes"] + ride_minutes))
        one = analyze_route(first["geometry"], when, HEIGHT_RASTER, first["_flags"], models.at(when))
        two = analyze_route(second["geometry"], reach, HEIGHT_RASTER, second["_flags"], models.at(reach))
        exposure = combine_walks({**first, "exposure": one}, {**second, "exposure": two})
        times.append({"offset_minutes": offset, "time": when, "sun_percent": exposure["sun_percent"], "exposure": exposure})
    return {"times": times, **recommend(times)}


def compare(shortest: dict[str, Any], shadier: dict[str, Any]) -> dict[str, float]:
    """How much less sun the shadier route has than the shortest (PRD F-09)."""
    return {
        "sun_percent_points_less": round(shortest["exposure"]["sun_percent"] - shadier["exposure"]["sun_percent"], 1),
        "sun_minutes_less": round(shortest["exposure"]["sun_minutes"] - shadier["exposure"]["sun_minutes"], 1),
        "extra_distance_m": round(shadier["distance_m"] - shortest["distance_m"], 1),
        "extra_minutes": round(shadier["duration_minutes"] - shortest["duration_minutes"], 1),
    }


def build_routes(start: tuple[float, float], destination: tuple[float, float], travel_time: str) -> dict[str, Any]:
    # Walking routes stop at 10 km straight-line (user decision); longer trips can still get a
    # train option (F-16), whose two walks are short.
    too_far_to_walk = haversine_meters(start, destination) > MAX_TRIP_M
    start_node = WALKING_GRAPH.nearest_node(start)
    destination_node = WALKING_GRAPH.nearest_node(destination)
    if start_node is None or destination_node is None:
        which = "start" if start_node is None else "destination"
        raise RouteError(f"There is no walking path near the {which}. Choose a point closer to a street or path.")
    if start_node == destination_node:
        raise RouteError("The start and destination are at the same spot on the walking network. Choose points farther apart.")
    covered = covered_edges_provider()
    models = _Models()
    if too_far_to_walk:
        option = best_train_option(train_candidates(start_node, destination_node, travel_time, covered, models))
        if option is None:
            raise RouteError(f"Too far for a walking route (over {MAX_TRIP_M // 1000} km), and no train option fits. Choose points closer together.")
        routes = [train_route(option, travel_time, covered, models)]
        add_walkability(routes)
        return {"routes": routes, "comparison": None,
                "alternative_note": f"Too far to walk (over {MAX_TRIP_M // 1000} km), so only the train option is shown."}
    # Search limits keep a failing request from exploring the whole city. Detours around rivers
    # and gated villages can be long (a 337 m gap needed a 4.5 km walk), so the shortest search
    # allows 3x the straight-line distance + 5 km, up to MAX_WALK_M. The shadier search can never
    # beat 3x the shortest route's length (its worst edge cost is 3x length), so that bound loses nothing.
    straight = haversine_meters(WALKING_GRAPH.coordinates[start_node], WALKING_GRAPH.coordinates[destination_node])
    shortest_path = WALKING_GRAPH.route_nodes(start_node, destination_node, max_cost=min(3 * straight + 5000, MAX_WALK_M))
    if len(shortest_path) < 2:
        raise RouteError("No walking route was found between those points. Try moving the start or destination closer to a street or path.")

    model = models.at(travel_time)
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
    comparison = compare(routes[0], routes[1]) if len(routes) == 2 else None
    for route in routes:
        route["total_minutes"] = route["duration_minutes"]  # F-17: walking-only total = walking time
    # Train option (stretch, F-16) alongside the walking routes; none and no error when nothing fits.
    option = best_train_option(train_candidates(start_node, destination_node, travel_time, covered, models), routes)
    if option is not None:
        routes.append(train_route(option, travel_time, covered, models))
    add_walkability(routes)
    return {"routes": routes, "comparison": comparison, "alternative_note": note}


def add_walkability(routes: list[dict[str, Any]]) -> None:
    """Walkability is shown for information only, after the routes are chosen (PRD S-09, C-02)."""
    stats = rating_stats([edge["way_id"] for route in routes for edge in route["edges"]])
    for route in routes:
        route["walkability"] = route_walkability(route["edges"], stats)


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
    payload = payload if isinstance(payload, dict) else {}
    token = payload.get("token") if isinstance(payload.get("token"), str) else None
    try:
        # With the device's token for this street, its earlier rating is replaced, not added to.
        token = STORE.add_rating(way_id, payload.get("rating"), token)
    except ValueError as error:
        return 400, {"error": str(error)}
    except StoreError:
        return 503, {"error": SAVE_FAILED}
    return 200, {**street_payload(way_id), "token": token}


def create_rating_removal_response(way_id: int, payload: Any) -> tuple[int, dict[str, Any]]:
    """Removes the rating made on this device (identified by its token, sent in the body)."""
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        return 400, {"error": "A rating token is needed to remove a rating."}
    try:
        removed = STORE.remove_rating(way_id, token)
    except StoreError:
        return 503, {"error": SAVE_FAILED}
    if not removed:
        return 404, {"error": "That rating was not found. It may already be removed."}
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
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "streets"] and parts[3] == "ratings" and parse_way_id(parts[2]) is not None:
            try:
                payload = self._read_json()
            except (ValueError, json.JSONDecodeError):
                self._send_json(400, {"error": "Request body must be valid JSON"})
                return
            self._send_json(*create_rating_removal_response(parse_way_id(parts[2]), payload))
            return
        self._covered(False)


def main() -> None:
    port = int(os.environ.get("SHADES_API_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    print(f"Shades API listening on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
