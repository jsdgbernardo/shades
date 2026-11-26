"""Walk, train, walk option (PRD F-16 to F-19, C-07; stretch), on the committed rail and map data."""

import unittest
from unittest.mock import patch

import app
from rail import RIDE_SPEED_M_PER_MIN, TRANSFER_MINUTES, RailNetwork
from shade import WALKING_SPEED_M_PER_MIN, analyze_route, shift_time

TIME = "2026-11-27T10:00:00+08:00"

# The PRD's 6 test trips (F-16 method): 4 with a qualifying option, 2 of them needing a transfer,
# and 2 with no station within 1 km.
WITH_OPTION = {
    "Katipunan -> Ortigas (transfer)": ((14.6330, 121.0745), (14.5878, 121.0567)),
    "Katipunan -> Ayala (transfer, over 10 km)": ((14.6330, 121.0745), (14.5495, 121.0273)),
    "Recto -> Vito Cruz": ((14.6040, 120.9845), (14.5635, 120.9950)),
    "Katipunan -> Gilmore": ((14.6330, 121.0745), (14.6135, 121.0345)),
}
WITHOUT_OPTION = {
    "Ateneo -> UP Diliman": ((14.6407, 121.0748), (14.6537, 121.0685)),
    "BGC short walk": ((14.5509, 121.0480), (14.5560, 121.0520)),
}


def request(start, destination, when=TIME):
    return app.create_route_response({
        "start": {"latitude": start[0], "longitude": start[1]},
        "destination": {"latitude": destination[0], "longitude": destination[1]},
        "travel_time": when,
    })


class RailNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rail = RailNetwork()

    def test_rides_follow_the_lines_and_transfers(self):
        ride = self.rail.ride("lrt2:katipunan", "lrt2:araneta-center-cubao")
        self.assertEqual(ride.transfers, [])
        self.assertEqual([segment["line"] for segment in ride.segments], ["lrt2"])
        ride = self.rail.ride("lrt2:katipunan", "mrt3:ayala")
        self.assertEqual([segment["line"] for segment in ride.segments], ["lrt2", "mrt3"])
        self.assertEqual([transfer["from"] for transfer in ride.transfers], ["Araneta Center - Cubao"])
        ride = self.rail.ride("lrt2:katipunan", "lrt1:vito-cruz")
        self.assertEqual([transfer["to"] for transfer in ride.transfers], ["Doroteo Jose"])

    def test_ride_time_is_distance_at_the_fixed_speed_plus_transfers(self):
        """F-18 arithmetic."""
        ride = self.rail.ride("lrt2:katipunan", "mrt3:ayala")
        self.assertAlmostEqual(ride.minutes, ride.distance_m / RIDE_SPEED_M_PER_MIN + TRANSFER_MINUTES * 1)
        self.assertAlmostEqual(RIDE_SPEED_M_PER_MIN, 400.0)

    def test_no_ride_that_is_only_or_starts_with_a_transfer(self):
        self.assertIsNone(self.rail.ride("lrt2:araneta-center-cubao", "mrt3:araneta-center-cubao"))
        self.assertIsNone(self.rail.ride("lrt2:recto", "lrt1:vito-cruz"))  # board at Doroteo Jose instead
        self.assertIsNone(self.rail.ride("lrt2:katipunan", "lrt2:katipunan"))

    def test_ride_shape_runs_from_boarding_to_alighting(self):
        ride = self.rail.ride("lrt2:katipunan", "lrt2:araneta-center-cubao")
        start, end = ride.segments[0]["geometry"][0], ride.segments[0]["geometry"][-1]
        katipunan, cubao = self.rail.stations["lrt2:katipunan"], self.rail.stations["lrt2:araneta-center-cubao"]
        self.assertLess(abs(start[1] - katipunan.lat) + abs(start[0] - katipunan.lon), 0.002)
        self.assertLess(abs(end[1] - cubao.lat) + abs(end[0] - cubao.lon), 0.002)


@patch("app.fetch_weather", return_value={})
@patch("app.covered_edges_provider", return_value=set())
class TrainOptionTests(unittest.TestCase):
    def test_trips_with_a_qualifying_option_show_it(self, *_mocks):
        for name, (start, destination) in WITH_OPTION.items():
            with self.subTest(name):
                status, response = request(start, destination)
                self.assertEqual(status, 200)
                train = [route for route in response["routes"] if route.get("kind") == "train"]
                self.assertEqual(len(train), 1)
                legs = train[0]["legs"]
                self.assertEqual([leg["type"] for leg in legs], ["walk", "ride", "walk"])
                self.assertLessEqual(legs[0]["distance_m"], app.TRAIN_WALK_MAX_M)
                self.assertLessEqual(legs[2]["distance_m"], app.TRAIN_WALK_MAX_M)
                self.assertTrue(legs[1]["from"] and legs[1]["to"])

    def test_two_of_the_trips_need_a_transfer(self, *_mocks):
        with_transfer = 0
        for start, destination in WITH_OPTION.values():
            route = next(r for r in request(start, destination)[1]["routes"] if r.get("kind") == "train")
            with_transfer += bool(route["legs"][1]["transfers"])
        self.assertGreaterEqual(with_transfer, 2)

    def test_trips_without_an_option_show_none_and_no_error(self, *_mocks):
        for name, (start, destination) in WITHOUT_OPTION.items():
            with self.subTest(name):
                status, response = request(start, destination)
                self.assertEqual(status, 200)
                self.assertFalse(any(route.get("kind") == "train" for route in response["routes"]))

    def test_the_chosen_option_has_the_fewest_minutes_in_sun(self, *_mocks):
        """F-16 method: every qualifying pair worked out separately; the shown one is the lowest."""
        for name, (start, destination) in WITH_OPTION.items():
            with self.subTest(name):
                start_node, end_node = app.WALKING_GRAPH.nearest_node(start), app.WALKING_GRAPH.nearest_node(destination)
                options = app.train_candidates(start_node, end_node, TIME, set(), app._Models())
                self.assertTrue(options)
                recomputed = []
                for option in options:
                    first, second = option["walks"]
                    # Recompute each walk's sun minutes on its own at its own time.
                    one = analyze_route(first["geometry"], TIME, app.HEIGHT_RASTER)
                    reach = shift_time(TIME, round(first["duration_minutes"] + option["ride"].minutes))
                    two = analyze_route(second["geometry"], reach, app.HEIGHT_RASTER)
                    total = first["duration_minutes"] + option["ride"].minutes + second["duration_minutes"]
                    recomputed.append((round(one["sun_minutes"] + two["sun_minutes"], 1), round(total, 1), option["alighting"].name, option["boarding"].name))
                shown = next(r for r in request(start, destination)[1]["routes"] if r.get("kind") == "train")
                best = min(recomputed)
                self.assertAlmostEqual(shown["exposure"]["sun_minutes"], best[0], delta=0.15)
                self.assertEqual(shown["summary"], f"{best[3]} → {best[2]}")

    def test_figures_count_the_walks_only_and_total_adds_the_ride(self, *_mocks):
        """F-17 and F-18 by hand."""
        route = next(r for r in request(*WITH_OPTION["Katipunan -> Ortigas (transfer)"])[1]["routes"] if r.get("kind") == "train")
        first, ride, second = route["legs"]
        walking = first["distance_m"] + second["distance_m"]
        self.assertAlmostEqual(route["distance_m"], walking, delta=0.2)
        self.assertAlmostEqual(route["duration_minutes"], walking / WALKING_SPEED_M_PER_MIN, delta=0.1)
        sun = first["exposure"]["sun_length_m"] + second["exposure"]["sun_length_m"]
        self.assertAlmostEqual(route["exposure"]["sun_percent"], sun / walking * 100, delta=0.15)
        ride_distance = sum(segment["distance_m"] for segment in ride["segments"])
        expected_total = first["duration_minutes"] + ride_distance / RIDE_SPEED_M_PER_MIN + TRANSFER_MINUTES * len(ride["transfers"]) + second["duration_minutes"]
        self.assertAlmostEqual(route["total_minutes"], expected_total, delta=0.3)
        self.assertTrue(route["total_is_estimate"])
        # Walking routes show a total time equal to their walking time.
        for walking_route in request(*WITH_OPTION["Katipunan -> Ortigas (transfer)"])[1]["routes"]:
            if walking_route.get("kind") != "train":
                self.assertEqual(walking_route["total_minutes"], walking_route["duration_minutes"])

    def test_second_walk_is_scored_later_and_marked_approximate(self, *_mocks):
        """F-19: the second walk at the chosen time + first walk + ride."""
        route = next(r for r in request(*WITH_OPTION["Katipunan -> Ortigas (transfer)"])[1]["routes"] if r.get("kind") == "train")
        first, ride, second = route["legs"]
        expected = shift_time(TIME, round(first["duration_minutes"] + route["total_minutes"] - first["duration_minutes"] - second["duration_minutes"]))
        self.assertEqual(second["time"], expected)
        self.assertNotEqual(second["time"], first["time"])
        self.assertTrue(second["approximate"])
        self.assertTrue(route["exposure"]["second_walk_approximate"])
        self.assertTrue(all(section.get("approximate") for section in route["exposure"]["sections"][-len(second["exposure"]["sections"]):]))

    def test_no_schedule_fare_or_status_data_and_notes_say_so(self, *_mocks):
        """C-07."""
        status, response = request(*WITH_OPTION["Katipunan -> Ortigas (transfer)"])

        def keys(value):
            if isinstance(value, dict):
                for key, inner in value.items():
                    yield key.lower()
                    yield from keys(inner)
            elif isinstance(value, list):
                for inner in value:
                    yield from keys(inner)

        # No field carries schedule, fare, delay, crowding or status data (the notes may name them).
        for key in keys(response["routes"]):
            for word in ("fare", "schedule", "delay", "crowd", "status_of_service", "headway"):
                self.assertNotIn(word, key)
        # F-17: no separate ride distance, ride time or transfer time figure on the route itself.
        train = next(r for r in response["routes"] if r.get("kind") == "train")
        for key in ("ride_minutes", "ride_distance_m", "transfer_minutes"):
            self.assertNotIn(key, train)
        notes = " ".join(response["assumptions"]["train_notes"]).lower()
        self.assertIn("estimate", notes)
        self.assertIn("service status", notes)

    def test_over_10_km_shows_only_the_train_or_the_old_message(self, *_mocks):
        status, response = request(*WITH_OPTION["Katipunan -> Ayala (transfer, over 10 km)"])
        self.assertEqual(status, 200)
        self.assertEqual([route["id"] for route in response["routes"]], ["train"])
        status, response = request((14.6407, 121.0748), (14.5400, 121.0200))
        if status != 200:
            self.assertIn("Too far", response["error"])


if __name__ == "__main__":
    unittest.main()
