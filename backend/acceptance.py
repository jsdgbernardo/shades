"""Acceptance evidence for PRD checks that can be scripted.

Run from the repository root:  python backend/acceptance.py [--url BASE]
Without --url it calls the API functions directly (no HTTP), including the live Open-Meteo
weather fetch. With --url (for example https://shades-jsb.vercel.app) every route request is
POSTed to BASE/api/routes, as the frontend sends it, and the Seconds column is the full round
trip from this machine. Points go only in the POST body, never in the URL (C-04). The sample
pairs are always chosen in-process, because that needs the walking graph. It prints a Markdown
report and does not write to the ratings/covered database.

Covered here: F-01 to F-05, F-08, F-09, F-15 (figures present), P-01 (timing in-process, or
from this machine over the network with --url; first requests include loading map tiles),
C-01 (indoor edges dropped by the data build), D-01 (buildings with height data). Short trips
are sampled around Katipunan (with building heights) and in Makati and Manila (no heights, so
"shade unknown"); long trips 5–10 km apart are sampled across central Metro Manila. Not covered:
anything needing people, a phone or a site visit (S-07, A-01, F-13/F-14 on a device, O-02 on a
phone).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import app  # noqa: E402
from area import MAX_TRIP_M, MAX_WALK_M  # noqa: E402
from routing import haversine_meters  # noqa: E402

TIMES = ["2026-10-15T09:00:00+08:00", "2026-10-15T12:00:00+08:00", "2026-10-15T15:00:00+08:00"]
P01_LIMIT_SECONDS = 10.0
REMOTE_TIMEOUT_SECONDS = 60


AREAS = {
    "Katipunan": (14.632, 121.060, 14.660, 121.090),
    "Makati": (14.548, 121.015, 14.562, 121.035),
    "Manila": (14.580, 120.975, 14.600, 120.995),
}
PAIRS_PER_AREA = {"Katipunan": 6, "Makati": 2, "Manila": 2}
SHORT_RANGE_M = (300, 1500)

# Long trips: both ends anywhere in central Metro Manila (Quezon City down to Makati and Manila).
LONG_AREA = (14.540, 120.985, 14.680, 121.100)
LONG_PAIRS = 3
LONG_RANGE_M = (5000, MAX_TRIP_M)


def _connected_pairs(rng: random.Random, box: tuple[float, float, float, float], count: int,
                     distance_range: tuple[float, float]) -> list[tuple[int, int, float]]:
    """``count`` connected node pairs whose straight-line distance is within ``distance_range``."""
    graph = app.WALKING_GRAPH
    south, west, north, east = box
    low, high = distance_range
    pairs = []
    while len(pairs) < count:
        first, second = (graph.nearest_node((rng.uniform(south, north), rng.uniform(west, east))) for _ in range(2))
        if first is None or second is None or first == second:
            continue
        straight = haversine_meters(graph.coordinates[first], graph.coordinates[second])
        if not low <= straight <= high:
            continue
        # The API's shortest-route search limit, so a hopeless pair fails fast.
        if graph.route_nodes(first, second, max_cost=min(3 * straight + 5000, MAX_WALK_M)):
            pairs.append((first, second, straight))
    return pairs


def sample_pairs(seed: int = 2026) -> list[tuple[str, int, int, float]]:
    """Short pairs (300–1500 m) in each area, then long pairs (5–10 km).

    Each item is (area, start node, destination node, straight-line metres).
    """
    rng = random.Random(seed)
    pairs = []
    for area, count in PAIRS_PER_AREA.items():
        pairs += [(area, *pair) for pair in _connected_pairs(rng, AREAS[area], count, SHORT_RANGE_M)]
    # A generator of their own, so the long trips leave the short pairs as they were before.
    long_rng = random.Random(seed + 1)
    pairs += [("Long", *pair) for pair in _connected_pairs(long_rng, LONG_AREA, LONG_PAIRS, LONG_RANGE_M)]
    return pairs


def check_base_url(base: str) -> str:
    """BASE must be https (http only for this machine) and only the site: no path, query or fragment."""
    parts = urllib.parse.urlsplit(base.strip().rstrip("/"))
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise SystemExit("--url must start with https:// (http:// is allowed only for localhost).")
    if not parts.hostname or parts.path or parts.query or parts.fragment:
        raise SystemExit("--url must be just the site, for example https://shades-jsb.vercel.app")
    return f"{parts.scheme}://{parts.netloc}"


def remote_route_response(base: str, payload: dict) -> tuple[int | str, dict]:
    """POST the payload to BASE/api/routes as the frontend does. The points stay in the body (C-04).

    HTTP errors come back as their status code; network failures as "error: <kind>".
    """
    request = urllib.request.Request(
        f"{base}/api/routes",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "shades-acceptance"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REMOTE_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body if isinstance(body, dict) else {}
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (ValueError, OSError):
            body = {}
        return error.code, body if isinstance(body, dict) else {}
    except (urllib.error.URLError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        return f"error: {type(reason).__name__}", {}


def p01_line(label: str, durations: list[float]) -> str:
    if not durations:
        return f"{label}: no requests"
    within = sum(1 for value in durations if value <= P01_LIMIT_SECONDS)
    return (f"{label}: {within} of {len(durations)} within {P01_LIMIT_SECONDS:.0f} s "
            f"(median {statistics.median(durations):.2f} s, max {max(durations):.2f} s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scripted PRD acceptance evidence, printed as Markdown.")
    parser.add_argument("--url", metavar="BASE",
                        help="send each route request to BASE/api/routes over HTTPS instead of calling the API in-process")
    args = parser.parse_args()
    base = check_base_url(args.url) if args.url else None

    graph = app.WALKING_GRAPH
    started = time.perf_counter()
    rows = []
    pairs = sample_pairs()
    sampling_seconds = time.perf_counter() - started
    run_started = time.perf_counter()
    for number, (area, first, second, straight) in enumerate(pairs, start=1):
        start = dict(zip(("latitude", "longitude"), graph.coordinates[first]))
        destination = dict(zip(("latitude", "longitude"), graph.coordinates[second]))
        for travel_time in TIMES:
            payload = {"start": start, "destination": destination, "travel_time": travel_time}
            began = time.perf_counter()
            if base:
                status, response = remote_route_response(base, payload)
            else:
                status, response = app.create_route_response(payload)
            elapsed = time.perf_counter() - began
            routes = response.get("routes", []) if status == 200 else []
            labels = {section["label"] for route in routes for section in route["exposure"]["sections"]}
            rows.append({
                "trip": number,
                "area": area,
                "long": area == "Long",
                "km": straight / 1000,
                "time": travel_time[11:16],
                "status": status,
                "seconds": elapsed,
                "routes": len(routes),
                "walk_km": " / ".join(f"{route['distance_m'] / 1000:.2f}" for route in routes) or "-",
                "sun": " / ".join(f"{route['exposure']['sun_percent']:.1f}" for route in routes) or "-",
                "sun_min": " / ".join(f"{route['exposure']['sun_minutes']:.1f}" for route in routes) or "-",
                "unknown": " / ".join(f"{route['exposure']['unknown_percent']:.1f}" for route in routes) or "-",
                "sections": " / ".join(str(len(route["exposure"]["sections"])) for route in routes) or "-",
                "mixed": "yes" if {"shaded", "covered"} & labels and {"sun", "unknown"} & labels else "no",
                "comfort": routes[0]["comfort_window"]["recommendation"] if routes else "-",
                "weather": (response.get("weather") or {}).get("temperature_c", {}).get("status", "-"),
            })
    run_seconds = time.perf_counter() - run_started

    short_count = sum(PAIRS_PER_AREA.values())
    long_rows = [row for row in rows if row["long"]]
    long_km = sorted({round(row["km"], 1) for row in long_rows})
    mode = f"remote, POST {base}/api/routes over the network" if base else "in-process (app.create_route_response, no HTTP)"

    print("## Acceptance run\n")
    print(f"Mode: {mode}.\n")
    print(f"Pairs: {short_count} seeded random node pairs {SHORT_RANGE_M[0]}–{SHORT_RANGE_M[1]} m apart "
          f"({', '.join(f'{count} {area}' for area, count in PAIRS_PER_AREA.items())}) and {LONG_PAIRS} long pairs "
          f"{LONG_RANGE_M[0] // 1000}–{LONG_RANGE_M[1] // 1000} km apart across central Metro Manila "
          f"({', '.join(f'{km:.1f}' for km in long_km)} km straight-line); times {', '.join(t[11:16] for t in TIMES)} on 2026-10-15.\n")
    print("| Trip | Area | Straight km | Time | Status | Seconds | Routes | Walk km | Sun % (shortest / shadier) | Sun min | Unknown % | Sections | Mixed labels | Comfort | Weather |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print(f"| {row['trip']} | {row['area']} | {row['km']:.2f} | {row['time']} | {row['status']} | {row['seconds']:.2f} | {row['routes']} | "
              f"{row['walk_km']} | {row['sun']} | {row['sun_min']} | {row['unknown']} | {row['sections']} | {row['mixed']} | {row['comfort']} | {row['weather']} |")

    durations = [row["seconds"] for row in rows]
    ok = [row for row in rows if row["status"] == 200]
    failed = [row for row in rows if row["status"] != 200]
    two_routes = sum(1 for row in rows if row["routes"] == 2)
    changed = sum(len({row["sun"] for row in rows if row["trip"] == trip}) > 1 for trip in range(1, len(pairs) + 1))
    print("\n### Summary\n")
    print(f"- Mode: {mode}.")
    if base:
        print("- Remote timings are full round trips from this machine's network connection, not from a phone on mobile data; "
              "they include any cold start of the host.")
    else:
        print("- In-process timings exclude HTTP and any network time to a phone.")
    print(f"- P-01: {p01_line('all', durations)}; {p01_line(f'short ({short_count} trips)', [r['seconds'] for r in rows if not r['long']])}; "
          f"{p01_line(f'long ({LONG_PAIRS} trips)', [r['seconds'] for r in long_rows])}.")
    if failed:
        statuses = sorted({str(row["status"]) for row in failed})
        print(f"- Not 200: {len(failed)} of {len(rows)} requests ({', '.join(statuses)}).")
    print(f"- F-01: {len(ok)} of {len(rows)} requests returned routes with sun figures.")
    print(f"- F-02: {changed} of {len(pairs)} trips have different sun figures across {', '.join(t[11:16] for t in TIMES)}.")
    print(f"- F-03: {sum(1 for row in rows if row['mixed'] == 'yes')} of {len(rows)} requests have both shaded and sunny sections.")
    print(f"- F-04: {two_routes} of {len(rows)} requests returned a shadier alternative.")
    print(f"- C-01: {app.WALKING_GRAPH.excluded_indoor_edges} walking edges through enclosed ground-level buildings were dropped by the data build (checked by test_routing).")
    tiles_note = "on this machine for sampling" if base else "on demand for this run"
    print(f"- Tiles: {app.WALKING_GRAPH.store.loads} graph tiles loaded {tiles_note}; sampling the pairs (with tile loads) took "
          f"{sampling_seconds:.1f} s and the {len(rows)} requests took {run_seconds:.1f} s.")
    report = app.BUILDING_HEIGHT_REPORT
    print(f"- D-01: {report['with_height']} of {report['buildings']} OSM building footprints have height data; {report['without_height']} are flagged as unknown.")


if __name__ == "__main__":
    main()
