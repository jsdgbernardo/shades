"""Shared, persistent user data: street walkability ratings and covered-walkway marks (PRD D-03).

Two stores with the same methods, chosen by open_store():
- Store: a local SQLite file. Each call opens its own connection because the HTTP server
  handles requests on several threads.
- TursoStore: the same SQL in a hosted SQLite database (Turso) over https, for hosts that do
  not keep files. Used when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set.
No location or personal data is stored (PRD C-04).

A rating can be changed or removed later by the device that made it: saving one returns a random
token, the device keeps it, and the store keeps only the token's SHA-256 hash. Tokens are random
per rating, so they do not link one person's ratings together.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_PATH = Path(__file__).parents[1] / "data" / "shades.db"
MIN_RATINGS = 3
REMOTE_TIMEOUT_S = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    way_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL,
    token_hash TEXT
);
CREATE INDEX IF NOT EXISTS ratings_way ON ratings (way_id);
CREATE TABLE IF NOT EXISTS covered_marks (
    edge_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


# Databases made before rating tokens lack the column; added on first use.
TOKEN_COLUMN = "ALTER TABLE ratings ADD COLUMN token_hash TEXT"
TOKEN_INDEX = "CREATE INDEX IF NOT EXISTS ratings_token ON ratings (way_id, token_hash)"
HAS_TOKEN_COLUMN = "SELECT COUNT(*) FROM pragma_table_info('ratings') WHERE name = 'token_hash'"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(16)


def now() -> str:
    """The date only (UTC). Several ratings saved at the same second would trace one person's walk,
    and location must not be stored (PRD C-04)."""
    return datetime.now(timezone.utc).date().isoformat()


class StoreError(Exception):
    """The store could not be read or written."""


def check_rating(rating: object) -> None:
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
        raise ValueError("rating must be a whole number from 1 to 5")


class Store:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(SCHEMA)
            if not connection.execute(HAS_TOKEN_COLUMN).fetchone()[0]:
                connection.execute(TOKEN_COLUMN)
            connection.execute(TOKEN_INDEX)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def add_rating(self, way_id: int, rating: int, token: str | None = None) -> str:
        """Saves a rating and returns its token. With the token of this street's earlier rating
        from the same device, that rating is replaced instead of a new one being added."""
        check_rating(rating)
        with closing(self._connect()) as connection, connection:
            if token and connection.execute(
                "UPDATE ratings SET rating = ?, created_at = ? WHERE way_id = ? AND token_hash = ?",
                (rating, now(), way_id, token_hash(token)),
            ).rowcount:
                return token
            token = new_token()
            connection.execute("INSERT INTO ratings (way_id, rating, created_at, token_hash) VALUES (?, ?, ?, ?)",
                               (way_id, rating, now(), token_hash(token)))
            return token

    def remove_rating(self, way_id: int, token: str) -> bool:
        """Removes the rating made with this token. False when there is none."""
        with closing(self._connect()) as connection, connection:
            return connection.execute("DELETE FROM ratings WHERE way_id = ? AND token_hash = ?",
                                      (way_id, token_hash(str(token)))).rowcount > 0

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


class TursoStore:
    """Same methods as Store, over Turso's HTTP API (POST /v2/pipeline). Nothing connects until first use."""

    def __init__(self, url: str, token: str) -> None:
        # Turso shows libsql:// addresses; the HTTP API is the same host over https.
        self.url = url.strip().replace("libsql://", "https://", 1).rstrip("/") + "/v2/pipeline"
        self.token = token.strip()
        self._schema_ready = False
        self._lock = threading.Lock()

    def _pipeline(self, statements: list[tuple[str, tuple]]) -> list[list[list]]:
        """Run statements in order; returns the rows of each. Raises StoreError on any failure."""
        requests: list[dict] = [
            {"type": "execute", "stmt": {"sql": sql, "args": [self._encode(value) for value in args]}}
            for sql, args in statements
        ]
        body = json.dumps({"requests": requests + [{"type": "close"}]}).encode("utf-8")
        try:
            request = Request(self.url, data=body, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
            })
            with urlopen(request, timeout=REMOTE_TIMEOUT_S) as response:
                results = json.load(response)["results"][:len(statements)]
            if len(results) < len(statements) or any(result["type"] != "ok" for result in results):
                raise StoreError("the ratings database rejected a statement")
            return [[[self._decode(cell) for cell in row] for row in result["response"]["result"]["rows"]] for result in results]
        # ValueError covers bad JSON and malformed URLs; the cause is dropped so a token is never shown.
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise StoreError(f"the ratings database is unreachable ({type(error).__name__})") from None

    def _run(self, sql: str, args: tuple = ()) -> list[list]:
        with self._lock:
            if not self._schema_ready:
                self._pipeline([(statement.strip(), ()) for statement in SCHEMA.split(";") if statement.strip()])
                if not self._pipeline([(HAS_TOKEN_COLUMN, ())])[0][0][0]:
                    self._pipeline([(TOKEN_COLUMN, ())])
                self._pipeline([(TOKEN_INDEX, ())])
                self._schema_ready = True
        return self._pipeline([(sql, args)])[0]

    def _changes(self, sql: str, args: tuple) -> int:
        """Runs a write and returns how many rows it changed."""
        rows = self._pipeline([(sql, args), ("SELECT changes()", ())])
        return int(rows[1][0][0])

    @staticmethod
    def _encode(value: int | str) -> dict[str, str]:
        return {"type": "integer" if isinstance(value, int) else "text", "value": str(value)}

    @staticmethod
    def _decode(cell: dict) -> int | float | str | None:
        kind = cell["type"]
        if kind == "null":
            return None
        return int(cell["value"]) if kind == "integer" else float(cell["value"]) if kind == "float" else cell["value"]

    def add_rating(self, way_id: int, rating: int, token: str | None = None) -> str:
        check_rating(rating)
        self._run("SELECT 1")  # make sure the schema is ready before counting changes
        if token and self._changes("UPDATE ratings SET rating = ?, created_at = ? WHERE way_id = ? AND token_hash = ?",
                                   (rating, now(), way_id, token_hash(token))):
            return token
        token = new_token()
        self._run("INSERT INTO ratings (way_id, rating, created_at, token_hash) VALUES (?, ?, ?, ?)",
                  (way_id, rating, now(), token_hash(token)))
        return token

    def remove_rating(self, way_id: int, token: str) -> bool:
        self._run("SELECT 1")
        return self._changes("DELETE FROM ratings WHERE way_id = ? AND token_hash = ?", (way_id, token_hash(str(token)))) > 0

    def rating_stats(self, way_ids: list[int] | None = None) -> dict[int, tuple[int, float]]:
        unique = sorted(set(way_ids or ()))
        if way_ids is not None and not unique:
            return {}
        where = f" WHERE way_id IN ({','.join('?' * len(unique))})" if unique else ""
        rows = self._run(f"SELECT way_id, COUNT(*), AVG(rating) FROM ratings{where} GROUP BY way_id", tuple(unique))
        return {row[0]: (row[1], row[2]) for row in rows}

    def covered_edges(self) -> set[str]:
        return {row[0] for row in self._run("SELECT edge_key FROM covered_marks")}

    def set_covered(self, edge_key: str, covered: bool) -> None:
        if covered:
            self._run("INSERT OR IGNORE INTO covered_marks (edge_key, created_at) VALUES (?, ?)", (edge_key, now()))
        else:
            self._run("DELETE FROM covered_marks WHERE edge_key = ?", (edge_key,))


class NoStore:
    """Stands in on a host that keeps no files when no online database is set up yet."""

    def _unavailable(self, *_args: object) -> None:
        raise StoreError("no ratings database is configured")

    add_rating = remove_rating = rating_stats = covered_edges = set_covered = _unavailable


def open_store() -> Store | TursoStore | NoStore:
    url, token = os.environ.get("TURSO_DATABASE_URL"), os.environ.get("TURSO_AUTH_TOKEN")
    if url and token:
        return TursoStore(url, token)
    if os.environ.get("VERCEL"):
        return NoStore()  # Vercel's disk is read-only, and anything saved there would be lost
    return Store(Path(os.environ.get("SHADES_DB", DEFAULT_PATH)))


def street_score(count: int, average: float | None) -> dict[str, object]:
    """Street walkability from user ratings only (PRD S-09, C-02)."""
    if count < MIN_RATINGS or average is None:
        return {"status": "not enough ratings", "rating_count": count, "average": None}
    return {"status": "rated", "rating_count": count, "average": round(average, 2)}


def route_walkability(edges: list[dict], stats: dict[int, tuple[int, float]] | None) -> dict[str, object]:
    """Length-weighted average over the route's rated streets, and the rated share of its length.

    `stats` is None when the ratings could not be read.
    """
    if stats is None:
        return {"basis": "user ratings", "status": "not available", "score": None, "rated_share_percent": None}
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
