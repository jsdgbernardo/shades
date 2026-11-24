import random
import unittest
from unittest.mock import patch

import app
from routing import WalkingGraph, haversine_meters
from shade import ExposureModel
from tiles import TileStore

TRAVEL_TIME = "2026-10-15T15:00:00+08:00"


# Around Katipunan / Ateneo, inside the building-height raster.
KATIPUNAN = (14.632, 121.060, 14.660, 121.090)


def sample_pairs(count=10, seed=189, box=KATIPUNAN):
    """Connected node pairs 300 m to 1.5 km apart, from seeded random points in `box`."""
    graph = app.WALKING_GRAPH
    rng = random.Random(seed)
    pairs = []
    while len(pairs) < count:
        points = [(rng.uniform(box[0], box[2]), rng.uniform(box[1], box[3])) for _ in range(2)]
        first, second = (graph.nearest_node(point) for point in points)
        if first is None or second is None or first == second:
            continue
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

    def test_build_drops_edges_through_enclosed_buildings(self):
        """PRD C-01: the data build leaves out walking edges through enclosed ground-level buildings."""
        from build_tiles import build_graph
        from osm import FootprintIndex

        d = 0.0003
        building = [(14.6400, 121.0750), (14.6400, 121.0750 + d), (14.6400 + d, 121.0750 + d), (14.6400 + d, 121.0750), (14.6400, 121.0750)]
        enclosed = FootprintIndex([building])
        across = [(1, 14.6400 + d / 2, 121.0745), (2, 14.6400 + d / 2, 121.0760)]   # straight through the building
        beside = [(3, 14.6395, 121.0745), (4, 14.6395, 121.0760)]                   # along its south side
        passage = [(5, 14.6400 + d / 2, 121.0745), (6, 14.6400 + d / 2, 121.0760)]  # mapped building passage
        ways = [
            (101, across, None, False, False, False, "footway"),
            (102, beside, "Side Street", False, False, False, "residential"),
            (103, passage, None, False, False, True, "footway"),
        ]
        tiles, excluded, _ = build_graph(ways, enclosed)
        edges = [edge for tile in tiles.values() for edge in tile["edges"]]
        self.assertEqual(excluded, 1)
        self.assertFalse(any(edge[3] == 101 for edge in edges))
        self.assertTrue(any(edge[3] == 102 for edge in edges))
        self.assertTrue(any(edge[3] == 103 for edge in edges))
        self.assertGreater(self.graph.excluded_indoor_edges, 0, "the real build should have dropped some indoor edges")

    def test_open_roofs_and_raised_buildings_are_not_obstacles(self):
        from osm import is_enclosed_ground_building
        self.assertFalse(is_enclosed_ground_building({"building": "roof"}))
        self.assertFalse(is_enclosed_ground_building({"building": "yes", "layer": "1"}))
        self.assertTrue(is_enclosed_ground_building({"building": "retail"}))
        self.assertTrue(is_enclosed_ground_building({"building": "yes", "layer": "0"}))

    def test_route_edges_say_whether_the_street_has_a_real_name(self):
        generic = {"Footway", "Service", "Residential", "Path", "Steps", "Primary", "Secondary", "Tertiary",
                   "Unclassified", "Living street", "Pedestrian", "Cycleway", "Trunk", "Primary link",
                   "Secondary link", "Tertiary link", "Trunk link"}
        seen_named = seen_unnamed = False
        for first, second in self.pairs:
            for edge in self.graph.path_edges(self.graph.route_nodes(first, second)):
                self.assertEqual(edge["named"], self.graph.is_named(edge["way_id"]))
                if edge["named"]:
                    seen_named = True
                else:
                    seen_unnamed = True
                    self.assertIn(edge["name"], generic)
        # Katipunan Avenue is a real, named street.
        edge = self.graph.nearest_edge((14.6400, 121.0745), max_distance_m=60)
        self.assertIsNotNone(edge)
        self.assertTrue(seen_named and seen_unnamed)

    def test_shade_cost_is_never_below_length(self):
        cost = app.exposure_cost(self.model, set())
        for first, second in self.pairs[:3]:
            path = self.graph.route_nodes(first, second)
            for a, b in zip(path, path[1:]):
                self.assertGreaterEqual(cost(a, b, self.graph.edges[a][b]), self.graph.edges[a][b] - 1e-9)


class TiledGraphTests(unittest.TestCase):
    """The walking graph loads tiles on demand (Metro Manila study area)."""

    def test_route_across_a_tile_boundary(self):
        from area import TILE_DEG, STUDY_AREA, tile_of
        graph = app.WALKING_GRAPH
        # Two points either side of a tile column boundary near Katipunan.
        boundary_lon = STUDY_AREA["west"] + round((121.075 - STUDY_AREA["west"]) / TILE_DEG) * TILE_DEG
        west = graph.nearest_node((14.640, boundary_lon - 0.004))
        east = graph.nearest_node((14.640, boundary_lon + 0.004))
        self.assertNotEqual(tile_of(*graph.coordinates[west]), tile_of(*graph.coordinates[east]))
        path = graph.route_nodes(west, east)
        self.assertGreater(len(path), 2)
        tiles = {tile_of(*graph.coordinates[node]) for node in path}
        self.assertGreaterEqual(len(tiles), 2)

    def test_routes_outside_quezon_city(self):
        """Makati has walking data but no building heights: routes work and count as unknown."""
        with patch("app.fetch_weather", return_value={}):
            status, response = app.create_route_response({
                "start": {"latitude": 14.5534, "longitude": 121.0244},       # Ayala Avenue area
                "destination": {"latitude": 14.5565, "longitude": 121.0296},
                "travel_time": TRAVEL_TIME,
            })
        self.assertEqual(status, 200)
        exposure = response["routes"][0]["exposure"]
        self.assertGreater(exposure["unknown_percent"], 90)
        self.assertGreaterEqual(exposure["sun_percent"], exposure["unknown_percent"])

    def test_trips_over_10_km_are_refused(self):
        status, response = app.create_route_response({
            "start": {"latitude": 14.6407, "longitude": 121.0748},  # Katipunan
            "destination": {"latitude": 14.5400, "longitude": 121.0200},  # ~12.6 km away
        })
        self.assertEqual(status, 422)
        self.assertIn("Too far", response["error"])

    def test_streets_are_found_before_their_tile_is_loaded(self):
        """After a restart nothing is loaded, but saved ratings and marks must still resolve (D-03)."""
        section = app.WALKING_GRAPH.nearest_edge((14.6407, 121.0748), max_distance_m=60)
        fresh = WalkingGraph(TileStore())
        self.assertEqual(fresh.edge_from_key(section["edge_key"]), section)
        fresh = WalkingGraph(TileStore())
        self.assertIn(section["way_id"], fresh.way_names)
        self.assertEqual(fresh.way_name(section["way_id"]), section["name"])
        self.assertNotIn(1, WalkingGraph(TileStore()).way_names)
        self.assertIsNone(WalkingGraph(TileStore()).edge_from_key("1:2-3"))

    def test_search_limit_stops_without_a_path(self):
        graph = app.WALKING_GRAPH
        first, second = sample_pairs(1, seed=11)[0]
        straight = haversine_meters(graph.coordinates[first], graph.coordinates[second])
        self.assertEqual(graph.route_nodes(first, second, max_cost=straight / 2), [])
        self.assertGreater(len(graph.route_nodes(first, second, max_cost=3 * straight + 5000)), 1)

    def test_point_far_from_any_path_gets_a_message(self):
        # Middle of Manila Bay, inside the study box but nowhere near a path.
        status, response = app.create_route_response({
            "start": {"latitude": 14.5500, "longitude": 120.9200},
            "destination": {"latitude": 14.5520, "longitude": 120.9250},
        })
        self.assertEqual(status, 422)
        self.assertIn("no walking path", response["error"])


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
