"""On-demand walking-graph tiles (written by build_tiles.py).

Each `datasets/tiles/{col}_{row}.json.gz` holds the directed walking edges that START in that
tile, the coordinates of every node those edges touch, and the ways they belong to:

    {"nodes": [[id, lat, lon], ...],
     "edges": [[from, to, length_m, way_id], ...],
     "ways":  [[way_id, label, named], ...]}

A node's outgoing edges are all in the tile that holds the node, so routing only ever needs
the tile of the node it is expanding. Tiles are loaded when first needed and kept in a small
LRU cache, so the API starts instantly whatever the size of the study area.
"""

from __future__ import annotations

import gzip
import json
import math
import sqlite3
import threading
from collections import OrderedDict
from contextlib import closing
from pathlib import Path

from area import tile_of

TILES_DIR = Path(__file__).parents[1] / "datasets" / "tiles"
WAYS_DB = Path(__file__).parents[1] / "datasets" / "derived" / "ways.db"  # way -> tiles (build_ways.py)
GRID_DEG = 0.001  # ~110 m buckets for nearest-node / nearest-edge lookups inside a tile


class Tile:
    __slots__ = ("adjacency", "ways", "grid")

    def __init__(self, payload: dict) -> None:
        self.adjacency: dict[int, dict[int, tuple[float, int]]] = {}
        for start, end, length, way_id in payload["edges"]:
            self.adjacency.setdefault(start, {})[end] = (length, way_id)
        self.ways: dict[int, tuple[str, bool]] = {way_id: (label, bool(named)) for way_id, label, named in payload["ways"]}
        self.grid: dict[tuple[int, int], list[int]] = {}


class TileStore:
    def __init__(self, directory: Path = TILES_DIR, capacity: int = 96, ways_db: Path = WAYS_DB) -> None:
        self.directory = Path(directory)
        self.ways_db = Path(ways_db)
        self.capacity = capacity
        self.coordinates: dict[int, tuple[float, float]] = {}
        self._tiles: OrderedDict[tuple[int, int], Tile | None] = OrderedDict()
        self._lock = threading.Lock()
        self.loads = 0

    def tile(self, key: tuple[int, int]) -> Tile | None:
        """The tile at (col, row), loading it on first use. None where there is no walking data."""
        with self._lock:
            if key in self._tiles:
                self._tiles.move_to_end(key)
                return self._tiles[key]
        path = self.directory / f"{key[0]}_{key[1]}.json.gz"
        tile = None
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            tile = Tile(payload)
            coordinates = {node: (lat, lon) for node, lat, lon in payload["nodes"]}
            for node in tile.adjacency:
                lat, lon = coordinates[node]
                tile.grid.setdefault((math.floor(lat / GRID_DEG), math.floor(lon / GRID_DEG)), []).append(node)
        with self._lock:
            if tile is not None:
                self.coordinates.update(coordinates)
                self.loads += 1
            self._tiles[key] = tile
            self._tiles.move_to_end(key)
            while len(self._tiles) > self.capacity:
                self._tiles.popitem(last=False)
        return tile

    def home_tile(self, node: int) -> Tile | None:
        lat, lon = self.coordinates[node]
        return self.tile(tile_of(lat, lon))

    def neighbors(self, node: int) -> dict[int, tuple[float, int]]:
        tile = self.home_tile(node)
        return tile.adjacency.get(node, {}) if tile else {}

    def way(self, way_id: int) -> tuple[str, bool] | None:
        for tile in list(self._tiles.values()):
            if tile is not None and way_id in tile.ways:
                return tile.ways[way_id]
        for tile in self.tiles_of_way(way_id):
            if way_id in tile.ways:
                return tile.ways[way_id]
        return None

    def tiles_of_way(self, way_id: int) -> list[Tile]:
        """Every tile with an edge of this way, loading them if needed (a saved rating or covered
        mark can name a street no request has reached yet, e.g. right after a restart)."""
        if not self.ways_db.exists():
            return []
        with closing(sqlite3.connect(f"{self.ways_db.resolve().as_uri()}?mode=ro&immutable=1", uri=True)) as connection:
            keys = connection.execute("SELECT col, row FROM way_tiles WHERE way_id = ?", (way_id,)).fetchall()
        return [tile for tile in map(self.tile, keys) if tile is not None]

    def tiles_around(self, latitude: float, longitude: float, ring: int = 1):
        column, row = tile_of(round(latitude, 7), round(longitude, 7))
        for dc in range(-ring, ring + 1):
            for dr in range(-ring, ring + 1):
                tile = self.tile((column + dc, row + dr))
                if tile is not None:
                    yield tile

    def nodes_near(self, latitude: float, longitude: float, radius_deg: float = 0.004):
        """Routable nodes (with outgoing edges) within about radius_deg of a point."""
        lat_cells = range(math.floor((latitude - radius_deg) / GRID_DEG), math.floor((latitude + radius_deg) / GRID_DEG) + 1)
        lon_cells = range(math.floor((longitude - radius_deg) / GRID_DEG), math.floor((longitude + radius_deg) / GRID_DEG) + 1)
        for tile in self.tiles_around(latitude, longitude):
            for lat_cell in lat_cells:
                for lon_cell in lon_cells:
                    yield from tile.grid.get((lat_cell, lon_cell), ())

    def edges_near(self, latitude: float, longitude: float, radius_deg: float = 0.0015):
        """Directed edges (start, end, length, way) starting near a point."""
        for node in self.nodes_near(latitude, longitude, radius_deg):
            for end, (length, way_id) in self.neighbors(node).items():
                yield node, end, length, way_id

    def loaded_tiles(self) -> list[Tile]:
        return [tile for tile in self._tiles.values() if tile is not None]
