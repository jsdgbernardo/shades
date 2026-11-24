import unittest
from unittest.mock import patch

import app
from weather import build_weather


class PlaceSearchTests(unittest.TestCase):
    def test_finds_known_campus_places_inside_study_area(self):
        status, response = app.create_places_response({"q": "rizal"})
        self.assertEqual(status, 200)
        names = [place["name"] for place in response["places"]]
        self.assertIn("Rizal Library", names)
        for place in response["places"]:
            self.assertTrue(app.is_in_study_area(place["latitude"], place["longitude"]))

    def test_prefix_matches_rank_first(self):
        places = app.PLACE_INDEX.search("katip")
        self.assertTrue(places[0]["name"].lower().startswith("katip"))

    def test_finds_places_across_metro_manila(self):
        """The index covers Metro Manila, not just Katipunan."""
        for query, south, north, west, east in [
            ("Greenbelt", 14.545, 14.560, 121.010, 121.030),         # Makati
            ("Bonifacio High Street", 14.545, 14.560, 121.040, 121.060),  # BGC
            ("Rizal Park", 14.575, 14.590, 120.970, 120.990),          # Manila
        ]:
            with self.subTest(query=query):
                places = app.PLACE_INDEX.search(query)
                self.assertTrue(places, f"no results for {query}")
                self.assertTrue(any(south <= p["latitude"] <= north and west <= p["longitude"] <= east for p in places),
                                f"{query} not found in the expected area: {places[:3]}")

    def test_near_ranks_the_closest_branch_first(self):
        katipunan, makati = (14.6400, 121.0750), (14.5540, 121.0240)
        near_katipunan = app.PLACE_INDEX.search("7-Eleven", near=katipunan)
        near_makati = app.PLACE_INDEX.search("7-Eleven", near=makati)
        self.assertTrue(near_katipunan and near_makati)
        def distance(place, point):
            return abs(place["latitude"] - point[0]) + abs(place["longitude"] - point[1])
        self.assertLess(distance(near_katipunan[0], katipunan), distance(near_makati[0], katipunan))
        self.assertLess(distance(near_makati[0], makati), distance(near_katipunan[0], makati))
        status, response = app.create_places_response({"q": "7-Eleven", "near": {"latitude": 14.6400, "longitude": 121.0750}})
        self.assertEqual((status, response["places"][0]["id"]), (200, near_katipunan[0]["id"]))

    def test_short_or_empty_query_returns_nothing(self):
        self.assertEqual(app.create_places_response({"q": "r"})[1]["places"], [])
        self.assertEqual(app.create_places_response({})[1]["places"], [])

    def test_malformed_input_is_safe(self):
        for payload in (None, [], {"q": None}, {"q": ["rizal"], "near": "14.64,121.07"}, {"q": 5}):
            with self.subTest(payload=payload):
                self.assertEqual(app.create_places_response(payload)[0], 200)
        status, response = app.create_places_response({"q": "rizal", "near": {"latitude": float("nan"), "longitude": 121.07}})
        self.assertEqual((status, response["places"][0]["name"]), (200, "Rizal Library"))

    def test_place_can_be_used_as_a_route_destination(self):
        place = app.PLACE_INDEX.search("Rizal Library")[0]
        with patch("app.fetch_weather", return_value=build_weather(None, None, None)):
            status, response = app.create_route_response({
                "start": {"latitude": 14.6378, "longitude": 121.0776},
                "destination": {"latitude": place["latitude"], "longitude": place["longitude"]},
            })
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(response["routes"]), 1)


class WeatherEndpointTests(unittest.TestCase):
    @patch("app.fetch_weather", return_value=build_weather(5.0, 31.0, 75.0))
    def test_weather_for_time(self, _fetch):
        status, response = app.create_weather_response({"time": ["2026-10-15T12:00:00+08:00"]})
        self.assertEqual(status, 200)
        self.assertEqual(response["weather"]["temperature_c"]["value"], 31.0)
        self.assertEqual(response["weather"]["heat_index_c"]["status"], "available")

    def test_invalid_time_is_rejected(self):
        self.assertEqual(app.create_weather_response({"time": ["soon"]})[0], 400)


if __name__ == "__main__":
    unittest.main()
