"""The Vercel entry point (api/index.py) over real HTTP, with both path forms Vercel may pass."""

import importlib.util
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import app
from storage import NoStore

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("vercel_index", ROOT / "api" / "index.py")
vercel_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vercel_index)


class OriginalPathTests(unittest.TestCase):
    def test_both_path_forms_give_the_client_path(self):
        for raw, expected in [
            ("/api/health", "/api/health"),
            ("/api/health?__path=health", "/api/health"),
            ("/api/index?__path=health", "/api/health"),
            ("/api/index.py?__path=streets/nearest", "/api/streets/nearest"),
            ("/api/index?time=2026-11-24T10%3A00%3A00%2B08%3A00&__path=weather", "/api/weather?time=2026-11-24T10%3A00%3A00%2B08%3A00"),
            ("/api/index?__path=covered%2F1%3A2-3", "/api/covered/1:2-3"),
            ("/api/index?__path=covered%2F1%253A2-3", "/api/covered/1:2-3"),
            ("/api/index?__path=streets&__path=nearest", "/api/streets/nearest"),
            ("/api/covered/1%3A2-3?__path=covered%2F1%3A2-3", "/api/covered/1%3A2-3"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(vercel_index.original_path(raw), expected)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        for target in (patch("app.STORE", NoStore()), patch("app.fetch_weather", return_value={"uv": None})):
            target.start()
            self.addCleanup(target.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), vercel_index.handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, path, body=None, method=None):
        request = Request(f"http://127.0.0.1:{self.server.server_port}{path}", method=method,
                          data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_every_endpoint_through_both_path_forms(self):
        section = app.WALKING_GRAPH.nearest_edge((14.6407, 121.0748), max_distance_m=60)
        key = quote(section["edge_key"], safe="")
        point = {"latitude": 14.6407, "longitude": 121.0748}
        trip = {"start": point, "destination": {"latitude": 14.6378, "longitude": 121.0776}, "travel_time": "2026-10-15T12:00:00+08:00"}
        for path, body, method, expected in [
            ("health", None, "GET", 200),
            ("places", {"q": "rizal"}, "POST", 200),
            ("routes", trip, "POST", 200),
            ("streets/nearest", point, "POST", 200),
            (f"streets/{section['way_id']}", None, "GET", 200),
            (f"streets/{section['way_id']}/ratings", {"rating": 4}, "POST", 503),  # no database here
            ("covered", None, "GET", 200),
            (f"covered/{key}", None, "PUT", 503),
            (f"covered/{key}", None, "DELETE", 503),
            ("places", None, "GET", 404),  # points never travel in URLs
            ("nope", None, "GET", 404),
        ]:
            for form in (f"/api/{path}", f"/api/index?__path={quote(path, safe='')}"):
                with self.subTest(method=method, form=form):
                    self.assertEqual(self.call(form, body, method)[0], expected)


class ConfigTests(unittest.TestCase):
    def test_every_data_file_the_api_opens_is_bundled(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        included = config["functions"]["api/index.py"]["includeFiles"]
        for needed in ("backend/*.py", "datasets/tiles/**", "datasets/derived/**", "2026_HEIGHT_GVSSM.tif"):
            self.assertIn(needed, included)
        for name in ("places.db", "ways.db", "build-info.json", "unknown-height-cells.bin"):
            self.assertTrue((ROOT / "datasets" / "derived" / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
