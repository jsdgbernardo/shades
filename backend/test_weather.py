import json
import unittest
from io import BytesIO
from unittest.mock import patch

import app
import weather
from weather import build_weather, fetch_weather, heat_index_c


def f_to_c(value):
    return (value - 32) * 5 / 9


class HeatIndexTests(unittest.TestCase):
    def test_matches_nws_heat_index_table(self):
        # (temperature F, relative humidity %, NWS heat index chart value F)
        for temperature_f, humidity, expected_f in [(90, 70, 106), (96, 65, 121), (86, 90, 105), (100, 40, 109), (80, 40, 80)]:
            with self.subTest(temperature_f=temperature_f, humidity=humidity):
                self.assertAlmostEqual(heat_index_c(f_to_c(temperature_f), humidity), f_to_c(expected_f), delta=f_to_c(33.5) - f_to_c(32))

    def test_missing_input_gives_no_heat_index(self):
        self.assertIsNone(heat_index_c(None, 70))
        self.assertIsNone(heat_index_c(32, None))


class AvailabilityTests(unittest.TestCase):
    def test_each_reading_is_available_or_not_on_its_own(self):
        result = build_weather(None, 31.0, None)
        self.assertEqual(result["uv"], {"status": "not available"})
        self.assertEqual(result["temperature_c"], {"status": "available", "value": 31.0})
        self.assertEqual(result["humidity_percent"], {"status": "not available"})
        self.assertEqual(result["heat_index_c"], {"status": "not available"})

    def test_uv_category_is_reported(self):
        self.assertEqual(build_weather(8.2, 33, 60)["uv"]["category"], "Very high")
        self.assertEqual(build_weather(6.5, 33, 60)["uv"]["category"], "High")

    def test_network_failure_gives_not_available_for_all(self):
        weather._CACHE.clear()
        with patch("weather.urlopen", side_effect=OSError("offline")):
            result = fetch_weather(14.64, 121.07, "2026-10-15T12:00:00+08:00")
        for key in ("uv", "temperature_c", "humidity_percent", "heat_index_c"):
            self.assertEqual(result[key]["status"], "not available")

    def test_reads_values_for_the_selected_hour(self):
        weather._CACHE.clear()
        payload = {"hourly": {
            "time": ["2026-10-15T11:00", "2026-10-15T12:00"],
            "uv_index": [7.0, 9.1],
            "temperature_2m": [30.0, 32.4],
            "relative_humidity_2m": [70, None],
        }}
        with patch("weather.urlopen", return_value=BytesIO(json.dumps(payload).encode())):
            result = fetch_weather(14.64, 121.07, "2026-10-15T12:20:00+08:00")
        self.assertEqual(result["uv"]["value"], 9.1)
        self.assertEqual(result["temperature_c"]["value"], 32.4)
        self.assertEqual(result["humidity_percent"]["status"], "not available")
        self.assertEqual(result["heat_index_c"]["status"], "not available")


class ContextOnlyTests(unittest.TestCase):
    """PRD F-07, F-10, F-11, F-12: weather never changes routes or scores, and never blocks them."""

    PAYLOAD = {
        "start": {"latitude": 14.6407, "longitude": 121.0748},
        "destination": {"latitude": 14.6378, "longitude": 121.0776},
        "travel_time": "2026-10-15T12:00:00+08:00",
    }

    def routes_with(self, weather_value):
        with patch("app.fetch_weather", return_value=weather_value):
            status, response = app.create_route_response(self.PAYLOAD)
        self.assertEqual(status, 200)
        return response

    def test_different_weather_values_leave_routes_unchanged(self):
        mild = self.routes_with(build_weather(2.0, 26.0, 50.0))
        harsh = self.routes_with(build_weather(11.5, 35.0, 85.0))
        self.assertNotEqual(mild["weather"], harsh["weather"])
        self.assertEqual(mild["routes"], harsh["routes"])
        self.assertEqual(mild["comparison"], harsh["comparison"])

    def test_route_succeeds_when_each_reading_is_missing(self):
        for missing in ("uv", "temperature", "humidity", "all"):
            with self.subTest(missing=missing):
                values = {"uv": 8.0, "temperature": 32.0, "humidity": 70.0}
                if missing == "all":
                    values = dict.fromkeys(values)
                else:
                    values[missing] = None
                response = self.routes_with(build_weather(values["uv"], values["temperature"], values["humidity"]))
                self.assertGreaterEqual(len(response["routes"]), 1)


if __name__ == "__main__":
    unittest.main()
