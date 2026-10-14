"""Small OpenStreetMap walking graph for the Katipunan prototype."""

from __future__ import annotations

import heapq
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


NETWORK_PATH = Path(__file__).parents[1] / "datasets" / "katipunan-walking-network.osm"
WALKABLE_HIGHWAYS = {
    "cycleway",
    "footway",
    "living_street",
    "path",
    "pedestrian",
    "primary",
    "primary_link",
    "residential",
    "secondary",
    "service",
    "steps",
    "tertiary",
    "unclassified",
}


class WalkingGraph:
    def __init__(self, coordinates: dict[int, tuple[float, float]], edges: dict[int, dict[int, float]]) -> None:
        self.coordinates = coordinates
        self.edges = edges

    @classmethod
    def from_osm(cls, path: Path = NETWORK_PATH) -> "WalkingGraph":
        root = ET.parse(path).getroot()
        coordinates = {
            int(node.attrib["id"]): (float(node.attrib["lat"]), float(node.attrib["lon"]))
            for node in root.findall("node")
        }
        edges: dict[int, dict[int, float]] = {}

        for way in root.findall("way"):
            tags = {tag.attrib.get("k"): tag.attrib.get("v") for tag in way.findall("tag")}
            highway = tags.get("highway")
            if highway not in WALKABLE_HIGHWAYS or tags.get("access") in {"no", "private"} or tags.get("foot") == "no":
                continue

            node_ids = [int(node.attrib["ref"]) for node in way.findall("nd")]
            oneway = tags.get("oneway") in {"yes", "1", "true"}
            reverse = tags.get("oneway") == "-1"
            for first, second in zip(node_ids, node_ids[1:]):
                if first not in coordinates or second not in coordinates:
                    continue
                if reverse:
                    first, second = second, first
                distance = haversine_meters(coordinates[first], coordinates[second])
                edges.setdefault(first, {})[second] = min(distance, edges.setdefault(first, {}).get(second, math.inf))
                if not oneway:
                    edges.setdefault(second, {})[first] = min(distance, edges.setdefault(second, {}).get(first, math.inf))

        return cls(coordinates, edges)

    def nearest_node(self, point: tuple[float, float]) -> int:
        return min(self.edges, key=lambda node_id: haversine_meters(point, self.coordinates[node_id]))

    def route(self, start: tuple[float, float], destination: tuple[float, float], penalty_edges: Iterable[tuple[int, int]] = ()) -> list[int]:
        start_node = self.nearest_node(start)
        destination_node = self.nearest_node(destination)
        penalties = set(penalty_edges)
        distances = {start_node: 0.0}
        previous: dict[int, int] = {}
        queue = [(0.0, start_node)]

        while queue:
            distance, node = heapq.heappop(queue)
            if node == destination_node:
                break
            if distance != distances.get(node):
                continue
            for neighbor, edge_distance in self.edges.get(node, {}).items():
                weight = edge_distance * (2.8 if (node, neighbor) in penalties else 1.0)
                candidate = distance + weight
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    previous[neighbor] = node
                    heapq.heappush(queue, (candidate, neighbor))

        if destination_node not in distances:
            return []
        path = [destination_node]
        while path[-1] != start_node:
            path.append(previous[path[-1]])
        return list(reversed(path))

    def route_geometry(self, path: list[int]) -> tuple[list[list[float]], float]:
        geometry = [[self.coordinates[node][1], self.coordinates[node][0]] for node in path]
        distance = sum(haversine_meters(self.coordinates[first], self.coordinates[second]) for first, second in zip(path, path[1:]))
        return geometry, distance


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