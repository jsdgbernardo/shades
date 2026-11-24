"""The online ratings store (PRD D-03), against a fake Turso server backed by in-memory SQLite."""

import json
import os
import sqlite3
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import app
from storage import NoStore, StoreError, TursoStore, open_store


def fake_turso():
    """A server speaking the parts of Turso's /v2/pipeline that TursoStore uses."""
    database = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    lock = threading.Lock()

    def encode(value):
        if value is None:
            return {"type": "null"}
        if isinstance(value, float):
            return {"type": "float", "value": value}
        return {"type": "integer" if isinstance(value, int) else "text", "value": str(value)}

    class Handler(BaseHTTPRequestHandler):
        paths = []

        def log_message(self, *_args):
            return

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.paths.append(self.path)
            if self.headers["Authorization"] != "Bearer secret":
                self.send_error(401)
                return
            results = []
            for item in body["requests"]:
                if item["type"] == "close":
                    results.append({"type": "ok", "response": {"type": "close"}})
                    continue
                args = [int(arg["value"]) if arg["type"] == "integer" else arg["value"] for arg in item["stmt"]["args"]]
                try:
                    with lock:
                        rows = database.execute(item["stmt"]["sql"], args).fetchall()
                    results.append({"type": "ok", "response": {"type": "execute", "result": {"rows": [[encode(v) for v in row] for row in rows]}}})
                except sqlite3.Error as error:
                    results.append({"type": "error", "error": {"message": str(error)}})
            encoded = json.dumps({"results": results}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, Handler.paths


class TursoStoreTests(unittest.TestCase):
    def setUp(self):
        self.server, self.paths = fake_turso()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_ratings_and_marks_are_seen_by_a_second_instance(self):
        first = TursoStore(self.url, "secret")
        for rating in (3, 4, 5):
            first.add_rating(1001, rating)
        first.add_rating(1002, 2)
        first.set_covered("1001:1-2", True)
        first.set_covered("1001:1-2", True)
        second = TursoStore(self.url + "/", "secret")
        self.assertEqual(second.rating_stats([1001, 1001, 7]), {1001: (3, 4.0)})
        self.assertEqual(second.rating_stats(), {1001: (3, 4.0), 1002: (1, 2.0)})
        self.assertEqual(second.covered_edges(), {"1001:1-2"})
        second.set_covered("1001:1-2", False)
        self.assertEqual(first.covered_edges(), set())
        self.assertEqual(set(self.paths), {"/v2/pipeline"})

    def test_empty_street_list_needs_no_request(self):
        self.assertEqual(TursoStore(self.url, "secret").rating_stats([]), {})
        self.assertEqual(self.paths, [])

    def test_bad_ratings_are_rejected_before_any_request(self):
        for bad in (0, 6, 3.5, "4", None, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                TursoStore(self.url, "secret").add_rating(1001, bad)
        self.assertEqual(self.paths, [])

    def test_wrong_token_and_sql_errors_raise_without_showing_the_token(self):
        with self.assertRaises(StoreError) as caught:
            TursoStore(self.url, "wrong-token").covered_edges()
        self.assertNotIn("wrong-token", str(caught.exception))
        with self.assertRaises(StoreError):
            TursoStore(self.url, "secret")._run("SELECT * FROM missing")

    def test_bad_address_raises_store_error(self):
        for url in ("not a url", "http://127.0.0.1:1"):
            with self.subTest(url=url), self.assertRaises(StoreError):
                TursoStore(url, "secret").covered_edges()

    def test_libsql_addresses_become_https(self):
        self.assertEqual(TursoStore("libsql://db-org.turso.io", "x").url, "https://db-org.turso.io/v2/pipeline")


class StoreChoiceTests(unittest.TestCase):
    def choose(self, **environment):
        with patch.dict(os.environ, environment):
            for name in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "VERCEL"):
                if name not in environment:
                    os.environ.pop(name, None)
            with patch("storage.Store") as local:
                return open_store(), local.called

    def test_store_follows_the_environment(self):
        self.assertIsInstance(self.choose(TURSO_DATABASE_URL="libsql://a", TURSO_AUTH_TOKEN="b", VERCEL="1")[0], TursoStore)
        store, opened_local = self.choose(VERCEL="1")
        self.assertIsInstance(store, NoStore)
        self.assertFalse(opened_local)  # nothing may touch Vercel's read-only disk
        self.assertTrue(self.choose()[1])


class UnreachableStoreTests(unittest.TestCase):
    """With the ratings database down, routes still work and saves say they failed."""

    TRIP = {
        "start": {"latitude": 14.64071, "longitude": 121.07482},
        "destination": {"latitude": 14.6378, "longitude": 121.0776},
        "travel_time": "2026-10-15T12:00:00+08:00",
    }

    def setUp(self):
        self.weather = patch("app.fetch_weather", return_value={})
        self.fetch = self.weather.start()
        self.addCleanup(self.weather.stop)
        store = patch("app.STORE", NoStore())
        store.start()
        self.addCleanup(store.stop)
        self.section = app.WALKING_GRAPH.nearest_edge((14.6407, 121.0748), max_distance_m=60)

    def test_routes_and_streets_still_work(self):
        status, response = app.create_route_response(self.TRIP)
        self.assertEqual(status, 200)
        self.assertEqual(response["routes"][0]["walkability"]["status"], "not available")
        self.assertIsNone(response["routes"][0]["walkability"]["score"])
        status, response = app.create_street_response(self.section["way_id"])
        self.assertEqual((status, response["walkability"]["status"]), (200, "not available"))
        self.assertEqual(app.create_nearest_street_response({"latitude": 14.6407, "longitude": 121.0748})[0], 200)
        self.assertEqual(app.create_covered_list_response(), (200, {"covered": []}))

    def test_saves_report_the_failure(self):
        self.assertEqual(app.create_rating_response(self.section["way_id"], {"rating": 4})[0], 503)
        self.assertEqual(app.create_covered_update_response(self.section["edge_key"], True)[0], 503)

    def test_the_exact_start_is_not_shared_with_the_weather_service(self):
        app.create_route_response(self.TRIP)
        self.assertEqual(self.fetch.call_args.args[:2], (14.6, 121.1))


if __name__ == "__main__":
    unittest.main()
