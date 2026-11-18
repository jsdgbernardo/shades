"""One-time data build: OpenStreetMap → routing tiles, place index and unknown-height cells.

Run from the repository root with a Python that has pyosmium (build-only dependency):

    py -3.13 -m pip install --user osmium
    py -3.13 backend/build_tiles.py [path/to/philippines-latest.osm.pbf]

Input (not committed): datasets/raw/philippines-latest.osm.pbf from
https://download.geofabrik.de/asia/philippines-latest.osm.pbf (© OpenStreetMap contributors, ODbL).

Outputs (committed, read by the stdlib-only API):
- datasets/tiles/{col}_{row}.json.gz  walking graph per tile (see tiles.py for the format)
- datasets/derived/places.db          SQLite FTS5 index of named places
- datasets/derived/unknown-height-cells.bin  raster cells of buildings without height (PRD D-01)
- datasets/derived/build-info.json    counts and source details
"""

from __future__ import annotations

import gzip
import json
import math
import sqlite3
import sys
import time
from array import array
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from area import COORD_DECIMALS, STUDY_AREA, tile_of  # noqa: E402
from osm import FootprintIndex, is_enclosed_ground_building  # noqa: E402
from places import kind_of  # noqa: E402
from routing import WALKABLE_HIGHWAYS, haversine_meters  # noqa: E402
from shade import HeightRaster  # noqa: E402

ROOT = Path(__file__).parents[1]
DEFAULT_INPUT = ROOT / "datasets" / "raw" / "philippines-latest.osm.pbf"
TILES_DIR = ROOT / "datasets" / "tiles"
DERIVED_DIR = ROOT / "datasets" / "derived"
MIN_COMPONENT_NODES = 200  # walking fragments smaller than this are dropped (see drop_small_components)
PLACE_DEDUPE_DEG = 0.002  # the same name within ~200 m is one place (a building and the shop inside it)
BUILDING_TAGS = ("building", "layer", "min_level", "building:min_level")


def inside(latitude: float, longitude: float) -> bool:
    return STUDY_AREA["south"] <= latitude <= STUDY_AREA["north"] and STUDY_AREA["west"] <= longitude <= STUDY_AREA["east"]


def walkable(tags) -> bool:
    return (
        tags.get("highway") in WALKABLE_HIGHWAYS
        and tags.get("access") not in {"no", "private"}
        and tags.get("foot") != "no"
        and tags.get("indoor") != "yes"
    )


def collect(path: Path):
    """Single streaming pass with node locations. Keeps only what touches the study area."""
    import osmium  # build-only dependency; imported here so tests can use the pure helpers below


    ways = []        # (way_id, [(node_id, lat, lon)], name, oneway_foot, passage, highway)
    buildings = []   # (ring [(lat, lon)], tags subset)
    places = []      # (identifier, name, tags, lat, lon)
    margin = 0.05  # a way whose first node is this close to the box may still cross into it
    processor = osmium.FileProcessor(str(path)).with_locations().with_filter(osmium.filter.KeyFilter("highway", "building", "name"))
    for item in processor:
        if item.is_node():
            if "name" in item.tags and item.location.valid() and inside(item.location.lat, item.location.lon):
                places.append((f"n{item.id}", item.tags["name"], dict(item.tags), item.location.lat, item.location.lon))
            continue
        if not item.is_way() or len(item.nodes) < 2:
            continue
        # Cheap reject on the first node before reading the whole way (most of the country is outside).
        first = item.nodes[0].location
        if not first.valid() or not (STUDY_AREA["south"] - margin <= first.lat <= STUDY_AREA["north"] + margin
                                     and STUDY_AREA["west"] - margin <= first.lon <= STUDY_AREA["east"] + margin):
            continue
        points = [(node.ref, node.location.lat, node.location.lon) for node in item.nodes if node.location.valid()]
        if len(points) < 2 or not any(inside(lat, lon) for _, lat, lon in points):
            continue
        tags = item.tags
        if walkable(tags):
            ways.append((
                item.id, points, tags.get("name"),
                tags.get("oneway:foot") in {"yes", "1", "true", "-1"}, tags.get("oneway:foot") == "-1",
                tags.get("tunnel") == "building_passage", tags.get("highway"),
            ))
        if "building" in tags and len(points) >= 4 and points[0][0] == points[-1][0]:
            buildings.append(([(lat, lon) for _, lat, lon in points], {key: tags[key] for key in BUILDING_TAGS if key in tags}))
        if tags.get("name"):
            if "highway" in tags:
                _, lat, lon = points[len(points) // 2]
            else:
                lat = sum(p[1] for p in points) / len(points)
                lon = sum(p[2] for p in points) / len(points)
            if inside(lat, lon):
                places.append((f"w{item.id}", tags["name"], dict(tags), lat, lon))
    return ways, buildings, places


def build_graph(ways, enclosed: FootprintIndex):
    """Directed walking edges grouped by the tile of their start node."""
    tiles = defaultdict(lambda: {"nodes": {}, "edges": [], "ways": {}})
    excluded = 0
    edge_count = 0
    for way_id, points, name, oneway, reverse, passage, highway in ways:
        label = name or (highway or "street").replace("_", " ").capitalize()
        for (a, lat_a, lon_a), (b, lat_b, lon_b) in zip(points, points[1:]):
            if not (inside(lat_a, lon_a) or inside(lat_b, lon_b)):
                continue
            if not passage and any(enclosed.contains(lat_a + (lat_b - lat_a) * f, lon_a + (lon_b - lon_a) * f) for f in (0.25, 0.5, 0.75)):
                excluded += 1
                continue
            pa = (round(lat_a, COORD_DECIMALS), round(lon_a, COORD_DECIMALS))
            pb = (round(lat_b, COORD_DECIMALS), round(lon_b, COORD_DECIMALS))
            length = round(haversine_meters(pa, pb), 2)
            directions = [(a, pa, b, pb)] if oneway else [(a, pa, b, pb), (b, pb, a, pa)]
            if reverse:
                directions = [(b, pb, a, pa)]
            for start, p_start, end, p_end in directions:
                tile = tiles[tile_of(*p_start)]
                tile["nodes"][start] = p_start
                tile["nodes"][end] = p_end
                tile["edges"].append((start, end, length, way_id))
                tile["ways"][way_id] = (label, bool(name))
                edge_count += 1
    return tiles, excluded, edge_count


def drop_small_components(tiles, min_nodes: int = MIN_COMPONENT_NODES) -> int:
    """Remove walking fragments cut off from the main network (paths inside malls, gated
    areas with private access roads). Otherwise a point can snap onto an island and routing
    searches the whole city before failing. Returns the number of edges removed."""
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for tile in tiles.values():
        for start, end, _, _ in tile["edges"]:
            root_a, root_b = find(start), find(end)
            if root_a != root_b:
                parent[root_a] = root_b
    sizes: dict[int, int] = defaultdict(int)
    for node in list(parent):
        sizes[find(node)] += 1
    removed = 0
    for tile in tiles.values():
        kept = [edge for edge in tile["edges"] if sizes[find(edge[0])] >= min_nodes]
        removed += len(tile["edges"]) - len(kept)
        tile["edges"] = kept
        used = {node for edge in kept for node in edge[:2]}
        tile["nodes"] = {node: point for node, point in tile["nodes"].items() if node in used}
        used_ways = {edge[3] for edge in kept}
        tile["ways"] = {way: info for way, info in tile["ways"].items() if way in used_ways}
    return removed


def write_tiles(tiles) -> int:
    TILES_DIR.mkdir(parents=True, exist_ok=True)
    for old in TILES_DIR.glob("*.json.gz"):
        old.unlink()
    total = 0
    for (column, row), tile in tiles.items():
        # De-duplicate parallel edges between the same nodes, keeping the shortest (as before).
        best = {}
        for start, end, length, way_id in tile["edges"]:
            if (start, end) not in best or length < best[(start, end)][2]:
                best[(start, end)] = (start, end, length, way_id)
        payload = {
            "nodes": [[node, lat, lon] for node, (lat, lon) in tile["nodes"].items()],
            "edges": [list(edge) for edge in best.values()],
            "ways": [[way_id, label, int(named)] for way_id, (label, named) in tile["ways"].items()],
        }
        path = TILES_DIR / f"{column}_{row}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
            json.dump(payload, handle, separators=(",", ":"))
        total += path.stat().st_size
    return total


def write_places(places) -> int:
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    path = DERIVED_DIR / "places.db"
    path.unlink(missing_ok=True)
    seen = set()
    rows = []
    for identifier, name, tags, lat, lon in places:
        key = (name.casefold(), round(lat / PLACE_DEDUPE_DEG), round(lon / PLACE_DEDUPE_DEG))
        if key in seen:
            continue
        seen.add(key)
        rows.append((name, kind_of(tags).lower(), identifier, round(lat, 6), round(lon, 6)))
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE VIRTUAL TABLE places USING fts5(name, kind UNINDEXED, id UNINDEXED, lat UNINDEXED, lon UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
        connection.executemany("INSERT INTO places VALUES (?, ?, ?, ?, ?)", rows)
        connection.execute("INSERT INTO places(places) VALUES ('optimize')")
    connection.execute("VACUUM")
    connection.close()
    return len(rows)


def write_unknown_cells(buildings) -> dict:
    """Raster cells of buildings the height raster reports as 0 m (PRD D-01), for the API to mark unknown."""
    raster = HeightRaster.from_file()
    before = array("f", raster.values)
    west, north = raster.origin_lon, raster.origin_lat
    east, south = west + raster.width * raster.pixel_size, north - raster.height * raster.pixel_size
    footprints = [ring for ring, _ in buildings if all(south <= lat <= north and west <= lon <= east for lat, lon in ring[:1])]
    report = raster.mark_unknown_footprints(footprints)
    cells = array("I", (index for index, (old, new) in enumerate(zip(before, raster.values)) if not math.isnan(old) and math.isnan(new)))
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    with open(DERIVED_DIR / "unknown-height-cells.bin", "wb") as handle:
        cells.tofile(handle)
    return {**report, "cells": len(cells)}


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    started = time.time()
    print(f"Reading {source} ...", flush=True)
    ways, buildings, places = collect(source)
    print(f"  {len(ways)} walkable ways, {len(buildings)} buildings, {len(places)} named features ({time.time() - started:.0f} s)", flush=True)

    enclosed = FootprintIndex([ring for ring, tags in buildings if is_enclosed_ground_building(tags)])
    tiles, excluded, edge_count = build_graph(ways, enclosed)
    del enclosed
    fragments = drop_small_components(tiles)
    tiles = {key: tile for key, tile in tiles.items() if tile["edges"]}
    edge_count -= fragments
    size = write_tiles(tiles)
    print(f"  {len(tiles)} tiles, {edge_count} directed edges, {excluded} indoor edges dropped, {fragments} fragment edges dropped, {size / 1e6:.1f} MB ({time.time() - started:.0f} s)", flush=True)

    place_count = write_places(places)
    print(f"  {place_count} places indexed ({time.time() - started:.0f} s)", flush=True)

    heights = write_unknown_cells(buildings)
    print(f"  heights: {heights} ({time.time() - started:.0f} s)", flush=True)

    info = {
        "source": "OpenStreetMap via Geofabrik (philippines-latest.osm.pbf), © OpenStreetMap contributors, ODbL",
        "source_modified": time.strftime("%Y-%m-%d", time.gmtime(source.stat().st_mtime)),
        "built": time.strftime("%Y-%m-%d"),
        "study_area": STUDY_AREA,
        "tiles": len(tiles),
        "directed_edges": edge_count,
        "indoor_edges_excluded": excluded,
        "fragment_edges_excluded": fragments,
        "places": place_count,
        "building_heights": {"buildings": heights["buildings"], "with_height": heights["with_height"], "without_height": heights["without_height"]},
        "unknown_height_cells": heights["cells"],
    }
    (DERIVED_DIR / "build-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"Done in {time.time() - started:.0f} s", flush=True)


if __name__ == "__main__":
    main()
