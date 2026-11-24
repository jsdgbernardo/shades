"""The fast sight-line check must give exactly the labels and details of the plain one kept here."""

import math
import random
import unittest
from array import array

import app
from shade import EYE_HEIGHT_M, MAX_RAY_M, SAMPLE_STEP_M, SUN_LABELS, ExposureModel, HeightRaster

SUN_TIMES = [
    "2026-11-24T06:10:00+08:00",  # sun very low, long sight lines
    "2026-11-24T07:30:00+08:00",
    "2026-11-24T10:00:00+08:00",
    "2026-04-27T12:00:00+08:00",  # sun almost overhead
    "2026-06-21T12:10:00+08:00",  # sun to the north
    "2026-06-21T15:30:00+08:00",
    "2026-11-24T17:10:00+08:00",
    "2026-11-24T20:00:00+08:00",  # night
]


def reference_classify(model: ExposureModel, latitude: float, longitude: float):
    """The original algorithm: look up the height at every sample."""
    if model.elevation <= 0:
        return "shaded", {"cause": "night"}
    tan_elevation = math.tan(math.radians(model.elevation))
    max_distance = min(MAX_RAY_M, (model.raster.max_height - EYE_HEIGHT_M) / tan_elevation)
    meters_per_degree_lat = 111_320
    meters_per_degree_lon = 111_320 * math.cos(math.radians(latitude))
    toward_east = math.sin(math.radians(model.azimuth))
    toward_north = math.cos(math.radians(model.azimuth))
    unknown = False
    distance = SAMPLE_STEP_M
    while distance <= max_distance:
        height = model.raster.height_at(
            latitude + toward_north * distance / meters_per_degree_lat,
            longitude + toward_east * distance / meters_per_degree_lon,
        )
        if height is None:
            unknown = True
        elif height > EYE_HEIGHT_M + distance * tan_elevation:
            return "shaded", {"cause": "building", "height_m": round(height, 1), "distance_m": distance}
        distance += SAMPLE_STEP_M
    return ("unknown", {"cause": "no_height"}) if unknown else ("sun", {"cause": "open"})


def random_raster(rng: random.Random, width: int, height: int, pixel_size: float, unknown_share: float = 0.002) -> HeightRaster:
    """Mostly open ground with scattered buildings, a few of them tall, and scattered unknown cells."""
    values = array("f", [0.0]) * (width * height)
    for index in range(len(values)):
        draw = rng.random()
        if draw < unknown_share:
            values[index] = math.nan
        elif draw < 0.05:
            values[index] = rng.uniform(0, 12)
        elif draw < 0.055:
            values[index] = rng.uniform(12, 150)
    return HeightRaster(width, height, 121.0, 14.7, pixel_size, values)


def random_points(rng: random.Random, raster: HeightRaster, count: int) -> list[tuple[float, float]]:
    """(lat, lon) points inside, along each edge (within 40 cells, and within 1.5 cells), and outside."""
    rows, columns, pixel = raster.height, raster.width, raster.pixel_size

    def point(row: float, column: float) -> tuple[float, float]:
        return raster.origin_lat - row * pixel, raster.origin_lon + column * pixel

    points = []
    for _ in range(count):
        points.append(point(rng.uniform(0, rows), rng.uniform(0, columns)))
        for spread in (1.5, 40):
            offset = rng.uniform(-spread, spread)
            points.append(point(offset, rng.uniform(-5, columns + 5)))
            points.append(point(rows + offset, rng.uniform(-5, columns + 5)))
            points.append(point(rng.uniform(-5, rows + 5), offset))
            points.append(point(rng.uniform(-5, rows + 5), columns + offset))
        # Exactly on cell corners, where rounding decides the cell.
        points.append(point(rng.randrange(-2, rows + 2), rng.randrange(-2, columns + 2)))
        points.append(point(rng.uniform(-3 * rows, 4 * rows), rng.uniform(-3 * columns, 4 * columns)))
    points += [(0.0, 0.0), (-33.9, 151.2), (60.0, 121.01)]
    return points


class SightLineTests(unittest.TestCase):
    def assert_same(self, model: ExposureModel, points: list[tuple[float, float]]) -> set[str]:
        causes = set()
        for latitude, longitude in points:
            expected = reference_classify(model, latitude, longitude)
            actual = model.classify_point(latitude, longitude)
            if expected != actual or repr(expected) != repr(actual):
                self.fail(f"{(latitude, longitude)} at {model.travel_time}: expected {expected}, got {actual}")
            causes.add(expected[1]["cause"])
        return causes

    def test_real_raster_matches_the_reference(self):
        raster = app.HEIGHT_RASTER
        rng = random.Random(189)
        causes = set()
        for time in SUN_TIMES:
            model = ExposureModel(raster, time, *app.STUDY_CENTER)
            points = random_points(rng, raster, 120)
            # Dense cluster, so many points share the same cached block.
            row, column = rng.uniform(300, 1400), rng.uniform(300, 1200)
            points += [
                (raster.origin_lat - (row + rng.uniform(0, 30)) * raster.pixel_size, raster.origin_lon + (column + rng.uniform(0, 30)) * raster.pixel_size)
                for _ in range(400)
            ]
            causes |= self.assert_same(model, points)
        self.assertEqual(causes, {"night", "building", "no_height", "open"})

    def test_synthetic_rasters_match_the_reference(self):
        rng = random.Random(42)
        causes = set()
        for width, height, pixel in [(64, 64, 9e-5), (37, 53, 5e-5), (3, 5, 9e-5), (1, 1, 2e-4), (70, 41, 1.5e-5)]:
            raster = random_raster(rng, width, height, pixel)
            for time in SUN_TIMES:
                model = ExposureModel(raster, time, 14.65, 121.05)
                causes |= self.assert_same(model, random_points(rng, raster, 25))
        self.assertEqual(causes, {"night", "building", "no_height", "open"})

    def test_every_sun_direction_matches_the_reference(self):
        rng = random.Random(7)
        raster = random_raster(rng, 60, 60, 9e-5)
        for azimuth in list(range(0, 360, 45)) + [rng.uniform(0, 360) for _ in range(8)]:
            for elevation in (0.01, 3, 20, 45, 80, 89.99):
                model = ExposureModel(raster, SUN_TIMES[2], 14.65, 121.05)
                model.elevation, model.azimuth = elevation, azimuth
                self.assert_same(model, random_points(rng, raster, 5))

    def test_unknown_or_empty_rasters_match_the_reference(self):
        rng = random.Random(3)
        for value in (math.nan, 0.0, 1.0, 30.0):
            raster = HeightRaster(20, 20, 121.0, 14.7, 9e-5, array("f", [value]) * 400)
            self.assert_same(ExposureModel(raster, SUN_TIMES[2], 14.65, 121.05), random_points(rng, raster, 10))

    def test_marking_unknown_cells_updates_a_model_already_in_use(self):
        rng = random.Random(11)
        raster = random_raster(rng, 40, 40, 9e-5, unknown_share=0)
        model = ExposureModel(raster, SUN_TIMES[2], 14.65, 121.05)
        points = random_points(rng, raster, 20)
        self.assert_same(model, points)
        pixel = raster.pixel_size
        north, south = raster.origin_lat - 8 * pixel, raster.origin_lat - 30 * pixel
        west, east = raster.origin_lon + 8 * pixel, raster.origin_lon + 30 * pixel
        ring = [(north, west), (north, east), (south, east), (south, west), (north, west)]
        # Only an all-open footprint becomes unknown, so clear it first.
        for row, column in raster._cells_in_polygon(ring):
            raster.values[row * raster.width + column] = 0.0
        self.assertEqual(raster.mark_unknown_footprints([ring])["without_height"], 1)
        self.assert_same(model, points)

    def test_segment_lengths_match_the_pieces(self):
        rng = random.Random(5)
        raster = app.HEIGHT_RASTER
        for _ in range(150):
            first = [rng.uniform(121.02, 121.12), rng.uniform(14.60, 14.72)]
            second = [first[0] + rng.uniform(-1e-3, 1e-3), first[1] + rng.uniform(-1e-3, 1e-3)]
            model = ExposureModel(raster, SUN_TIMES[2], *app.STUDY_CENTER)
            shaded = exposed = 0.0
            for piece in model.segment_pieces(first, second):
                if piece["label"] in SUN_LABELS:
                    exposed += piece["length_m"]
                else:
                    shaded += piece["length_m"]
            self.assertEqual(model.segment_lengths(first, second), (shaded, exposed))


if __name__ == "__main__":
    unittest.main()
