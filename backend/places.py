"""Place search (PRD S-02) over a prebuilt SQLite FTS5 index of named OSM features
(datasets/derived/places.db, written by build_tiles.py). Offline; no external geocoder.
"""

from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path

PLACES_DB = Path(__file__).parents[1] / "datasets" / "derived" / "places.db"
KIND_TAGS = ("amenity", "shop", "leisure", "tourism", "office", "building", "highway", "landuse", "railway", "public_transport")


def kind_of(tags: dict[str, str]) -> str:
    for key in KIND_TAGS:
        value = tags.get(key)
        if value:
            if key == "highway":
                return "street" if value not in {"bus_stop", "crossing", "traffic_signals"} else value.replace("_", " ")
            if key == "building":
                return "building" if value in {"yes", "university", "school"} else value.replace("_", " ")
            return value.replace("_", " ")
    return "place"


def _distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Rough metres, good enough for ranking nearby results."""
    return math.hypot((lat2 - lat1) * 111_320, (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1)))


class PlaceIndex:
    def __init__(self, path: Path = PLACES_DB) -> None:
        self.path = Path(path)

    def search(self, query: str, limit: int = 8, near: tuple[float, float] | None = None) -> list[dict]:
        """Prefix matches first, then word-start matches, then any match. With `near`, ties
        break by distance, so a chain store finds the branch closest to the trip."""
        needle = query.strip().casefold()
        words = re.findall(r"\w+", needle)
        if len(needle) < 2 or not words:
            return []
        match = " ".join(f'"{word}"*' for word in words)
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT name, kind, id, lat, lon FROM places WHERE places MATCH ? ORDER BY rank LIMIT 2000", (match,)
            ).fetchall()
        finally:
            connection.close()

        def score(row) -> tuple:
            name = row[0].casefold()
            level = 0 if name.startswith(needle) else 1 if any(part.startswith(needle) for part in name.split()) else 2
            distance = _distance(near[0], near[1], row[3], row[4]) if near else 0.0
            return (level, distance, name)

        return [
            {"id": identifier, "name": name, "kind": kind, "latitude": lat, "longitude": lon}
            for name, kind, identifier, lat, lon in sorted(rows, key=score)[:limit]
        ]
