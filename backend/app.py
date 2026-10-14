"""Minimal API for the Katipunan shade-routing prototype."""

from __future__ import annotations

import json
import math
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from routing import WalkingGraph
from shade import HeightRaster, analyze_route
from uv import fetch_uv_context


STUDY_AREA = {
    "name": "Katipunan and Ateneo de Manila University",
    "south": 14.635,
    "north": 14.650,
    "west": 121.065,
    "east": 121.083,
}

WALKING_GRAPH = WalkingGraph.from_osm()
HEIGHT_RASTER = HeightRaster.from_file()


def is_in_study_area(latitude: float, longitude: float) -> bool:
    return (
        STUDY_AREA["south"] <= latitude <= STUDY_AREA["north"]
        and STUDY_AREA["west"] <= longitude <= STUDY_AREA["east"]
    )


def validate_point(point: Any, field_name: str) -> tuple[float, float]:
    if not isinstance(point, dict):
        raise ValueError(f"{field_name} must contain latitude and longitude")

    try:
        latitude = float(point["latitude"])
        longitude = float(point["longitude"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must contain numeric latitude and longitude") from error

    if not is_in_study_area(latitude, longitude):
        raise ValueError(f"{field_name} must be inside the Katipunan study area")

    return latitude, longitude


def haversine_meters(start: tuple[float, float], end: tuple[float, float]) -> float:
    earth_radius_m = 6_371_000
    start_lat, start_lon = map(math.radians, start)
    end_lat, end_lon = map(math.radians, end)
    delta_lat = end_lat - start_lat
    delta_lon = end_lon - start_lon
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(start_lat) * math.cos(end_lat) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_m * math.asin(math.sqrt(haversine))


def build_routes(start: tuple[float, float], destination: tuple[float, float], travel_time: str) -> list[dict[str, Any]]:
    first_path = WALKING_GRAPH.route(start, destination)
    if not first_path:
        return []
    first_geometry, first_distance = WALKING_GRAPH.route_geometry(first_path)
    routes = [build_route("walking-route-1", "Walking route 1", first_geometry, first_distance, travel_time)]

    second_path = WALKING_GRAPH.route(start, destination, zip(first_path, first_path[1:]))
    if second_path and second_path != first_path:
        second_geometry, second_distance = WALKING_GRAPH.route_geometry(second_path)
        routes.append(build_route("walking-route-2", "Walking route 2", second_geometry, second_distance, travel_time))
    return routes


def build_route(route_id: str, label: str, geometry: list[list[float]], distance_m: float, travel_time: str) -> dict[str, Any]:
    return {
        "id": route_id,
        "label": label,
        "geometry": geometry,
        "distance_m": round(distance_m, 1),
        "duration_minutes": round(distance_m / 80, 1),
        "exposure": analyze_route(geometry, travel_time, HEIGHT_RASTER),
    }


def create_route_response(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    try:
        start = validate_point(payload.get("start"), "start")
        destination = validate_point(payload.get("destination"), "destination")
        travel_time = payload.get("travel_time")
        if travel_time:
            datetime.fromisoformat(str(travel_time).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        return 400, {"error": str(error)}

    if not travel_time:
        travel_time = datetime.now().astimezone().isoformat(timespec="minutes")
    routes = build_routes(start, destination, str(travel_time))
    if not routes:
        return 422, {"error": "No walking route was found between those points."}
    uv_context = fetch_uv_context(start[0], start[1], str(travel_time))

    return 200, {
        "study_area": STUDY_AREA,
        "travel_time": travel_time,
        "data_status": "walking_network_loaded",
        "message": "Walking routes are generated from the local OpenStreetMap extract and classified using the local building-height raster.",
        "uv_context": uv_context,
        "routes": routes,
    }


class RequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/health":
            self._send_json(200, {"status": "ok", "study_area": STUDY_AREA})
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/routes":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON"})
            return
        status, response = create_route_response(payload)
        self._send_json(status, response)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8000), RequestHandler)
    print("Shade API listening on http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()