import random
import unittest
from unittest.mock import patch

import app
from routing import haversine_meters
from shade import ExposureModel

TRAVEL_TIME = "2026-10-15T15:00:00+08:00"


def sample_pairs(count=10, seed=189):
    """Node pairs inside the study area, 300 m to 1.5 km apart, that are connected."""
    graph = app.WALKING_GRAPH
    rng = random.Random(seed)
    nodes = sorted(node for node in graph.edges if app.is_in_study_area(*graph.coordinates[node]))
    pairs = []
    while len(pairs) < count:
        first, second = rng.sample(nodes, 2)
        distance = haversine_meters(graph.coordinates[first], graph.coordinates[second])
        if 300 <= distance <= 1500 and graph.route_nodes(first, second):
            pairs.append((first, second))
    return pairs


class AStarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = app.WALKING_GRAPH
        cls.pairs = sample_pairs()
        cls.model = ExposureModel(app.HEIGHT_RASTER, TRAVEL_TIME, *app.STUDY_CENTER)

    def test_astar_matches_dijkstra_for_shortest_distance(self):
        for first, second in self.pairs:
            astar = self.graph.route_nodes(first, second)
            dijkstra = self.graph.route_nodes(first, second, use_heuristic=False)
            self.assertAlmostEqual(self.graph.path_cost(astar), self.graph.path_cost(dijkstra), places=6)

    def test_astar_matches_dijkstra_for_shade_weighted_cost(self):
        cost = app.exposure_cost(self.model, set())
        for first, second in self.pairs:
            astar = self.graph.route_nodes(first, second, cost)
            dijkstra = self.graph.route_nodes(first, second, cost, use_heuristic=False)
            self.assertAlmostEqual(self.graph.path_cost(astar, cost), self.graph.path_cost(dijkstra, cost), places=6)

    def test_routes_do_not_pass_through_enclosed_buildings(self):
        """PRD C-01: no edge on a route runs through an enclosed ground-level building."""
        buildings = app.ENCLOSED_BUILDINGS
        cost = app.exposure_cost(self.model, set())
        for first, second in self.pairs:
            for path in (self.graph.route_nodes(first, second), self.graph.route_nodes(first, second, cost)):
                for a, b in zip(path, path[1:]):
                    (lat_a, lon_a), (lat_b, lon_b) = self.graph.coordinates[a], self.graph.coordinates[b]
                    passage = any(way.tags.get("tunnel") == "building_passage" for way in app.OSM_DATA.ways if way.way_id == self.graph.edge_ways[(a, b)])
                    if passage:
                        continue
                    for fraction in (0.25, 0.5, 0.75):
                        self.assertFalse(buildings.contains(lat_a + (lat_b - lat_a) * fraction, lon_a + (lon_b - lon_a) * fraction))

    def test_open_roofs_and_raised_buildings_are_not_obstacles(self):
        from osm import is_enclosed_ground_building
        self.assertFalse(is_enclosed_ground_building({"building": "roof"}))
        self.assertFalse(is_enclosed_ground_building({"building": "yes", "layer": "1"}))
        self.assertTrue(is_enclosed_ground_building({"building": "retail"}))
        self.assertTrue(is_enclosed_ground_building({"building": "yes", "layer": "0"}))

    def test_shade_cost_is_never_below_length(self):
        cost = app.exposure_cost(self.model, set())
        for first, second in self.pairs[:3]:
            path = self.graph.route_nodes(first, second)
            for a, b in zip(path, path[1:]):
                self.assertGreaterEqual(cost(a, b, self.graph.edges[a][b]), self.graph.edges[a][b] - 1e-9)


@patch("app.fetch_weather", return_value={})
class RouteResponseTests(unittest.TestCase):
    def request(self, first, second, travel_time=TRAVEL_TIME):
        graph = app.WALKING_GRAPH
        start = dict(zip(("latitude", "longitude"), graph.coordinates[first]))
        destination = dict(zip(("latitude", "longitude"), graph.coordinates[second]))
        return app.create_route_response({"start": start, "destination": destination, "travel_time": travel_time})

    def test_every_trip_returns_a_route_with_sun_information(self, _weather):
        for first, second in sample_pairs():
            status, response = self.request(first, second)
            self.assertEqual(status, 200)
            for route in response["routes"]:
                self.assertIn("sun_percent", route["exposure"])
                self.assertIn("sun_minutes", route["exposure"])
                self.assertGreater(route["distance_m"], 0)

    def test_shortest_and_shadier_relationship_and_comparison(self, _weather):
        compared = 0
        for first, second in sample_pairs():
            _, response = self.request(first, second)
            routes = response["routes"]
            if len(routes) == 1:
                self.assertIsNone(response["comparison"])
                self.assertTrue(response["alternative_note"])
                continue
            compared += 1
            shortest, shadier = routes
            self.assertEqual((shortest["id"], shadier["id"]), ("shortest", "shadier"))
            self.assertLessEqual(shortest["distance_m"], shadier["distance_m"] + 0.05)
            self.assertLess(shadier["exposure"]["sun_percent"], shortest["exposure"]["sun_percent"])
            comparison = response["comparison"]
            self.assertAlmostEqual(comparison["sun_percent_points_less"],
                                   shortest["exposure"]["sun_percent"] - shadier["exposure"]["sun_percent"], delta=0.051)
            self.assertAlmostEqual(comparison["sun_minutes_less"],
                                   shortest["exposure"]["sun_minutes"] - shadier["exposure"]["sun_minutes"], delta=0.051)
            self.assertAlmostEqual(comparison["extra_distance_m"], shadier["distance_m"] - shortest["distance_m"], delta=0.051)
        self.assertGreater(compared, 0, "expected at least one trip with a shadier alternative")

    def test_route_figures_follow_section_lengths(self, _weather):
        first, second = sample_pairs(1)[0]
        _, response = self.request(first, second)
        for route in response["routes"]:
            sections = route["exposure"]["sections"]
            total = sum(section["length_m"] for section in sections)
            exposed = sum(section["length_m"] for section in sections if section["label"] in {"sun", "unknown"})
            self.assertAlmostEqual(total, route["distance_m"], delta=max(1.0, total * 0.002))
            self.assertAlmostEqual(route["exposure"]["sun_percent"], exposed / total * 100, delta=0.2)
            self.assertAlmostEqual(route["exposure"]["sun_minutes"], exposed / 80, delta=0.1)
            self.assertAlmostEqual(route["duration_minutes"], route["distance_m"] / 80, delta=0.05)

    def test_time_of_day_changes_exposure(self, _weather):
        changed = False
        for first, second in sample_pairs(5):
            morning = self.request(first, second, "2026-10-15T09:00:00+08:00")[1]["routes"][0]["exposure"]["sun_percent"]
            afternoon = self.request(first, second, "2026-10-15T15:00:00+08:00")[1]["routes"][0]["exposure"]["sun_percent"]
            changed = changed or morning != afternoon
        self.assertTrue(changed)


if __name__ == "__main__":
    unittest.main()
