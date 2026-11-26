"""MRT and LRT network for the walk, train, walk option (PRD F-16 to F-19, D-04, C-07; stretch).

Reads datasets/derived/rail.json (written by build_rail.py): LRT-1, LRT-2 and MRT-3 with their
stations in order, track shapes and the transfers between lines. No schedules, fares, delays,
crowding or service status are used (C-07): the ride time is the ride distance at one fixed
average speed plus a fixed allowance for each transfer (F-18).
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

RAIL_PATH = Path(__file__).parents[1] / "datasets" / "derived" / "rail.json"

# One average speed from published end-to-end running times (read 2026-11-26):
# LRT-2 Recto-Antipolo about 40 min (DOTr), MRT-3 North Avenue-Taft Avenue 45 min after the
# rehabilitation (RTVM 2022), LRT-1 Fernando Poe Jr.-Dr. Santos "under an hour" (taken as 60 min).
# Line lengths from rail.json: 16.6 + 16.5 + 24.6 km over 145 min = about 24 km/h.
RIDE_SPEED_KMH = 24.0
RIDE_SPEED_M_PER_MIN = RIDE_SPEED_KMH * 1000 / 60
# Walking between the two stations of a transfer and waiting for the next train.
TRANSFER_MINUTES = 10.0


def distance_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Metres between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(value))


@dataclass
class Station:
    id: str
    name: str
    line: str
    lat: float
    lon: float
    position_m: float
    entrances: list[tuple[float, float]]
    entrance_source: str


@dataclass
class Line:
    id: str
    name: str
    ref: str
    colour: str
    shape: list[tuple[float, float]]  # (lat, lon)
    stations: list[str]
    cumulative: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cumulative = [0.0]
        for first, second in zip(self.shape, self.shape[1:]):
            self.cumulative.append(self.cumulative[-1] + distance_m(first, second))

    def slice(self, start_m: float, end_m: float) -> list[list[float]]:
        """The track between two positions along the line, as [lon, lat] points, in riding order."""
        low, high = sorted((start_m, end_m))
        points = [self._point_at(low)]
        points += [[lon, lat] for (lat, lon), at in zip(self.shape, self.cumulative) if low < at < high]
        points.append(self._point_at(high))
        return points if start_m <= end_m else points[::-1]

    def _point_at(self, along: float) -> list[float]:
        along = max(0.0, min(along, self.cumulative[-1]))
        for index in range(1, len(self.cumulative)):
            if self.cumulative[index] >= along:
                span = self.cumulative[index] - self.cumulative[index - 1] or 1.0
                t = (along - self.cumulative[index - 1]) / span
                (lat1, lon1), (lat2, lon2) = self.shape[index - 1], self.shape[index]
                return [lon1 + (lon2 - lon1) * t, lat1 + (lat2 - lat1) * t]
        lat, lon = self.shape[-1]
        return [lon, lat]


@dataclass
class Ride:
    stations: list[str]
    distance_m: float
    transfers: list[dict]
    segments: list[dict]

    @property
    def minutes(self) -> float:
        """F-18: ride distance at the fixed average speed, plus the allowance per transfer."""
        return self.distance_m / RIDE_SPEED_M_PER_MIN + TRANSFER_MINUTES * len(self.transfers)


class RailNetwork:
    def __init__(self, path: Path = RAIL_PATH) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.lines: dict[str, Line] = {}
        self.stations: dict[str, Station] = {}
        for line in data["lines"]:
            self.lines[line["id"]] = Line(line["id"], line["name"], line["ref"], line["colour"],
                                          [tuple(point) for point in line["shape"]], [s["id"] for s in line["stations"]])
            for station in line["stations"]:
                self.stations[station["id"]] = Station(
                    station["id"], station["name"], line["id"], station["lat"], station["lon"], station["position_m"],
                    [(entrance["lat"], entrance["lon"]) for entrance in station["entrances"]], station.get("entrance_source", "osm"),
                )
        # Track between neighbouring stations of a line, both ways; transfers cost no distance.
        self.neighbours: dict[str, list[tuple[str, float, bool]]] = {station: [] for station in self.stations}
        for line in self.lines.values():
            for first, second in zip(line.stations, line.stations[1:]):
                gap = abs(self.stations[second].position_m - self.stations[first].position_m)
                self.neighbours[first].append((second, gap, False))
                self.neighbours[second].append((first, gap, False))
        self.transfers = data.get("transfers", [])
        for transfer in self.transfers:
            self.neighbours[transfer["from"]].append((transfer["to"], 0.0, True))
            self.neighbours[transfer["to"]].append((transfer["from"], 0.0, True))

    def ride(self, boarding: str, alighting: str) -> Ride | None:
        """Shortest rail path by distance (fewer transfers on a tie), as line segments and transfers."""
        if boarding == alighting:
            return None
        queue = [(0.0, 0, boarding)]
        best = {boarding: (0.0, 0)}
        previous: dict[str, tuple[str, bool]] = {}
        while queue:
            distance, transfers, station = heapq.heappop(queue)
            if station == alighting:
                break
            if (distance, transfers) > best.get(station, (math.inf, math.inf)):
                continue
            for neighbour, gap, is_transfer in self.neighbours[station]:
                candidate = (distance + gap, transfers + int(is_transfer))
                if candidate < best.get(neighbour, (math.inf, math.inf)):
                    best[neighbour] = candidate
                    previous[neighbour] = (station, is_transfer)
                    heapq.heappush(queue, (*candidate, neighbour))
        if alighting not in best:
            return None
        path = [alighting]
        while path[-1] != boarding:
            path.append(previous[path[-1]][0])
        path.reverse()
        # A trip that is only a transfer between two stations of one interchange is not a ride, and
        # one that starts or ends with a transfer is the same trip as boarding or alighting at the
        # other station of that interchange, which is offered on its own.
        if best[alighting][0] <= 0 or previous[path[1]][1] or previous[path[-1]][1]:
            return None
        return self._describe(path, best[alighting][0])

    def _describe(self, path: list[str], distance: float) -> Ride:
        segments: list[dict] = []
        transfers: list[dict] = []
        start = path[0]
        for here, nxt in zip(path, path[1:]):
            if self.stations[here].line != self.stations[nxt].line:
                if here != start:
                    segments.append(self._segment(start, here))
                transfers.append({"from": self.stations[here].name, "from_line": self.lines[self.stations[here].line].name,
                                  "to": self.stations[nxt].name, "to_line": self.lines[self.stations[nxt].line].name})
                start = nxt
        if path[-1] != start:
            segments.append(self._segment(start, path[-1]))
        return Ride(path, distance, transfers, segments)

    def _segment(self, first: str, second: str) -> dict:
        a, b = self.stations[first], self.stations[second]
        line = self.lines[a.line]
        return {
            "line": line.id, "line_name": line.name, "ref": line.ref, "colour": line.colour,
            "from": a.name, "to": b.name, "geometry": line.slice(a.position_m, b.position_m),
            "distance_m": round(abs(b.position_m - a.position_m), 1),
        }

    def stations_near(self, point: tuple[float, float], radius_m: float) -> list[tuple[Station, tuple[float, float], float]]:
        """Stations with an entrance within radius_m (straight line), nearest first, with that entrance."""
        found = []
        for station in self.stations.values():
            entrance = min(station.entrances, key=lambda spot: distance_m(point, spot))
            gap = distance_m(point, entrance)
            if gap <= radius_m:
                found.append((station, entrance, gap))
        return sorted(found, key=lambda item: item[2])
