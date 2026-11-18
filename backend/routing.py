"""Walking graph over on-demand tiles (see tiles.py), with A* routing.

Routes are found with A* using the straight-line distance to the destination as the
heuristic. Every edge cost is at least the edge length, so the heuristic never
overestimates and A* returns the lowest-cost path, like Dijkstra, while exploring fewer
edges. Tiles load as the search reaches them, so only the corridor between the two points
is read from disk. That also keeps the shadier search cheap, since each explored edge needs
a shade check.
"""

from __future__ import annotations

import heapq
import math
from typing import Callable

from tiles import TileStore

# Walkable OSM highway types. "trunk" is included because Metro Manila's big avenues (EDSA,
# Commonwealth) are trunk roads with sidewalks; ways tagged foot=no are still excluded.
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
    "trunk",
    "trunk_link",
    "unclassified",
}

CostFunction = Callable[[int, int, float], float]


def edge_key(way_id: int, first: int, second: int) -> str:
    """Stable, direction-free id of one street section (OSM way + its two nodes)."""
    low, high = sorted((first, second))
    return f"{way_id}:{low}-{high}"


class _Coordinates:
    """node -> (lat, lon), loading tiles as needed (nodes are known once a neighbouring tile loaded)."""

    def __init__(self, store: TileStore) -> None:
        self.store = store

    def __getitem__(self, node: int) -> tuple[float, float]:
        return self.store.coordinates[node]

    def __contains__(self, node: int) -> bool:
        return node in self.store.coordinates


class _Edges:
    """node -> {neighbor: length} for outgoing edges."""

    def __init__(self, store: TileStore) -> None:
        self.store = store

    def get(self, node: int, default=None) -> dict[int, float]:
        neighbors = self.store.neighbors(node)
        if not neighbors:
            return default if default is not None else {}
        return {end: length for end, (length, _) in neighbors.items()}

    def __getitem__(self, node: int) -> dict[int, float]:
        return self.get(node)


class _EdgeWays:
    """(a, b) -> way id."""

    def __init__(self, store: TileStore) -> None:
        self.store = store

    def get(self, pair: tuple[int, int], default=None):
        first, second = pair
        if first not in self.store.coordinates:
            return default
        entry = self.store.neighbors(first).get(second)
        return entry[1] if entry else default

    def __getitem__(self, pair: tuple[int, int]) -> int:
        value = self.get(pair)
        if value is None:
            raise KeyError(pair)
        return value


class WalkingGraph:
    def __init__(self, store: TileStore | None = None, excluded_indoor_edges: int = 0) -> None:
        self.store = store or TileStore()
        self.coordinates = _Coordinates(self.store)
        self.edges = _Edges(self.store)
        self.edge_ways = _EdgeWays(self.store)
        self.excluded_indoor_edges = excluded_indoor_edges

    # Street names ------------------------------------------------------------------------
    def way_name(self, way_id: int) -> str:
        info = self.store.way(way_id)
        return info[0] if info else "Street"

    def is_named(self, way_id: int) -> bool:
        info = self.store.way(way_id)
        return bool(info and info[1])

    # Snapping ----------------------------------------------------------------------------
    def nearest_node(self, point: tuple[float, float], max_distance_m: float = 400.0) -> int | None:
        """Closest routable node to a point, or None if no walking path is within max_distance_m."""
        latitude, longitude = point
        radius = max_distance_m / 111_320
        best, best_distance = None, math.inf
        for node in self.store.nodes_near(latitude, longitude, radius):
            distance = haversine_meters(point, self.store.coordinates[node])
            if distance < best_distance:
                best, best_distance = node, distance
        return best if best_distance <= max_distance_m else None

    def nearest_edge(self, point: tuple[float, float], max_distance_m: float = 25.0) -> dict[str, object] | None:
        """Closest street section to a tapped point, within ``max_distance_m``."""
        latitude, longitude = point
        meters_lat = 111_320
        meters_lon = 111_320 * math.cos(math.radians(latitude))
        best: tuple[float, int, int, int] | None = None
        for first, second, _, way_id in self.store.edges_near(latitude, longitude):
            (lat_a, lon_a), (lat_b, lon_b) = self.store.coordinates[first], self.store.coordinates[second]
            ax, ay = (lon_a - longitude) * meters_lon, (lat_a - latitude) * meters_lat
            bx, by = (lon_b - longitude) * meters_lon, (lat_b - latitude) * meters_lat
            dx, dy = bx - ax, by - ay
            length_squared = dx * dx + dy * dy
            t = 0.0 if length_squared == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length_squared))
            distance = math.hypot(ax + t * dx, ay + t * dy)
            if distance <= max_distance_m and (best is None or distance < best[0]):
                best = (distance, first, second, way_id)
        if best is None:
            return None
        _, first, second, way_id = best
        return self.edge_from_key(edge_key(way_id, first, second))

    # Routing -----------------------------------------------------------------------------
    def route(self, start: tuple[float, float], destination: tuple[float, float], cost: CostFunction | None = None) -> list[int]:
        start_node, destination_node = self.nearest_node(start), self.nearest_node(destination)
        if start_node is None or destination_node is None:
            return []
        return self.route_nodes(start_node, destination_node, cost)

    def route_nodes(self, start_node: int, destination_node: int, cost: CostFunction | None = None,
                    use_heuristic: bool = True, max_cost: float | None = None) -> list[int]:
        """Lowest-cost node path. ``cost(a, b, length)`` must return at least ``length``.

        With ``use_heuristic=False`` this is plain Dijkstra (kept for tests). With ``max_cost``,
        the search gives up once no path can cost less, so an unreachable destination fails
        fast instead of exploring (and loading tiles for) the whole city.
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
            estimate, so_far, node = heapq.heappop(queue)
            if max_cost is not None and estimate > max_cost:
                break
            if node in closed:
                continue
            if node == destination_node:
                break
            closed.add(node)
            for neighbor, (length, _) in self.store.neighbors(node).items():
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
        return sum(cost(first, second, self.store.neighbors(first)[second][0]) for first, second in zip(path, path[1:]))

    # Geometry and street info ---------------------------------------------------------------
    def point(self, node: int) -> list[float]:
        latitude, longitude = self.coordinates[node]
        return [longitude, latitude]

    def route_geometry(self, path: list[int]) -> tuple[list[list[float]], float]:
        geometry = [self.point(node) for node in path]
        distance = sum(self.store.neighbors(first)[second][0] for first, second in zip(path, path[1:]))
        return geometry, distance

    def path_edges(self, path: list[int]) -> list[dict[str, object]]:
        """Per-segment street info: edge key, way id and street name."""
        result = []
        for first, second in zip(path, path[1:]):
            length, way_id = self.store.neighbors(first)[second]
            result.append({
                "edge_key": edge_key(way_id, first, second),
                "way_id": way_id,
                "name": self.way_name(way_id),
                # True only for a real OSM street name; unnamed ways get their path type as `name`.
                "named": self.is_named(way_id),
                "length_m": length,
            })
        return result

    def edge_keys(self):
        """Edge keys in the tiles loaded so far (for tests and diagnostics)."""
        for tile in self.store.loaded_tiles():
            for first, ends in tile.adjacency.items():
                for second, (_, way_id) in ends.items():
                    yield edge_key(way_id, first, second)

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
            "name": self.way_name(way_id),
            "geometry": [self.point(first), self.point(second)],
            "length_m": round(haversine_meters(self.coordinates[first], self.coordinates[second]), 1),
        }

    @property
    def way_names(self):
        """Mapping-like view kept for older callers: way id -> label."""
        graph = self

        class _Names:
            def get(self, way_id, default="Street"):
                info = graph.store.way(way_id)
                return info[0] if info else default

            def __contains__(self, way_id):
                return graph.store.way(way_id) is not None

        return _Names()


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
