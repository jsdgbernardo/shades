import unittest
from unittest.mock import patch

import app
from weather import build_weather


class PlaceSearchTests(unittest.TestCase):
    def test_finds_known_campus_places_inside_study_area(self):
        status, response = app.create_places_response({"q": ["rizal"]})
        self.assertEqual(status, 200)
        names = [place["name"] for place in response["places"]]
        self.assertIn("Rizal Library", names)
        for place in response["places"]:
            self.assertTrue(app.is_in_study_area(place["latitude"], place["longitude"]))

    def test_prefix_matches_rank_first_and_names_are_unique(self):
        places = app.PLACE_INDEX.search("katip")
        self.assertTrue(places[0]["name"].lower().startswith("katip"))
        names = [place["name"].casefold() for place in app.PLACE_INDEX.places]
        self.assertEqual(len(names), len(set(names)))

    def test_short_or_empty_query_returns_nothing(self):
        self.assertEqual(app.create_places_response({"q": ["r"]})[1]["places"], [])
        self.assertEqual(app.create_places_response({})[1]["places"], [])

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
