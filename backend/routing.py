"""Walking graph for the Katipunan prototype, built from the local OpenStreetMap extract.

Routes are found with A* using the straight-line distance to the destination as the
heuristic. Every edge cost is at least the edge length, so the heuristic never
overestimates and A* returns the lowest-cost path, like Dijkstra, while exploring fewer
edges. That matters for the shadier search, where each explored edge needs a shade check.
"""

from __future__ import annotations

import heapq
import math
from typing import Callable

from osm import FootprintIndex, OsmData


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
    "secondary_link",
    "service",
    "steps",
    "tertiary",
    "tertiary_link",
    "unclassified",
}

CostFunction = Callable[[int, int, float], float]


def edge_key(way_id: int, first: int, second: int) -> str:
    """Stable, direction-free id of one street section (OSM way + its two nodes)."""
    low, high = sorted((first, second))
    return f"{way_id}:{low}-{high}"


class WalkingGraph:
    def __init__(
        self,
        coordinates: dict[int, tuple[float, float]],
        edges: dict[int, dict[int, float]],
        edge_ways: dict[tuple[int, int], int] | None = None,
        way_names: dict[int, str] | None = None,
    ) -> None:
        self.coordinates = coordinates
        self.edges = edges
        self.edge_ways = edge_ways or {}
        self.way_names = way_names or {}
        self.named_ways: set[int] = set()
        self.excluded_indoor_edges = 0

    @classmethod
    def from_osm(cls, osm: OsmData, buildings: FootprintIndex | None = None) -> "WalkingGraph":
        """Build the walking graph. With ``buildings``, edges that run through an enclosed
        ground-level building are left out so no route goes indoors (PRD C-01). Mapped
        building passages (tunnel=building_passage) stay, since they are open walkways."""
        coordinates = osm.coordinates
        excluded = 0

        def through_building(first: int, second: int) -> bool:
            if buildings is None:
                return False
            (lat_a, lon_a), (lat_b, lon_b) = coordinates[first], coordinates[second]
            return any(
                buildings.contains(lat_a + (lat_b - lat_a) * fraction, lon_a + (lon_b - lon_a) * fraction)
                for fraction in (0.25, 0.5, 0.75)
            )
        edges: dict[int, dict[int, float]] = {}
        edge_ways: dict[tuple[int, int], int] = {}
        way_names: dict[int, str] = {}
        named_ways: set[int] = set()

        def add(first: int, second: int, distance: float, way_id: int) -> None:
            if distance < edges.setdefault(first, {}).get(second, math.inf):
                edges[first][second] = distance
                edge_ways[(first, second)] = way_id

        for way in osm.ways:
            tags = way.tags
            if tags.get("highway") not in WALKABLE_HIGHWAYS or tags.get("access") in {"no", "private"} or tags.get("foot") == "no":
                continue
            if tags.get("indoor") == "yes":
                continue
            passage = tags.get("tunnel") == "building_passage"
            way_names[way.way_id] = tags.get("name") or tags.get("highway", "street").replace("_", " ").capitalize()
            if tags.get("name"):
                named_ways.add(way.way_id)
            # A vehicle "oneway" tag does not restrict pedestrians; only oneway:foot does.
            oneway = tags.get("oneway:foot") in {"yes", "1", "true", "-1"}
            reverse = tags.get("oneway:foot") == "-1"
            for first, second in zip(way.node_ids, way.node_ids[1:]):
                if first not in coordinates or second not in coordinates:
                    continue
                if not passage and through_building(first, second):
                    excluded += 1
                    continue
                if reverse:
                    first, second = second, first
                distance = haversine_meters(coordinates[first], coordinates[second])
                add(first, second, distance, way.way_id)
                if not oneway:
                    add(second, first, distance, way.way_id)
        graph = cls(coordinates, edges, edge_ways, way_names)
        graph.excluded_indoor_edges = excluded
        graph.named_ways = named_ways
        return graph

    def nearest_node(self, point: tuple[float, float]) -> int:
        return min(self.edges, key=lambda node_id: haversine_meters(point, self.coordinates[node_id]))

    def route(self, start: tuple[float, float], destination: tuple[float, float], cost: CostFunction | None = None) -> list[int]:
        return self.route_nodes(self.nearest_node(start), self.nearest_node(destination), cost)

    def route_nodes(self, start_node: int, destination_node: int, cost: CostFunction | None = None, use_heuristic: bool = True) -> list[int]:
        """Lowest-cost node path. ``cost(a, b, length)`` must return at least ``length``.

        With ``use_heuristic=False`` this is plain Dijkstra (kept for tests).
        """
        cost = cost or (lambda _first, _second, length: length)
        target = self.coordinates[destination_node]

        def heuristic(node: int) -> float:
            return haversine_meters(self.coordinates[node], target) if use_heuristic else 0.0

        best = {start_node: 0.0}
        previous: dict[int, int] = {}
        queue = [(heuristic(start_node), 0.0, start_node)]
        closed: set[int] = set()
        while queue:
            _, so_far, node = heapq.heappop(queue)
            if node in closed:
                continue
            if node == destination_node:
                break
            closed.add(node)
            for neighbor, length in self.edges.get(node, {}).items():
                if neighbor in closed:
                    continue
                candidate = so_far + cost(node, neighbor, length)
                if candidate < best.get(neighbor, math.inf):
                    best[neighbor] = candidate
                    previous[neighbor] = node
                    heapq.heappush(queue, (candidate + heuristic(neighbor), candidate, neighbor))

        if destination_node not in best:
            return []
        path = [destination_node]
        while path[-1] != start_node:
            path.append(previous[path[-1]])
        return list(reversed(path))

    def path_cost(self, path: list[int], cost: CostFunction | None = None) -> float:
        cost = cost or (lambda _first, _second, length: length)
        return sum(cost(first, second, self.edges[first][second]) for first, second in zip(path, path[1:]))

    def point(self, node: int) -> list[float]:
        latitude, longitude = self.coordinates[node]
        return [longitude, latitude]

    def route_geometry(self, path: list[int]) -> tuple[list[list[float]], float]:
        geometry = [self.point(node) for node in path]
        distance = sum(self.edges[first][second] for first, second in zip(path, path[1:]))
        return geometry, distance

    def path_edges(self, path: list[int]) -> list[dict[str, object]]:
        """Per-segment street info: edge key, way id and street name."""
        result = []
        for first, second in zip(path, path[1:]):
            way_id = self.edge_ways.get((first, second), 0)
            result.append({
                "edge_key": edge_key(way_id, first, second),
                "way_id": way_id,
                "name": self.way_names.get(way_id, "Street"),
                # True only for a real OSM street name; unnamed ways get their path type as `name`.
                "named": way_id in self.named_ways,
                "length_m": self.edges[first][second],
            })
        return result


    def edge_keys(self) -> set[str]:
        return {edge_key(way_id, first, second) for (first, second), way_id in self.edge_ways.items()}

    def edge_from_key(self, key: str) -> dict[str, object] | None:
        """Street section for an edge key, or None if the key is not on the walking network."""
        try:
            way_text, nodes = key.split(":")
            first, second = (int(part) for part in nodes.split("-"))
            way_id = int(way_text)
        except ValueError:
            return None
        if self.edge_ways.get((first, second)) != way_id and self.edge_ways.get((second, first)) != way_id:
            return None
        return {
            "edge_key": key,
            "way_id": way_id,
            "name": self.way_names.get(way_id, "Street"),
            "geometry": [self.point(first), self.point(second)],
            "length_m": round(haversine_meters(self.coordinates[first], self.coordinates[second]), 1),
        }

    def nearest_edge(self, point: tuple[float, float], max_distance_m: float = 25.0) -> dict[str, object] | None:
        """Closest street section to a tapped point, within ``max_distance_m``."""
        latitude, longitude = point
        meters_lat = 111_320
        meters_lon = 111_320 * math.cos(math.radians(latitude))
        best: tuple[float, int, int] | None = None
        for (first, second) in self.edge_ways:
            if first > second and (second, first) in self.edge_ways:
                continue
            (lat_a, lon_a), (lat_b, lon_b) = self.coordinates[first], self.coordinates[second]
            ax, ay = (lon_a - longitude) * meters_lon, (lat_a - latitude) * meters_lat
            bx, by = (lon_b - longitude) * meters_lon, (lat_b - latitude) * meters_lat
            dx, dy = bx - ax, by - ay
            length_squared = dx * dx + dy * dy
            t = 0.0 if length_squared == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length_squared))
            distance = math.hypot(ax + t * dx, ay + t * dy)
            if distance <= max_distance_m and (best is None or distance < best[0]):
                best = (distance, first, second)
        if best is None:
            return None
        _, first, second = best
        return self.edge_from_key(edge_key(self.edge_ways[(first, second)], first, second))


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
