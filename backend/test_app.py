import unittest
from unittest.mock import patch

from app import STUDY_AREA, create_route_response, is_in_study_area


class RouteApiTests(unittest.TestCase):
    def test_katipunan_bounds_accept_admu_and_reject_outside_points(self):
        self.assertTrue(is_in_study_area(14.6407, 121.0748))
        self.assertFalse(is_in_study_area(14.6000, 121.0748))

    @patch("app.fetch_uv_context")
    def test_route_request_returns_routes_and_uv_context(self, fetch_uv):
        fetch_uv.return_value = {
            "status": "available",
            "index": 8.2,
            "category": "Very high",
            "source": "Open-Meteo",
        }
        status, response = create_route_response(
            {
                "start": {"latitude": 14.6407, "longitude": 121.0748},
                "destination": {"latitude": 14.6378, "longitude": 121.0776},
                "travel_time": "2026-10-15T12:00:00+08:00",
            }
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["study_area"], STUDY_AREA)
        self.assertEqual(response["data_status"], "walking_network_loaded")
        self.assertGreaterEqual(len(response["routes"]), 1)
        self.assertGreater(response["routes"][0]["distance_m"], 0)
        self.assertEqual(response["routes"][0]["exposure"]["status"], "computed")
        self.assertEqual(response["uv_context"]["category"], "Very high")
        fetch_uv.assert_called_once()

    def test_route_request_rejects_points_outside_study_area(self):
        status, response = create_route_response(
            {
                "start": {"latitude": 14.6000, "longitude": 121.0748},
                "destination": {"latitude": 14.6378, "longitude": 121.0776},
            }
        )

        self.assertEqual(status, 400)
        self.assertIn("study area", response["error"])


if __name__ == "__main__":
    unittest.main()