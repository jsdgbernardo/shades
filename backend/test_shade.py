import math
import unittest
from array import array

from shade import ExposureModel, HeightRaster, analyze_route, distance_meters

ORIGIN_LON = 121.0
ORIGIN_LAT = 14.002
PIXEL = 0.00005  # about 5.4 m
SIZE = 40
POINT = (14.001, 121.001)  # (lat, lon), centre of the grid
METERS_PER_DEG_LON = 111_320 * math.cos(math.radians(POINT[0]))


def make_raster(cells: dict[tuple[float, float], float]) -> HeightRaster:
    """Flat ground (0 m) with the given (lat, lon) -> height cells. A far tall building fixes max_height."""
    values = array("f", [0.0]) * (SIZE * SIZE)
    raster = HeightRaster(SIZE, SIZE, ORIGIN_LON, ORIGIN_LAT, PIXEL, values)
    cells = {**cells, (ORIGIN_LAT - PIXEL / 2, ORIGIN_LON + PIXEL / 2): 20.0}
    for (latitude, longitude), height in cells.items():
        row, column = raster.cell(latitude, longitude)
        values[row * SIZE + column] = height
    return HeightRaster(SIZE, SIZE, ORIGIN_LON, ORIGIN_LAT, PIXEL, values)


def east_of(meters: float) -> tuple[float, float]:
    return POINT[0], POINT[1] + meters / METERS_PER_DEG_LON


def model_with_sun(raster: HeightRaster, elevation: float, azimuth: float) -> ExposureModel:
    model = ExposureModel(raster, "2026-10-15T12:00:00+08:00", POINT[0], POINT[1])
    model.elevation = elevation
    model.azimuth = azimuth
    return model


class ClassifyPointTests(unittest.TestCase):
    def test_building_toward_the_sun_shades_the_point(self):
        raster = make_raster({east_of(10): 20.0})
        label, detail = model_with_sun(raster, 45, 90).classify_point(*POINT)
        self.assertEqual(label, "shaded")
        self.assertEqual(detail["cause"], "building")

    def test_building_away_from_the_sun_does_not_shade(self):
        raster = make_raster({east_of(10): 20.0})
        label, _ = model_with_sun(raster, 45, 270).classify_point(*POINT)
        self.assertEqual(label, "sun")

    def test_short_building_below_sight_line_does_not_shade(self):
        raster = make_raster({east_of(10): 5.0})
        label, _ = model_with_sun(raster, 45, 90).classify_point(*POINT)
        self.assertEqual(label, "sun")

    def test_missing_height_toward_sun_is_unknown_not_zero(self):
        raster = make_raster({east_of(6): math.nan})
        label, _ = model_with_sun(raster, 45, 90).classify_point(*POINT)
        self.assertEqual(label, "unknown")

    def test_known_blocker_wins_over_missing_height(self):
        raster = make_raster({east_of(4): math.nan, east_of(10): 20.0})
        label, _ = model_with_sun(raster, 45, 90).classify_point(*POINT)
        self.assertEqual(label, "shaded")

    def test_sun_below_horizon_is_no_direct_sun(self):
        label, detail = model_with_sun(make_raster({}), -5, 90).classify_point(*POINT)
        self.assertEqual((label, detail["cause"]), ("shaded", "night"))

    def test_height_lookup_reports_unknown_outside_raster(self):
        self.assertIsNone(make_raster({}).height_at(15.0, 122.0))


class AnalyzeRouteTests(unittest.TestCase):
    def setUp(self):
        # A west-to-east route; a tall building row north of its eastern half shades it from a northern sun.
        self.west = [POINT[1] - 30 / METERS_PER_DEG_LON, POINT[0]]
        self.middle = [POINT[1], POINT[0]]
        self.east = [POINT[1] + 30 / METERS_PER_DEG_LON, POINT[0]]
        cells = {}
        for step in range(0, 31, 2):
            cells[(POINT[0] + 8 / 111_320, POINT[1] + step / METERS_PER_DEG_LON)] = 30.0
        cells[(POINT[0] + 8 / 111_320, self.west[0] + 5 / METERS_PER_DEG_LON)] = math.nan
        self.raster = make_raster(cells)
        self.model = model_with_sun(self.raster, 45, 0)

    def analyze(self, covered=None):
        return analyze_route([self.west, self.middle, self.east], "2026-10-15T12:00:00+08:00", self.raster, covered, self.model)

    def test_route_has_mixed_sections_and_percent_matches_section_lengths(self):
        result = self.analyze()
        labels = [section["label"] for section in result["sections"]]
        self.assertIn("shaded", labels)
        self.assertGreaterEqual(len(result["sections"]), 2)
        total = sum(section["length_m"] for section in result["sections"])
        exposed = sum(section["length_m"] for section in result["sections"] if section["label"] in {"sun", "unknown"})
        self.assertAlmostEqual(result["sun_percent"], exposed / total * 100, delta=0.2)
        self.assertAlmostEqual(result["sun_minutes"], exposed / 80, delta=0.1)
        expected_total = distance_meters(POINT[0], self.west[0], POINT[0], self.east[0])
        self.assertAlmostEqual(total, expected_total, delta=0.5)

    def test_adjacent_pieces_with_same_label_are_merged(self):
        labels = [section["label"] for section in self.analyze()["sections"]]
        self.assertTrue(all(first != second for first, second in zip(labels, labels[1:])))

    def test_unknown_sections_count_as_sun_and_are_reported(self):
        result = self.analyze()
        self.assertGreater(result["unknown_percent"], 0)
        unknown = sum(section["length_m"] for section in result["sections"] if section["label"] == "unknown")
        self.assertAlmostEqual(result["unknown_length_m"], unknown, delta=0.2)
        self.assertGreaterEqual(result["sun_length_m"], unknown)

    def test_covered_segment_counts_as_shaded_and_removal_restores(self):
        base = self.analyze()
        covered = self.analyze([True, False])
        self.assertIn("covered", [section["label"] for section in covered["sections"]])
        self.assertLess(covered["sun_percent"], base["sun_percent"])
        west_half_exposed = sum(
            piece["length_m"] for piece in self.model.segment_pieces(self.west, self.middle)
            if piece["label"] in {"sun", "unknown"}
        )
        self.assertGreater(west_half_exposed, 0)
        total = sum(section["length_m"] for section in base["sections"])
        self.assertAlmostEqual(base["sun_percent"] - covered["sun_percent"], west_half_exposed / total * 100, delta=0.3)
        self.assertEqual(self.analyze([False, False])["sun_percent"], base["sun_percent"])

    def test_every_section_has_a_reason(self):
        for section in self.analyze([True, False])["sections"]:
            self.assertTrue(section["reason"])


class FootprintTests(unittest.TestCase):
    def ring_around(self, latitude, longitude, half_m=6):
        d_lat = half_m / 111_320
        d_lon = half_m / METERS_PER_DEG_LON
        return [(latitude - d_lat, longitude - d_lon), (latitude - d_lat, longitude + d_lon),
                (latitude + d_lat, longitude + d_lon), (latitude + d_lat, longitude - d_lon),
                (latitude - d_lat, longitude - d_lon)]

    def test_footprint_without_height_becomes_unknown(self):
        raster = make_raster({})
        report = raster.mark_unknown_footprints([self.ring_around(*POINT)])
        self.assertEqual(report["without_height"], 1)
        self.assertIsNone(raster.height_at(*POINT))

    def test_footprint_with_height_is_kept(self):
        raster = make_raster({POINT: 12.0})
        report = raster.mark_unknown_footprints([self.ring_around(*POINT)])
        self.assertEqual(report["with_height"], 1)
        self.assertEqual(raster.height_at(*POINT), 12.0)


if __name__ == "__main__":
    unittest.main()
