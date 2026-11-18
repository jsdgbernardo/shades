"""Acceptance evidence for PRD checks that can be scripted.

Run from the repository root:  python backend/acceptance.py
It calls the API functions directly (no HTTP), including the live Open-Meteo weather fetch,
and prints a Markdown report. It does not write to the ratings/covered database.

Covered here: F-01 to F-05, F-08, F-09, F-15 (figures present), P-01 (timing without HTTP or
network latency to a phone; first requests include loading map tiles), C-01 (indoor edges dropped
by the data build), D-01 (buildings with height data). Trips are sampled around Katipunan (with
building heights) and in Makati and Manila (no heights, so "shade unknown"). Not covered: anything needing people, a phone or a site visit
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

TIMES = ["2026-10-15T09:00:00+08:00", "2026-10-15T12:00:00+08:00", "2026-10-15T15:00:00+08:00"]
P01_LIMIT_SECONDS = 10.0


AREAS = {
    "Katipunan": (14.632, 121.060, 14.660, 121.090),
    "Makati": (14.548, 121.015, 14.562, 121.035),
    "Manila": (14.580, 120.975, 14.600, 120.995),
}
PAIRS_PER_AREA = {"Katipunan": 6, "Makati": 2, "Manila": 2}


def sample_pairs(seed: int = 2026) -> list[tuple[str, int, int]]:
    """Connected node pairs 300–1500 m apart from seeded random points in each area."""
    graph = app.WALKING_GRAPH
    rng = random.Random(seed)
    pairs = []
    for area, count in PAIRS_PER_AREA.items():
        south, west, north, east = AREAS[area]
        found = 0
        while found < count:
            first, second = (graph.nearest_node((rng.uniform(south, north), rng.uniform(west, east))) for _ in range(2))
            if first is None or second is None or first == second:
                continue
            if 300 <= haversine_meters(graph.coordinates[first], graph.coordinates[second]) <= 1500 and graph.route_nodes(first, second):
                pairs.append((area, first, second))
                found += 1
    return pairs


def main() -> None:
    graph = app.WALKING_GRAPH
    started = time.perf_counter()
    rows = []
    durations = []
    pairs = sample_pairs()
    sampling_seconds = time.perf_counter() - started
    for number, (area, first, second) in enumerate(pairs, start=1):
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
                "area": area,
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
                "weather": response.get("weather", {}).get("temperature_c", {}).get("status", "-"),
            })

    print("## Acceptance run\n")
    print(f"Pairs: 10 seeded random node pairs 300–1500 m apart (6 Katipunan, 2 Makati, 2 Manila); times {', '.join(t[11:16] for t in TIMES)} on 2026-10-15.\n")
    print("| Trip | Area | Time | Status | Seconds | Routes | Sun % (shortest / shadier) | Sun min | Unknown % | Sections | Mixed labels | Comfort | Weather |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print(f"| {row['trip']} | {row['area']} | {row['time']} | {row['status']} | {row['seconds']:.2f} | {row['routes']} | {row['sun']} | {row['sun_min']} | {row['unknown']} | {row['sections']} | {row['mixed']} | {row['comfort']} | {row['weather']} |")

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
    print(f"- C-01: {app.WALKING_GRAPH.excluded_indoor_edges} walking edges through enclosed ground-level buildings were dropped by the data build (checked by test_routing).")
    print(f"- Tiles: {app.WALKING_GRAPH.store.loads} graph tiles loaded on demand for this run; sampling the pairs (with tile loads) took {sampling_seconds:.1f} s.")
    report = app.BUILDING_HEIGHT_REPORT
    print(f"- D-01: {report['with_height']} of {report['buildings']} OSM building footprints have height data; {report['without_height']} are flagged as unknown.")


if __name__ == "__main__":
    main()
