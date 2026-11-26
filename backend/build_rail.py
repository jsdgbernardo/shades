"""Build the train-option station data (PRD D-04): datasets/derived/rail.json.

Run from the repository root with a Python that has pyosmium (build-only dependency):

    py -3.13 backend/build_rail.py [path/to/philippines-latest.osm.pbf]

Only the operating MRT and LRT lines are kept (PRD C-07): LRT Line 1, LRT Line 2 and MRT Line 3.
PNR, the Metro Manila Subway, MRT Line 7 and every other rail route are left out, because lines
are picked by their OSM route_master (ref, network and mode in LINES), not by searching for rail.

Per line (rail.json `lines`):
- id, name, ref, colour (the line's official colour: LRT-1 green, LRT-2 purple, MRT-3 yellow;
  the hex values are the line relations' `colour` tags), length_m
- shape: one ordered [lat, lon] polyline, the track of the line's main route relation (the one
  direction with the most stops; see `pick_routes`), chained from its track ways in member order
  and trimmed to the two terminals. The other direction runs on a parallel track a few metres
  away, so it is not merged point by point; it fills a gap in the main direction if there is one
  and is used to check the shape (`opposite_offset_m` in the report).
- stations in line order: id, name, osm_id, lat, lon (the stop position on the shape),
  position_m (distance along the shape from the first station), in_study_area, entrance_source
  and entrances.

Station entrances: `railway=subway_entrance` / `railway=train_station_entrance` nodes that are
members of the station's stop_area relation, plus any such node within ENTRANCE_RADIUS_M of the
station that belongs to no other stop_area and is nearer to this station than to any other.
With none, the entrance is the station point itself and `entrance_source` is "station".

Transfers (rail.json `transfers`): the hand-checked list in TRANSFERS, resolved against the
station names in the data; the build fails if a name is not found. Each transfer is a step
between two stations; the walk between them is not routed (PRD C-07).

Station names come from the station feature (railway=station) in the stop_area, else the stop
position, else the stop_area, skipping names without letters (one stop position is named "/").
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from area import STUDY_AREA  # noqa: E402
from routing import haversine_meters  # noqa: E402

ROOT = Path(__file__).parents[1]
DEFAULT_INPUT = ROOT / "datasets" / "raw" / "philippines-latest.osm.pbf"
OUTPUT = ROOT / "datasets" / "derived" / "rail.json"

ENTRANCE_RADIUS_M = 150.0
STOP_AREA_ENTRANCE_MAX_M = 400.0  # a stop_area entrance farther than this is a mapping error
ENTRANCE_TAGS = ("subway_entrance", "train_station_entrance")
JOIN_TOLERANCE_M = 30.0  # consecutive track ways must meet within this, or the build fails
MAX_STOP_OFF_TRACK_M = 30.0
MAX_TRANSFER_M = 600.0  # straight line between the two stations of a transfer
COORD_DECIMALS = 6

# `first`: the terminus published line maps start from (the order stations are listed in).
LINES = [
    {"id": "lrt1", "name": "LRT Line 1", "ref": "1", "network": "Manila LRT", "mode": "light_rail", "first": "Fernando Poe Jr."},
    {"id": "lrt2", "name": "LRT Line 2", "ref": "2", "network": "Manila LRT", "mode": "subway", "first": "Recto"},
    {"id": "mrt3", "name": "MRT Line 3", "ref": "3", "network": "Manila MRT", "mode": "light_rail", "first": "North Avenue"},
]
# Official line colours (green, purple, yellow); the hex comes from the OSM `colour` tags when present.
FALLBACK_COLOURS = {"lrt1": "#008000", "lrt2": "#800080", "mrt3": "#FFCC00"}

# Hand-checked interchanges between the three lines (line id, station name), each pair joined by
# a walkway between the two stations.
TRANSFERS = [
    (("lrt1", "EDSA"), ("mrt3", "Taft Avenue")),
    (("lrt1", "Doroteo Jose"), ("lrt2", "Recto")),
    (("lrt2", "Araneta Center - Cubao"), ("mrt3", "Araneta Center - Cubao")),
]


def norm_name(name: str) -> str:
    """Compare names loosely: case, dashes (- – —) and spacing do not matter."""
    return re.sub(r"[\s\-–—]+", " ", name).strip().lower()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def has_letters(name: str | None) -> bool:
    return bool(name) and any(ch.isalpha() for ch in name)


def inside(lat: float, lon: float) -> bool:
    return STUDY_AREA["south"] <= lat <= STUDY_AREA["north"] and STUDY_AREA["west"] <= lon <= STUDY_AREA["east"]


# ---------- geometry (pure; tested through the committed rail.json) ----------

def _xy(origin_lat: float, lat: float, lon: float) -> tuple[float, float]:
    k = 111_320.0
    return lon * k * math.cos(math.radians(origin_lat)), lat * k


def project(polyline: list[tuple[float, float]], point: tuple[float, float]) -> tuple[float, float, tuple[float, float]]:
    """(distance along the polyline in metres, distance off it in metres, the projected point)."""
    best = (math.inf, 0.0, polyline[0])
    along = 0.0
    lat0 = point[0]
    px, py = _xy(lat0, *point)
    for a, b in zip(polyline, polyline[1:]):
        ax, ay = _xy(lat0, *a)
        bx, by = _xy(lat0, *b)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        qx, qy = ax + t * dx, ay + t * dy
        off = math.hypot(px - qx, py - qy)
        seg_len = haversine_meters(a, b)
        if off < best[0]:
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            best = (off, along + t * seg_len, q)
        along += seg_len
    return best[1], best[0], best[2]


def length(polyline) -> float:
    return sum(haversine_meters(a, b) for a, b in zip(polyline, polyline[1:]))


def cut(polyline, start_m: float, end_m: float) -> list[tuple[float, float]]:
    """The part of the polyline between two distances along it."""
    def at(a, b, t):
        t = max(0.0, min(1.0, t))
        return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

    out = []
    along = 0.0
    for a, b in zip(polyline, polyline[1:]):
        seg = haversine_meters(a, b)
        if seg == 0:
            continue
        nxt = along + seg
        if not out and start_m <= nxt:
            out.append(at(a, b, (start_m - along) / seg))
        if out:
            if end_m <= nxt:
                out.append(at(a, b, (end_m - along) / seg))
                break
            out.append(b)
        along = nxt
    dedup = [out[0]]
    for p in out[1:]:
        if haversine_meters(dedup[-1], p) > 0.05:
            dedup.append(p)
    return dedup


def chain_ways(way_ids: list[int], way_nodes: dict, loc: dict):
    """Join ways in relation order into one node list, flipping each as needed.
    Returns (points, joins) where joins lists (way_id, gap_m) for every junction."""
    seqs = [list(way_nodes[w]) for w in way_ids]
    if len(seqs) > 1:  # orient the first way towards the second
        first, second = seqs[0], seqs[1]
        if first[0] in (second[0], second[-1]) and first[-1] not in (second[0], second[-1]):
            first.reverse()
    nodes = list(seqs[0])
    joins = []
    for way_id, seq in zip(way_ids[1:], seqs[1:]):
        tail = nodes[-1]
        if seq[-1] == tail or (seq[0] != tail and haversine_meters(loc[tail], loc[seq[-1]]) < haversine_meters(loc[tail], loc[seq[0]])):
            seq = seq[::-1]
        gap = 0.0 if seq[0] == tail else haversine_meters(loc[tail], loc[seq[0]])
        joins.append((way_id, gap))
        nodes.extend(seq[1:] if seq[0] == tail else seq)
    return [loc[n] for n in nodes], joins


# ---------- OSM reading ----------

def read_osm(path: Path):
    import osmium  # build-only dependency

    relations = {}
    for r in osmium.FileProcessor(str(path), osmium.osm.RELATION):
        tags = dict(r.tags)
        if tags.get("type") in ("route", "route_master") or tags.get("public_transport") == "stop_area":
            relations[r.id] = {"tags": tags, "members": [(m.type, m.ref, m.role) for m in r.members]}

    # Railway-tagged nodes (stations, stop positions, entrances) anywhere near the area.
    rail_nodes = {}
    for n in osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(osmium.filter.KeyFilter("railway", "public_transport")):
        lat, lon = n.location.lat, n.location.lon
        if STUDY_AREA["south"] - 0.05 <= lat <= STUDY_AREA["north"] + 0.05 and STUDY_AREA["west"] - 0.05 <= lon <= STUDY_AREA["east"] + 0.05:
            rail_nodes[n.id] = {"lat": lat, "lon": lon, "tags": dict(n.tags)}
    return relations, rail_nodes


def read_ways(path: Path, way_ids: set[int]):
    import osmium

    ways = {}
    for w in osmium.FileProcessor(str(path), osmium.osm.WAY).with_filter(osmium.filter.IdFilter(way_ids)):
        ways[w.id] = {"nodes": [n.ref for n in w.nodes], "tags": dict(w.tags)}
    node_ids = {n for w in ways.values() for n in w["nodes"]}
    loc = {}
    for n in osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(osmium.filter.IdFilter(node_ids)):
        loc[n.id] = (n.location.lat, n.location.lon)
    return ways, loc


def stops_of(relation) -> list[int]:
    return [ref for kind, ref, role in relation["members"] if kind == "n" and role.startswith("stop")]


def track_ways(relation) -> list[int]:
    return [ref for kind, ref, role in relation["members"] if kind == "w" and role in ("", "forward", "backward")]


def pick_routes(line, relations):
    """The line's route_master and its two direction relations: the active route with the most
    stops (main), and the active route running the other way with the most stops."""
    masters = [
        rid for rid, r in relations.items()
        if r["tags"].get("type") == "route_master" and r["tags"].get("ref") == line["ref"]
        and r["tags"].get("route_master") == line["mode"] and r["tags"].get("network") == line["network"]
    ]
    if len(masters) != 1:
        raise SystemExit(f"{line['id']}: expected one route_master, found {masters}")
    master = relations[masters[0]]
    routes = [ref for kind, ref, _ in master["members"] if kind == "r" and ref in relations
              and relations[ref]["tags"].get("route") == line["mode"]]  # disused routes have no `route`
    if not routes:
        raise SystemExit(f"{line['id']}: no active route relations")
    routes.sort(key=lambda rid: (-len(stops_of(relations[rid])), rid))
    main = routes[0]
    main_tags = relations[main]["tags"]
    opposite = [rid for rid in routes[1:] if relations[rid]["tags"].get("from") == main_tags.get("to")]
    return masters[0], main, (opposite[0] if opposite else None)


def stop_area_index(relations):
    """node id → stop_area relation id, for every node member of a stop_area."""
    index = {}
    for rid, r in relations.items():
        if r["tags"].get("public_transport") != "stop_area":
            continue
        for kind, ref, _ in r["members"]:
            if kind == "n":
                index.setdefault(ref, rid)
    return index


# ---------- build ----------

def build(path: Path) -> dict:
    t0 = time.time()
    relations, rail_nodes = read_osm(path)
    area_of_node = stop_area_index(relations)

    picked = {line["id"]: pick_routes(line, relations) for line in LINES}
    need_ways = set()
    for master, main, opposite in picked.values():
        need_ways.update(track_ways(relations[main]))
        if opposite:
            need_ways.update(track_ways(relations[opposite]))
    station_way_members = {}  # stop_area id → way ids (for railway=station areas)
    for rid, r in relations.items():
        if r["tags"].get("public_transport") == "stop_area":
            station_way_members[rid] = [ref for kind, ref, _ in r["members"] if kind == "w"]
            need_ways.update(station_way_members[rid])
    ways, loc = read_ways(path, need_ways)
    for nid, n in rail_nodes.items():
        loc.setdefault(nid, (n["lat"], n["lon"]))

    report = {"lines": {}, "entrances_nearby": [], "warnings": []}
    lines_out = []
    our_areas = {}  # stop_area id → station id
    all_stations = []

    for line in LINES:
        master, main, opposite = picked[line["id"]]
        rel = relations[main]
        colour = rel["tags"].get("colour") or relations[master]["tags"].get("colour") or FALLBACK_COLOURS[line["id"]]

        main_ways = [w for w in track_ways(rel) if w in ways]
        points, joins = chain_ways(main_ways, {w: ways[w]["nodes"] for w in main_ways}, loc)
        gaps = [(w, g) for w, g in joins if g > 0.5]
        if any(g > JOIN_TOLERANCE_M for _, g in gaps):
            raise SystemExit(f"{line['id']}: track ways do not join: {gaps}")

        stop_ids = stops_of(rel)
        stations = []
        for stop in stop_ids:
            if stop not in rail_nodes:
                raise SystemExit(f"{line['id']}: stop node {stop} not found")
            stop_node = rail_nodes[stop]
            area_id = area_of_node.get(stop)
            area = relations.get(area_id) if area_id else None
            name, osm_id = None, f"node/{stop}"
            station_point = None
            if area:
                for kind, ref, _ in area["members"]:
                    tags = (rail_nodes.get(ref, {}).get("tags") if kind == "n" else ways.get(ref, {}).get("tags")) or {}
                    if tags.get("railway") == "station" or tags.get("public_transport") == "station":
                        if has_letters(tags.get("name")):
                            name, osm_id = tags["name"], f"{'node' if kind == 'n' else 'way'}/{ref}"
                            break
                if not name:
                    osm_id = f"relation/{area_id}"
            if not name and has_letters(stop_node["tags"].get("name")):
                name = stop_node["tags"]["name"]
            if not name and area and has_letters(area["tags"].get("name")):
                name = area["tags"]["name"]
            if not name:
                raise SystemExit(f"{line['id']}: no usable name for stop {stop}")
            along, off, on_track = project(points, (stop_node["lat"], stop_node["lon"]))
            if off > MAX_STOP_OFF_TRACK_M:
                raise SystemExit(f"{line['id']}: stop {name} is {off:.0f} m off the track")
            station_point = on_track
            stations.append({
                "id": f"{line['id']}:{slug(name)}", "name": name, "osm_id": osm_id,
                "lat": station_point[0], "lon": station_point[1], "_along": along,
                "_area": area_id, "_stop": stop,
            })
            if area_id:
                our_areas[area_id] = stations[-1]["id"]

        # List stations from the terminus a published line map starts at (`first`).
        if norm_name(stations[-1]["name"]) == norm_name(line["first"]):
            total = length(points)
            points = points[::-1]
            stations.reverse()
            for s in stations:
                s["_along"] = total - s["_along"]
        if norm_name(stations[0]["name"]) != norm_name(line["first"]):
            raise SystemExit(f"{line['id']}: terminus {line['first']!r} not found, line starts at {stations[0]['name']!r}")

        # Trim the shape to the terminals and measure positions along it.
        start_m, end_m = stations[0]["_along"], stations[-1]["_along"]
        if not end_m > start_m:
            raise SystemExit(f"{line['id']}: stations are not in track order")
        shape = cut(points, start_m, end_m)
        for s in stations:
            s["position_m"] = round(s["_along"] - start_m, 1)
        positions = [s["position_m"] for s in stations]
        if positions != sorted(positions) or len(set(positions)) != len(positions):
            raise SystemExit(f"{line['id']}: positions do not increase: {positions}")

        # Compare with the other direction's track.
        opposite_offset = None
        if opposite:
            o_ways = [w for w in track_ways(relations[opposite]) if w in ways]
            o_points, _ = chain_ways(o_ways, {w: ways[w]["nodes"] for w in o_ways}, loc)
            offsets = []
            for p in o_points:
                along, off, _ = project(shape, p)
                if 1.0 < along < length(shape) - 1.0:
                    offsets.append(off)
            opposite_offset = round(max(offsets), 1) if offsets else None

        report["lines"][line["id"]] = {
            "main_relation": main, "opposite_relation": opposite, "track_ways": len(main_ways),
            "joins_with_gap": [(w, round(g, 1)) for w, g in gaps], "opposite_offset_m": opposite_offset,
        }
        lines_out.append({
            "id": line["id"], "name": line["name"], "ref": line["ref"], "colour": colour,
            "osm_route": f"relation/{main}", "length_m": round(length(shape), 1),
            "shape": [[round(a, COORD_DECIMALS), round(b, COORD_DECIMALS)] for a, b in shape],
            "stations": stations,
        })
        all_stations.extend(stations)

    # Entrances.
    entrance_nodes = {nid: n for nid, n in rail_nodes.items() if n["tags"].get("railway") in ENTRANCE_TAGS}
    by_id = {s["id"]: s for s in all_stations}
    assigned = {s["id"]: [] for s in all_stations}
    for s in all_stations:
        area = relations.get(s["_area"]) if s["_area"] else None
        if not area:
            continue
        for kind, ref, _ in area["members"]:
            if kind == "n" and ref in entrance_nodes:
                e = entrance_nodes[ref]
                d = haversine_meters((s["lat"], s["lon"]), (e["lat"], e["lon"]))
                if d > STOP_AREA_ENTRANCE_MAX_M:
                    report["warnings"].append(f"{s['id']}: stop_area entrance node/{ref} is {d:.0f} m away, skipped")
                    continue
                assigned[s["id"]].append((ref, e, "stop_area", d))
    taken = {ref for lst in assigned.values() for ref, *_ in lst}
    for ref, e in entrance_nodes.items():
        if ref in taken:
            continue
        other_area = area_of_node.get(ref)
        if other_area and other_area not in our_areas:
            continue  # belongs to another station (PNR, subway, ...)
        dists = sorted((haversine_meters((s["lat"], s["lon"]), (e["lat"], e["lon"])), s["id"]) for s in all_stations)
        d, sid = dists[0]
        if other_area:
            sid = our_areas[other_area]
            d = haversine_meters((by_id[sid]["lat"], by_id[sid]["lon"]), (e["lat"], e["lon"]))
        if d <= ENTRANCE_RADIUS_M:
            assigned[sid].append((ref, e, "nearby", d))
            report["entrances_nearby"].append(f"{sid}: node/{ref} {e['tags'].get('name') or ''} {d:.0f} m".rstrip())

    for s in all_stations:
        found = sorted(assigned[s["id"]], key=lambda item: item[0])
        if found:
            s["entrance_source"] = "osm"
            s["entrances"] = [
                {"osm_id": f"node/{ref}", "lat": round(e["lat"], 7), "lon": round(e["lon"], 7),
                 **({"name": e["tags"]["name"]} if e["tags"].get("name") else {}), "source": how}
                for ref, e, how, _ in found
            ]
        else:
            s["entrance_source"] = "station"
            s["entrances"] = [{"lat": round(s["lat"], 7), "lon": round(s["lon"], 7), "source": "station"}]
        s["in_study_area"] = inside(s["lat"], s["lon"])
        s["lat"], s["lon"] = round(s["lat"], 7), round(s["lon"], 7)
        for key in ("_along", "_area", "_stop"):
            s.pop(key)

    # Transfers.
    transfers = []
    for (line_a, name_a), (line_b, name_b) in TRANSFERS:
        ends = []
        for line_id, name in ((line_a, name_a), (line_b, name_b)):
            match = [s for s in all_stations if s["id"].startswith(line_id + ":") and norm_name(s["name"]) == norm_name(name)]
            if len(match) != 1:
                raise SystemExit(f"transfer: station {name!r} on {line_id} not found (matches: {len(match)})")
            ends.append(match[0])
        distance = haversine_meters((ends[0]["lat"], ends[0]["lon"]), (ends[1]["lat"], ends[1]["lon"]))
        if distance > MAX_TRANSFER_M:
            raise SystemExit(f"transfer {name_a} – {name_b}: stations are {distance:.0f} m apart")
        transfers.append({"from": ends[0]["id"], "to": ends[1]["id"], "straight_line_m": round(distance)})

    result = {
        "source": "OpenStreetMap via Geofabrik (philippines-latest.osm.pbf), © OpenStreetMap contributors, ODbL",
        "source_modified": time.strftime("%Y-%m-%d", time.gmtime(path.stat().st_mtime)),
        "built": time.strftime("%Y-%m-%d"),
        "notes": "Operating MRT and LRT lines only (PRD C-07). Shapes are [lat, lon]; position_m is "
                 "the distance along the shape from the line's first station. entrance_source "
                 "'station' means no entrance is mapped and the station point stands in.",
        "lines": lines_out,
        "transfers": transfers,
    }
    report["seconds"] = round(time.time() - t0, 1)
    return result, report


def print_report(result: dict, report: dict, size: int) -> None:
    print("\n## Rail build report\n")
    print("| Line | Stations | With mapped entrances | Station-point fallback | Entrances | Length | Main relation | Other direction offset |")
    print("|---|---|---|---|---|---|---|---|")
    for line in result["lines"]:
        st = line["stations"]
        mapped = sum(s["entrance_source"] == "osm" for s in st)
        entrances = sum(len(s["entrances"]) for s in st if s["entrance_source"] == "osm")
        info = report["lines"][line["id"]]
        print(f"| {line['name']} | {len(st)} | {mapped} | {len(st) - mapped} | {entrances} | {line['length_m'] / 1000:.2f} km "
              f"| {line['osm_route']} | {info['opposite_offset_m']} m |")
    for line in result["lines"]:
        print(f"\n**{line['name']}** ({line['colour']}): " + " → ".join(
            f"{s['name']}{'' if s['entrance_source'] == 'osm' else '*'}{'' if s['in_study_area'] else ' (outside area)'}"
            for s in line["stations"]))
        gaps = report["lines"][line["id"]]["joins_with_gap"]
        if gaps:
            print(f"  joins with a gap: {gaps}")
    print("\n\\* station-point fallback (no entrance mapped)\n")
    print("Transfers: " + "; ".join(f"{t['from']} ↔ {t['to']} ({t['straight_line_m']} m)" for t in result["transfers"]))
    if report["entrances_nearby"]:
        print("\nEntrances matched by distance (not in the stop_area):")
        for item in report["entrances_nearby"]:
            print(f"- {item}")
    for w in report["warnings"]:
        print(f"- warning: {w}")
    print(f"\nFile: {OUTPUT.relative_to(ROOT).as_posix()}, {size / 1024:.1f} KB; build {report['seconds']} s")


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    result, report = build(source)
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    OUTPUT.write_text(text + "\n", encoding="utf-8")
    print_report(result, report, OUTPUT.stat().st_size)


if __name__ == "__main__":
    main()
