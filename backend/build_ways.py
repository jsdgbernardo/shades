"""Build datasets/derived/ways.db: which graph tiles hold each OSM way.

The API loads tiles on demand, so a saved rating or covered mark may name a street whose tile
is not loaded yet. This index says which tiles to load. It is made from the committed tiles,
so it needs no OSM download:  python backend/build_ways.py   (build_tiles.py runs it too)
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

from tiles import TILES_DIR, WAYS_DB


def build_ways(directory: Path = TILES_DIR, path: Path = WAYS_DB) -> int:
    """Write way id -> tile rows; returns the number of distinct ways."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    rows = []
    for file in sorted(directory.glob("*.json.gz")):
        column, row = (int(part) for part in file.name.split(".")[0].split("_"))
        with gzip.open(file, "rt", encoding="utf-8") as handle:
            # Ways with an edge starting in this tile.
            rows += [(way_id, column, row) for way_id in sorted({edge[3] for edge in json.load(handle)["edges"]})]
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE way_tiles (way_id INTEGER, col INTEGER, row INTEGER, PRIMARY KEY (way_id, col, row)) WITHOUT ROWID")
        connection.executemany("INSERT INTO way_tiles VALUES (?, ?, ?)", rows)
    connection.execute("VACUUM")
    connection.close()
    return len({row[0] for row in rows})


if __name__ == "__main__":
    print(f"{build_ways()} ways indexed, {WAYS_DB.stat().st_size / 1e6:.1f} MB")
