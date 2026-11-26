"""Build the place-search index (datasets/derived/places.db) with a short address per place.

Run from the repository root with a Python that has pyosmium (build-only dependency):

    py -3.13 backend/build_places.py [path/to/philippines-latest.osm.pbf]

build_tiles.py calls `build()` after writing the tiles; run this file on its own to refresh the
place index without rebuilding the tiles. It reads the committed walking tiles for the nearest
street, so the tiles must exist first.

Address per place, enough to tell two branches of a chain apart:
- street: `addr:housenumber` + `addr:street` when tagged; otherwise the nearest named walkable
  street within NEAR_STREET_M. Places that are themselves streets get no street part.
- city: the name of the containing admin_level=6 boundary (cities and municipalities), so every
  place in one city is labelled the same way; `addr:city` only when no boundary contains it.
Formatted "Street, City", or just one of the two, or "" when neither is known.
"""

from __future__ import annotations

import math
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from area import STUDY_AREA, tile_of  # noqa: E402
from places import kind_of  # noqa: E402
from routing import WalkingGraph  # noqa: E402
from tiles import TileStore  # noqa: E402

ROOT = Path(__file__).parents[1]
DEFAULT_INPUT = ROOT / "datasets" / "raw" / "philippines-latest.osm.pbf"
DERIVED_DIR = ROOT / "datasets" / "derived"
PLACE_DEDUPE_DEG = 0.002  # the same name within ~200 m is one place (a building and the shop inside it)
NEAR_STREET_M = 150.0
BAND_DEG = 0.002  # latitude strips for the point-in-boundary test


def inside(latitude: float, longitude: float) -> bool:
    return STUDY_AREA["south"] <= latitude <= STUDY_AREA["north"] and STUDY_AREA["west"] <= longitude <= STUDY_AREA["east"]


def place_point(identifier: str, tags, points) -> tuple | None:
    """A named feature as a search place (identifier, name, tags, lat, lon), or None if it is
    unnamed or outside the study area. `points` are (lat, lon) pairs: one for a node; for a way,
    a street is placed at its middle node and anything else at the mean of its nodes."""
    name = tags.get("name")
    if not name or not points:
        return None
    if len(points) == 1 or "highway" in tags:
        lat, lon = points[len(points) // 2]
    else:
        lat = sum(p[0] for p in points) / len(points)
        lon = sum(p[1] for p in points) / len(points)
    if not inside(lat, lon):
        return None
    return (identifier, name, dict(tags), lat, lon)


def collect(path: Path):
    """One streaming pass: named places and the admin_level=6 boundaries around the study area."""
    import osmium  # build-only dependency

    places = []
    boundaries = []  # (name, rings [[(lat, lon), ...]], bbox)
    margin = 0.05
    processor = (osmium.FileProcessor(str(path))
                 .with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
                 .with_filter(osmium.filter.KeyFilter("name")))
    for item in processor:
        if item.is_node():
            if item.location.valid():
                place = place_point(f"n{item.id}", item.tags, [(item.location.lat, item.location.lon)])
                if place:
                    places.append(place)
        elif item.is_way():
            if len(item.nodes) < 2:
                continue
            first = item.nodes[0].location
            if not first.valid() or not (STUDY_AREA["south"] - margin <= first.lat <= STUDY_AREA["north"] + margin
                                         and STUDY_AREA["west"] - margin <= first.lon <= STUDY_AREA["east"] + margin):
                continue
            points = [(node.location.lat, node.location.lon) for node in item.nodes if node.location.valid()]
            if len(points) < 2 or not any(inside(lat, lon) for lat, lon in points):
                continue
            place = place_point(f"w{item.id}", item.tags, points)
            if place:
                places.append(place)
        elif item.is_area():
            tags = item.tags
            if item.from_way() or tags.get("boundary") != "administrative" or tags.get("admin_level") != "6":
                continue
            rings = []
            for outer in item.outer_rings():
                rings.append([(node.lat, node.lon) for node in outer])
                rings.extend([(node.lat, node.lon) for node in inner] for inner in item.inner_rings(outer))
            all_points = [p for ring in rings for p in ring]
            if not all_points:
                continue
            bbox = (min(p[0] for p in all_points), max(p[0] for p in all_points),
                    min(p[1] for p in all_points), max(p[1] for p in all_points))
            if bbox[1] < STUDY_AREA["south"] or bbox[0] > STUDY_AREA["north"] or bbox[3] < STUDY_AREA["west"] or bbox[2] > STUDY_AREA["east"]:
                continue
            boundaries.append((tags["name"], rings, bbox))
    return places, boundaries


class BoundaryIndex:
    """Even-odd point-in-polygon over the boundaries, with ring edges bucketed into latitude
    strips so each test only looks at the few edges that cross the point's strip."""

    def __init__(self, boundaries) -> None:
        self.entries = []
        for name, rings, bbox in boundaries:
            bands: dict[int, list] = {}
            for ring in rings:
                for (y1, x1), (y2, x2) in zip(ring, ring[1:] + ring[:1]):
                    if y1 == y2:
                        continue
                    for band in range(math.floor(min(y1, y2) / BAND_DEG), math.floor(max(y1, y2) / BAND_DEG) + 1):
                        bands.setdefault(band, []).append((y1, x1, y2, x2))
            size = (bbox[1] - bbox[0]) * (bbox[3] - bbox[2])
            self.entries.append((size, name, bbox, bands))
        self.entries.sort(key=lambda entry: entry[0])  # smallest first, if boundaries overlap

    def city_at(self, lat: float, lon: float) -> str | None:
        band = math.floor(lat / BAND_DEG)
        for _, name, (south, north, west, east), bands in self.entries:
            if not (south <= lat <= north and west <= lon <= east):
                continue
            crossings = 0
            for y1, x1, y2, x2 in bands.get(band, ()):
                if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                    crossings += 1
            if crossings % 2:
                return name
        return None


def _segment_distance_m(lat: float, lon: float, a, b) -> float:
    scale = math.cos(math.radians(lat)) * 111_320
    ax, ay = (a[1] - lon) * scale, (a[0] - lat) * 111_320
    bx, by = (b[1] - lon) * scale, (b[0] - lat) * 111_320
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
    return math.hypot(ax + t * dx, ay + t * dy)


def nearest_named_street(graph: WalkingGraph, lat: float, lon: float, max_m: float = NEAR_STREET_M) -> str | None:
    store = graph.store
    best, best_distance = None, max_m
    named: dict[int, bool] = {}
    for start, end, _, way_id in store.edges_near(lat, lon, max_m / 111_320):
        if way_id not in named:
            named[way_id] = graph.is_named(way_id)
        if not named[way_id]:
            continue
        distance = _segment_distance_m(lat, lon, store.coordinates[start], store.coordinates[end])
        if distance < best_distance:
            best, best_distance = way_id, distance
    return graph.way_name(best) if best is not None else None


def address_of(tags, lat: float, lon: float, graph: WalkingGraph, cities: BoundaryIndex) -> tuple[str, str, str]:
    """(address, street source, city source); sources are 'tagged' / 'nearby' / 'boundary' / '' ."""
    street, street_source = "", ""
    if kind_of(tags) != "street":
        if tags.get("addr:street"):
            street = " ".join(part for part in (tags.get("addr:housenumber", "").strip(), tags["addr:street"].strip()) if part)
            street_source = "tagged"
        else:
            nearby = nearest_named_street(graph, lat, lon)
            if nearby:
                street, street_source = nearby, "nearby"
    city, city_source = cities.city_at(lat, lon), "boundary"
    if not city:
        city, city_source = tags.get("addr:city", "").strip(), "tagged"
    if not city:
        city_source = ""
    return ", ".join(part for part in (street, city) if part), street_source, city_source


def write_places(places, boundaries, graph: WalkingGraph | None = None, path: Path | None = None) -> dict:
    """Write places.db and return counts: places, and how each address part was found."""
    graph = graph or WalkingGraph(TileStore(capacity=256))
    cities = BoundaryIndex(boundaries)
    path = path or DERIVED_DIR / "places.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    unique = []
    for place in places:
        _, name, _, lat, lon = place
        key = (name.casefold(), round(lat / PLACE_DEDUPE_DEG), round(lon / PLACE_DEDUPE_DEG))
        if key not in seen:
            seen.add(key)
            unique.append(place)
    # Visit places tile by tile so the tile cache is reused; keep the original row order in the file.
    order = sorted(range(len(unique)), key=lambda index: tile_of(round(unique[index][3], 7), round(unique[index][4], 7)))
    addresses = [""] * len(unique)
    counts = Counter()
    for index in order:
        _, _, tags, lat, lon = unique[index]
        addresses[index], street_source, city_source = address_of(tags, lat, lon, graph, cities)
        counts[f"street_{street_source or 'none'}"] += 1
        counts[f"city_{city_source or 'none'}"] += 1
        if not addresses[index]:
            counts["no_address"] += 1
    rows = [(name, kind_of(tags).lower(), identifier, round(lat, 6), round(lon, 6), address)
            for (identifier, name, tags, lat, lon), address in zip(unique, addresses)]
    temporary = path.with_suffix(".db.tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    with connection:
        connection.execute("CREATE VIRTUAL TABLE places USING fts5(name, kind UNINDEXED, id UNINDEXED, lat UNINDEXED, lon UNINDEXED, address UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
        connection.executemany("INSERT INTO places VALUES (?, ?, ?, ?, ?, ?)", rows)
        connection.execute("INSERT INTO places(places) VALUES ('optimize')")
    connection.execute("VACUUM")
    connection.close()
    temporary.replace(path)
    return {"places": len(rows), "boundaries": len(boundaries), **dict(sorted(counts.items())), "bytes": path.stat().st_size}


def build(source: Path = DEFAULT_INPUT) -> dict:
    started = time.time()
    places, boundaries = collect(source)
    print(f"  {len(places)} named features, {len(boundaries)} admin_level=6 boundaries ({time.time() - started:.0f} s)", flush=True)
    print(f"  boundaries: {', '.join(sorted(name for name, _, _ in boundaries))}", flush=True)
    report = write_places(places, boundaries)
    print(f"  places: {report} ({time.time() - started:.0f} s)", flush=True)
    return report


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT)
