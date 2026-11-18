import unittest
from unittest.mock import patch

from app import ASSUMPTIONS, STUDY_AREA, create_route_response, is_in_study_area
from weather import build_weather

ADMU = {"latitude": 14.6407, "longitude": 121.0748}
NEARBY = {"latitude": 14.6378, "longitude": 121.0776}


class RouteApiTests(unittest.TestCase):
    def test_katipunan_bounds_accept_admu_and_reject_outside_points(self):
        self.assertTrue(is_in_study_area(14.6407, 121.0748))
        self.assertFalse(is_in_study_area(14.3000, 121.0748))

    @patch("app.fetch_weather")
    def test_route_request_returns_routes_and_weather_context(self, fetch_weather):
        fetch_weather.return_value = build_weather(8.2, 32.0, 70.0)
        status, response = create_route_response(
            {"start": ADMU, "destination": NEARBY, "travel_time": "2026-10-15T12:00:00+08:00"}
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["study_area"], STUDY_AREA)
        self.assertGreaterEqual(len(response["routes"]), 1)
        route = response["routes"][0]
        self.assertGreater(route["distance_m"], 0)
        self.assertEqual(route["exposure"]["status"], "computed")
        for key in ("sun_percent", "sun_minutes", "unknown_percent", "sections"):
            self.assertIn(key, route["exposure"])
        self.assertEqual(len(route["comfort_window"]["times"]), 3)
        self.assertEqual(response["weather"]["uv"]["category"], "Very high")
        self.assertEqual(response["assumptions"], ASSUMPTIONS)
        fetch_weather.assert_called_once()

    def test_route_request_rejects_points_outside_study_area(self):
        for field in ("start", "destination"):
            payload = {"start": ADMU, "destination": NEARBY, field: {"latitude": 14.3000, "longitude": 121.0748}}
            status, response = create_route_response(payload)
            self.assertEqual(status, 400)
            self.assertIn("outside", response["error"])
            self.assertNotIn("routes", response)

    def test_invalid_travel_time_is_rejected(self):
        status, response = create_route_response({"start": ADMU, "destination": NEARBY, "travel_time": "noon-ish"})
        self.assertEqual(status, 400)

    @patch("app.fetch_weather", return_value=build_weather(None, None, None))
    def test_same_start_and_destination_gives_message_not_crash(self, _weather):
        status, response = create_route_response({"start": ADMU, "destination": ADMU})
        self.assertEqual(status, 422)
        self.assertIn("Choose points", response["error"])

    @patch("app.fetch_weather", return_value=build_weather(None, None, None))
    def test_missing_travel_time_defaults_to_now(self, _weather):
        status, response = create_route_response({"start": ADMU, "destination": NEARBY})
        self.assertEqual(status, 200)
        self.assertTrue(response["travel_time"])


if __name__ == "__main__":
    unittest.main()
