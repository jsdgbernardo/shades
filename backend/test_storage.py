"""PRD S-08 to S-11 and D-03: walkability ratings and covered marks, persisted in SQLite."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from storage import Store, route_walkability, street_score
from weather import build_weather

TRIP = {
    "start": {"latitude": 14.6407, "longitude": 121.0748},
    "destination": {"latitude": 14.6378, "longitude": 121.0776},
    "travel_time": "2026-10-15T12:00:00+08:00",
}


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "test.db"
        self.store = Store(self.path)
        self.patches = [patch("app.STORE", self.store), patch("app.fetch_weather", return_value=build_weather(None, None, None))]
        for active in self.patches:
            active.start()

    def tearDown(self):
        for active in self.patches:
            active.stop()
        self.directory.cleanup()

    def route(self):
        status, response = app.create_route_response(TRIP)
        self.assertEqual(status, 200)
        return response


class PersistenceTests(TempStoreCase):
    def test_ratings_and_marks_survive_reopening_the_database(self):
        self.store.add_rating(1001, 4)
        self.store.set_covered("1001:1-2", True)
        reopened = Store(self.path)
        self.assertEqual(reopened.rating_stats([1001]), {1001: (1, 4.0)})
        self.assertEqual(reopened.covered_edges(), {"1001:1-2"})

    def test_a_device_can_change_and_remove_its_rating(self):
        token = self.store.add_rating(1001, 2)
        self.store.add_rating(1001, 5)  # someone else
        self.assertEqual(self.store.add_rating(1001, 4, token), token)  # replaces, does not add
        self.assertEqual(self.store.rating_stats([1001]), {1001: (2, 4.5)})
        self.assertFalse(self.store.remove_rating(1001, "wrong-token"))
        self.assertFalse(self.store.remove_rating(1002, token))  # a token belongs to one street
        self.assertTrue(self.store.remove_rating(1001, token))
        self.assertEqual(self.store.rating_stats([1001]), {1001: (1, 5.0)})
        # A stale token (rating already removed) simply adds a new rating with a new token.
        fresh = self.store.add_rating(1001, 3, token)
        self.assertNotEqual(fresh, token)
        self.assertEqual(self.store.rating_stats([1001])[1001][0], 2)

    def test_only_a_hash_of_the_token_is_stored(self):
        import sqlite3
        token = self.store.add_rating(1001, 4)
        with sqlite3.connect(self.path) as connection:
            stored = connection.execute("SELECT token_hash FROM ratings").fetchone()[0]
        self.assertNotEqual(stored, token)
        self.assertEqual(len(stored), 64)

    def test_older_databases_gain_the_token_column(self):
        import sqlite3
        old = Path(self.directory.name) / "old.db"
        with sqlite3.connect(old) as connection:
            connection.execute("CREATE TABLE ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, way_id INTEGER NOT NULL, rating INTEGER NOT NULL, created_at TEXT NOT NULL)")
            connection.execute("INSERT INTO ratings (way_id, rating, created_at) VALUES (7, 3, '2026-11-01T10:00:00+00:00')")
        store = Store(old)
        self.assertEqual(store.rating_stats([7]), {7: (1, 3.0)})
        token = store.add_rating(7, 5)
        self.assertTrue(store.remove_rating(7, token))
        self.assertEqual(store.rating_stats([7]), {7: (1, 3.0)})

    def test_rating_api_returns_a_token_and_removes_with_it(self):
        way = app.WALKING_GRAPH.nearest_edge((14.6407, 121.0748), max_distance_m=60)["way_id"]
        status, saved = app.create_rating_response(way, {"rating": 2})
        self.assertEqual(status, 200)
        status, changed = app.create_rating_response(way, {"rating": 4, "token": saved["token"]})
        self.assertEqual((status, changed["token"]), (200, saved["token"]))
        self.assertEqual(self.store.rating_stats([way]), {way: (1, 4.0)})
        self.assertEqual(app.create_rating_removal_response(way, {"token": "nope"})[0], 404)
        self.assertEqual(app.create_rating_removal_response(way, {})[0], 400)
        self.assertEqual(app.create_rating_removal_response(way, {"token": saved["token"]})[0], 200)
        self.assertEqual(self.store.rating_stats([way]), {})

    def test_saved_records_keep_the_date_only(self):
        """No time of day, so ratings from one walk cannot be lined up into a trip (PRD C-04)."""
        import sqlite3
        self.store.add_rating(1001, 4)
        self.store.set_covered("1001:1-2", True)
        with sqlite3.connect(self.path) as connection:
            stamps = [row[0] for table in ("ratings", "covered_marks") for row in connection.execute(f"SELECT created_at FROM {table}")]
        self.assertEqual(len(stamps), 2)
        for stamp in stamps:
            self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}$")

    def test_rating_must_be_whole_number_one_to_five(self):
        for bad in (0, 6, 3.5, "4", None, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.store.add_rating(1001, bad)


class WalkabilityTests(TempStoreCase):
    def test_street_shows_not_enough_ratings_below_three(self):
        self.assertEqual(street_score(2, 4.5)["status"], "not enough ratings")
        self.assertIsNone(street_score(2, 4.5)["average"])
        self.assertEqual(street_score(3, 4.0), {"status": "rated", "rating_count": 3, "average": 4.0})

    def test_route_score_is_length_weighted_over_rated_streets(self):
        edges = [{"way_id": 1, "length_m": 100}, {"way_id": 2, "length_m": 300}, {"way_id": 3, "length_m": 100}]
        stats = {1: (3, 5.0), 2: (4, 3.0), 3: (2, 1.0)}  # street 3 has too few ratings
        result = route_walkability(edges, stats)
        self.assertAlmostEqual(result["score"], (5 * 100 + 3 * 300) / 400, places=2)
        self.assertEqual(result["rated_share_percent"], 80.0)
        self.assertEqual(result["basis"], "user ratings")

    def test_ratings_endpoint_and_route_walkability(self):
        before = self.route()
        way_id = before["routes"][0]["edges"][0]["way_id"]
        for rating in (5, 4, 3):
            status, street = app.create_rating_response(way_id, {"rating": rating})
            self.assertEqual(status, 200)
        self.assertEqual(street["walkability"]["average"], 4.0)
        after = self.route()
        self.assertIsNotNone(after["routes"][0]["walkability"]["score"])
        self.assertGreater(after["routes"][0]["walkability"]["rated_share_percent"], 0)
        # Ratings never change which routes are shown or any sun figure (S-09, C-02).
        strip = lambda response: [{k: v for k, v in route.items() if k != "walkability"} for route in response["routes"]]
        self.assertEqual(strip(before), strip(after))

    def test_rating_unknown_street_is_rejected(self):
        self.assertEqual(app.create_rating_response(999999999999, {"rating": 3})[0], 404)
        street = app.WALKING_GRAPH.nearest_edge((14.6407, 121.0748), max_distance_m=60)
        self.assertEqual(app.create_rating_response(street["way_id"], {"rating": 9})[0], 400)


class CoveredTests(TempStoreCase):
    def test_marking_a_sunny_section_covered_lowers_sun_by_its_share_and_removal_restores(self):
        before = self.route()
        route = before["routes"][0]
        # Find an edge that is entirely in direct sun at this time.
        model = app.ExposureModel(app.HEIGHT_RASTER, TRIP["travel_time"], *app.STUDY_CENTER)
        target = None
        for index, edge in enumerate(route["edges"]):
            pieces = model.segment_pieces(route["geometry"][index], route["geometry"][index + 1])
            if edge["length_m"] > 10 and all(piece["label"] == "sun" for piece in pieces):
                target = edge
                break
        self.assertIsNotNone(target, "test route needs a fully sunny edge")

        status, marked = app.create_covered_update_response(target["edge_key"], True)
        self.assertEqual((status, marked["covered"]), (200, True))
        after = self.route()
        same = next(candidate for candidate in after["routes"] if candidate["id"] == route["id"])
        # The shortest route depends on distance only, so marking a section covered cannot move it.
        self.assertEqual(same["geometry"], route["geometry"])
        drop = route["exposure"]["sun_percent"] - same["exposure"]["sun_percent"]
        self.assertAlmostEqual(drop, target["length_m"] / route["distance_m"] * 100, delta=0.3)
        self.assertIn("covered", [section["label"] for section in same["exposure"]["sections"]])
        self.assertAlmostEqual(route["exposure"]["sun_minutes"] - same["exposure"]["sun_minutes"], target["length_m"] / 80, delta=0.15)

        app.create_covered_update_response(target["edge_key"], False)
        restored = self.route()
        self.assertEqual(restored["routes"][0]["exposure"], route["exposure"])

    def test_covered_list_returns_geometry(self):
        key = app.WALKING_GRAPH.nearest_edge((14.6407, 121.0748), max_distance_m=60)["edge_key"]
        app.create_covered_update_response(key, True)
        status, response = app.create_covered_list_response()
        self.assertEqual(status, 200)
        self.assertEqual(response["covered"][0]["edge_key"], key)
        self.assertEqual(len(response["covered"][0]["geometry"]), 2)

    def test_unknown_edge_is_rejected(self):
        self.assertEqual(app.create_covered_update_response("1:2-3", True)[0], 404)
        self.assertEqual(app.create_covered_update_response("garbage", True)[0], 404)

    def test_nearest_street_to_a_tap(self):
        status, response = app.create_nearest_street_response({"latitude": 14.6407, "longitude": 121.0748})
        self.assertEqual(status, 200)
        self.assertIn("edge_key", response["section"])
        self.assertIsInstance(response["named"], bool)
        self.assertFalse(response["section"]["covered"])
        self.assertEqual(response["walkability"]["status"], "not enough ratings")


if __name__ == "__main__":
    unittest.main()
