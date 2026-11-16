"""Shared, persistent user data: street walkability ratings and covered-walkway marks (PRD D-03).

SQLite from the standard library. Each call opens its own connection because the HTTP server
handles requests on several threads. No location or personal data is stored (PRD C-04).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).parents[1] / "data" / "shades.db"
MIN_RATINGS = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    way_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ratings_way ON ratings (way_id);
CREATE TABLE IF NOT EXISTS covered_marks (
    edge_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def add_rating(self, way_id: int, rating: int) -> None:
        if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
            raise ValueError("rating must be a whole number from 1 to 5")
        with closing(self._connect()) as connection, connection:
            connection.execute("INSERT INTO ratings (way_id, rating, created_at) VALUES (?, ?, ?)", (way_id, rating, now()))

    def rating_stats(self, way_ids: list[int] | None = None) -> dict[int, tuple[int, float]]:
        """way_id -> (number of ratings, average rating)."""
        query = "SELECT way_id, COUNT(*), AVG(rating) FROM ratings"
        parameters: tuple = ()
        if way_ids is not None:
            unique = sorted(set(way_ids))
            if not unique:
                return {}
            query += f" WHERE way_id IN ({','.join('?' * len(unique))})"
            parameters = tuple(unique)
        query += " GROUP BY way_id"
        with closing(self._connect()) as connection:
            return {row[0]: (row[1], row[2]) for row in connection.execute(query, parameters)}

    def covered_edges(self) -> set[str]:
        with closing(self._connect()) as connection:
            return {row[0] for row in connection.execute("SELECT edge_key FROM covered_marks")}

    def set_covered(self, edge_key: str, covered: bool) -> None:
        with closing(self._connect()) as connection, connection:
            if covered:
                connection.execute("INSERT OR IGNORE INTO covered_marks (edge_key, created_at) VALUES (?, ?)", (edge_key, now()))
            else:
                connection.execute("DELETE FROM covered_marks WHERE edge_key = ?", (edge_key,))


def street_score(count: int, average: float | None) -> dict[str, object]:
    """Street walkability from user ratings only (PRD S-09, C-02)."""
    if count < MIN_RATINGS or average is None:
        return {"status": "not enough ratings", "rating_count": count, "average": None}
    return {"status": "rated", "rating_count": count, "average": round(average, 2)}


def route_walkability(edges: list[dict], stats: dict[int, tuple[int, float]]) -> dict[str, object]:
    """Length-weighted average over the route's rated streets, and the rated share of its length."""
    total = sum(edge["length_m"] for edge in edges)
    rated_length = 0.0
    weighted = 0.0
    for edge in edges:
        count, average = stats.get(edge["way_id"], (0, None))
        if count >= MIN_RATINGS and average is not None:
            rated_length += edge["length_m"]
            weighted += average * edge["length_m"]
    return {
        "basis": "user ratings",
        "score": round(weighted / rated_length, 2) if rated_length else None,
        "rated_share_percent": round(rated_length / total * 100, 1) if total else 0.0,
    }
