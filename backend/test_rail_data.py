"""Checks on the committed train-option station data, datasets/derived/rail.json (PRD D-04, C-07).

The file is written by build_rail.py from OpenStreetMap; these tests read only the committed file.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from build_rail import norm_name, project
from routing import haversine_meters

RAIL = Path(__file__).parents[1] / "datasets" / "derived" / "rail.json"
ON_SHAPE_M = 2.0  # stations and shape ends must sit on the shape
MAX_TURN_DEG = 100.0  # a sharper bend between two track pieces means a way was chained backwards

# Published station lists (Wikipedia line articles, read 2026-11-26), in line order. OSM uses
# the naming-rights name "Yamaha Monumento" for Monumento.
PUBLISHED = {
    "lrt1": ["Fernando Poe Jr.", "Balintawak", "Yamaha Monumento", "5th Avenue", "R. Papa", "Abad Santos",
             "Blumentritt", "Tayuman", "Bambang", "Doroteo Jose", "Carriedo", "Central Terminal",
             "United Nations", "Pedro Gil", "Quirino", "Vito Cruz", "Gil Puyat", "Libertad", "EDSA",
             "Baclaran", "Redemptorist-Aseana", "MIA Road", "PITX", "Ninoy Aquino Avenue", "Dr. Santos"],
    "lrt2": ["Recto", "Legarda", "Pureza", "V. Mapa", "J. Ruiz", "Gilmore", "Betty Go-Belmonte",
             "Araneta Center-Cubao", "Anonas", "Katipunan", "Santolan", "Marikina-Pasig", "Antipolo"],
    "mrt3": ["North Avenue", "Quezon Avenue", "GMA Kamuning", "Araneta Center-Cubao", "Santolan-Annapolis",
             "Ortigas", "Shaw Boulevard", "Boni", "Guadalupe", "Buendia", "Ayala", "Magallanes", "Taft Avenue"],
}
EXCLUDED_WORDS = ("pnr", "subway", "line 7", "mrt-7", "mrt 7", "mrt-9", "commuter", "north-south")


def bearing(a, b) -> float:
    dy = b[0] - a[0]
    dx = (b[1] - a[1]) * math.cos(math.radians(a[0]))
    return math.degrees(math.atan2(dx, dy))


class RailDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(RAIL.read_text(encoding="utf-8"))
        cls.lines = {line["id"]: line for line in cls.data["lines"]}
        cls.stations = {s["id"]: s for line in cls.data["lines"] for s in line["stations"]}

    def test_three_operating_lines_only(self):
        self.assertEqual(sorted(self.lines), ["lrt1", "lrt2", "mrt3"])
        self.assertEqual({l["ref"] for l in self.lines.values()}, {"1", "2", "3"})
        for line in self.lines.values():
            text = (line["name"] + " " + " ".join(s["name"] for s in line["stations"])).lower()
            for word in EXCLUDED_WORDS:
                self.assertNotIn(word, text, line["id"])
            self.assertRegex(line["colour"], r"^#[0-9A-Fa-f]{6}$")

    def test_stations_match_published_order(self):
        for line_id, names in PUBLISHED.items():
            got = [norm_name(s["name"]) for s in self.lines[line_id]["stations"]]
            self.assertEqual(got, [norm_name(n) for n in names], line_id)

    def test_positions_increase_and_span_the_line(self):
        for line in self.lines.values():
            positions = [s["position_m"] for s in line["stations"]]
            self.assertEqual(positions[0], 0)
            self.assertTrue(all(b > a for a, b in zip(positions, positions[1:])), line["id"])
            self.assertAlmostEqual(positions[-1], line["length_m"], delta=1.0)

    def test_station_ids_unique_and_fields_present(self):
        ids = [s["id"] for line in self.lines.values() for s in line["stations"]]
        self.assertEqual(len(ids), len(set(ids)))
        for s in self.stations.values():
            for key in ("name", "osm_id", "lat", "lon", "position_m", "entrance_source", "entrances", "in_study_area"):
                self.assertIn(key, s, s["id"])
            self.assertRegex(s["osm_id"], r"^(node|way|relation)/\d+$")

    def test_every_station_has_an_entrance(self):
        for s in self.stations.values():
            self.assertGreaterEqual(len(s["entrances"]), 1, s["id"])
            self.assertIn(s["entrance_source"], ("osm", "station"))
            for e in s["entrances"]:
                d = haversine_meters((s["lat"], s["lon"]), (e["lat"], e["lon"]))
                self.assertLessEqual(d, 400, s["id"])
            if s["entrance_source"] == "station":
                self.assertEqual([(e["lat"], e["lon"]) for e in s["entrances"]], [(s["lat"], s["lon"])])

    def test_transfers_resolve(self):
        pairs = {(t["from"], t["to"]) for t in self.data["transfers"]}
        self.assertEqual(pairs, {
            ("lrt1:edsa", "mrt3:taft-avenue"),
            ("lrt1:doroteo-jose", "lrt2:recto"),
            ("lrt2:araneta-center-cubao", "mrt3:araneta-center-cubao"),
        })
        for t in self.data["transfers"]:
            a, b = self.stations[t["from"]], self.stations[t["to"]]
            self.assertNotEqual(a["id"].split(":")[0], b["id"].split(":")[0])
            self.assertLess(haversine_meters((a["lat"], a["lon"]), (b["lat"], b["lon"])), 600)

    def test_shapes_continuous(self):
        for line in self.lines.values():
            shape = [tuple(p) for p in line["shape"]]
            first, last = line["stations"][0], line["stations"][-1]
            self.assertLess(haversine_meters(shape[0], (first["lat"], first["lon"])), ON_SHAPE_M, line["id"])
            self.assertLess(haversine_meters(shape[-1], (last["lat"], last["lon"])), ON_SHAPE_M, line["id"])
            for s in line["stations"]:
                along, off, _ = project(shape, (s["lat"], s["lon"]))
                self.assertLess(off, ON_SHAPE_M, s["id"])
                self.assertAlmostEqual(along, s["position_m"], delta=ON_SHAPE_M, msg=s["id"])
            # No reversals: a way chained the wrong way round would double back.
            for a, b, c in zip(shape, shape[1:], shape[2:]):
                if haversine_meters(a, b) < 3 or haversine_meters(b, c) < 3:
                    continue
                turn = abs((bearing(b, c) - bearing(a, b) + 180) % 360 - 180)
                self.assertLess(turn, MAX_TURN_DEG, f"{line['id']} at {b}")
            # Between neighbouring stations the track is not much longer than the straight line.
            for s, t in zip(line["stations"], line["stations"][1:]):
                straight = haversine_meters((s["lat"], s["lon"]), (t["lat"], t["lon"]))
                self.assertLessEqual(straight, t["position_m"] - s["position_m"] + 1, (s["id"], t["id"]))
                self.assertLess(t["position_m"] - s["position_m"], 1.5 * straight, (s["id"], t["id"]))


if __name__ == "__main__":
    unittest.main()
