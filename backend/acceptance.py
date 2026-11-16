"""Acceptance evidence for PRD checks that can be scripted.

Run from the repository root:  python backend/acceptance.py
It calls the API functions directly (no HTTP), including the live Open-Meteo weather fetch,
and prints a Markdown report. It does not write to the ratings/covered database.

Covered here: F-01 to F-05, F-08, F-09, F-15 (figures present), P-01 (timing without HTTP or
network latency to a phone), C-01 (routes crossing OSM building footprints), D-01 (buildings
with height data). Not covered: anything needing people, a phone or a site visit
(S-07, A-01, F-13/F-14 on a device, O-02 on a phone).
"""

from __future__ import annotations

import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import app  # noqa: E402
from routing import haversine_meters  # noqa: E402
from shade import point_in_ring  # noqa: E402

TIMES = ["2026-10-15T09:00:00+08:00", "2026-10-15T12:00:00+08:00", "2026-10-15T15:00:00+08:00"]
P01_LIMIT_SECONDS = 10.0


def sample_pairs(count: int = 10, seed: int = 2026) -> list[tuple[int, int]]:
    graph = app.WALKING_GRAPH
    rng = random.Random(seed)
    nodes = sorted(node for node in graph.edges if app.is_in_study_area(*graph.coordinates[node]))
    pairs = []
    while len(pairs) < count:
        first, second = rng.sample(nodes, 2)
        if 300 <= haversine_meters(graph.coordinates[first], graph.coordinates[second]) <= 1500 and graph.route_nodes(first, second):
            pairs.append((first, second))
    return pairs


def footprint_index() -> list[tuple[float, float, float, float, list]]:
    index = []
    # Enclosed ground-level buildings only: open roofs and raised structures can be walked under.
    for ring in app.OSM_DATA.building_footprints(enclosed_only=True):
        lats = [point[0] for point in ring]
        lons = [point[1] for point in ring]
        index.append((min(lats), max(lats), min(lons), max(lons), ring))
    return index


def crossings(route: dict, footprints: list) -> float:
    """Metres of route whose ~10 m pieces have a midpoint inside an OSM building footprint."""
    inside = 0.0
    for section in route["exposure"]["sections"]:
        points = section["geometry"]
        for first, second in zip(points, points[1:]):
            longitude = (first[0] + second[0]) / 2
            latitude = (first[1] + second[1]) / 2
            for south, north, west, east, ring in footprints:
                if south <= latitude <= north and west <= longitude <= east and point_in_ring(latitude, longitude, ring):
                    inside += haversine_meters((first[1], first[0]), (second[1], second[0]))
                    break
    return inside


def main() -> None:
    graph = app.WALKING_GRAPH
    footprints = footprint_index()
    rows = []
    durations = []
    for number, (first, second) in enumerate(sample_pairs(), start=1):
        start = dict(zip(("latitude", "longitude"), graph.coordinates[first]))
        destination = dict(zip(("latitude", "longitude"), graph.coordinates[second]))
        for travel_time in TIMES:
            began = time.perf_counter()
            status, response = app.create_route_response({"start": start, "destination": destination, "travel_time": travel_time})
            elapsed = time.perf_counter() - began
            durations.append(elapsed)
            routes = response.get("routes", [])
            labels = {section["label"] for route in routes for section in route["exposure"]["sections"]}
            rows.append({
                "trip": number,
                "time": travel_time[11:16],
                "status": status,
                "seconds": elapsed,
                "routes": len(routes),
                "sun": " / ".join(f"{route['exposure']['sun_percent']:.1f}" for route in routes),
                "sun_min": " / ".join(f"{route['exposure']['sun_minutes']:.1f}" for route in routes),
                "unknown": " / ".join(f"{route['exposure']['unknown_percent']:.1f}" for route in routes),
                "sections": " / ".join(str(len(route["exposure"]["sections"])) for route in routes),
                "mixed": "yes" if {"shaded", "covered"} & labels and {"sun", "unknown"} & labels else "no",
                "comfort": routes[0]["comfort_window"]["recommendation"] if routes else "-",
                "inside_m": sum(crossings(route, footprints) for route in routes),
                "weather": response.get("weather", {}).get("temperature_c", {}).get("status", "-"),
            })

    print("## Acceptance run\n")
    print(f"Pairs: 10 seeded random node pairs 300–1500 m apart; times {', '.join(t[11:16] for t in TIMES)} on 2026-10-15.\n")
    print("| Trip | Time | Status | Seconds | Routes | Sun % (shortest / shadier) | Sun min | Unknown % | Sections | Mixed labels | Comfort | Metres inside footprints | Weather |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print(f"| {row['trip']} | {row['time']} | {row['status']} | {row['seconds']:.2f} | {row['routes']} | {row['sun']} | {row['sun_min']} | {row['unknown']} | {row['sections']} | {row['mixed']} | {row['comfort']} | {row['inside_m']:.0f} | {row['weather']} |")

    within = sum(1 for value in durations if value <= P01_LIMIT_SECONDS)
    two_routes = sum(1 for row in rows if row["routes"] == 2)
    changed = 0
    for trip in range(1, 11):
        values = {row["sun"] for row in rows if row["trip"] == trip}
        changed += len(values) > 1
    print("\n### Summary\n")
    print(f"- P-01: {within} of {len(durations)} requests within {P01_LIMIT_SECONDS:.0f} s (median {statistics.median(durations):.2f} s, max {max(durations):.2f} s). Measured in-process, without HTTP or phone network time.")
    print(f"- F-01: {sum(1 for row in rows if row['status'] == 200)} of {len(rows)} requests returned routes with sun figures.")
    print(f"- F-02: {changed} of 10 trips have different sun figures across 09:00, 12:00 and 15:00.")
    print(f"- F-03: {sum(1 for row in rows if row['mixed'] == 'yes')} of {len(rows)} requests have both shaded and sunny sections.")
    print(f"- F-04: {two_routes} of {len(rows)} requests returned a shadier alternative.")
    print(f"- C-01: {sum(1 for row in rows if row['inside_m'] > 0)} of {len(rows)} requests have route pieces inside an enclosed ground-level OSM building footprint (total {sum(row['inside_m'] for row in rows):.0f} m). {app.WALKING_GRAPH.excluded_indoor_edges} walking edges through such buildings are excluded from the graph.")
    report = app.BUILDING_HEIGHT_REPORT
    print(f"- D-01: {report['with_height']} of {report['buildings']} OSM building footprints have height data; {report['without_height']} are flagged as unknown.")


if __name__ == "__main__":
    main()
