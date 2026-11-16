"""Single parse of the local OpenStreetMap extract, shared by routing, shade and place search."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


NETWORK_PATH = Path(__file__).parents[1] / "datasets" / "katipunan-walking-network.osm"


@dataclass
class OsmWay:
    way_id: int
    node_ids: list[int]
    tags: dict[str, str]


@dataclass
class OsmData:
    coordinates: dict[int, tuple[float, float]]
    ways: list[OsmWay]
    named_nodes: list[tuple[int, str, dict[str, str]]] = field(default_factory=list)

    def building_footprints(self, enclosed_only: bool = False) -> list[list[tuple[float, float]]]:
        """Closed building ways as (latitude, longitude) rings. Multipolygon relations are not included."""
        footprints = []
        for way in self.ways:
            if "building" not in way.tags or len(way.node_ids) < 4 or way.node_ids[0] != way.node_ids[-1]:
                continue
            if enclosed_only and not is_enclosed_ground_building(way.tags):
                continue
            ring = [self.coordinates[node] for node in way.node_ids if node in self.coordinates]
            if len(ring) >= 4:
                footprints.append(ring)
        return footprints


OPEN_STRUCTURES = {"roof", "carport", "canopy", "shelter", "bridge", "construction", "ruins"}


def is_enclosed_ground_building(tags: dict[str, str]) -> bool:
    """A building a pedestrian cannot walk through at street level (PRD C-01).

    Open roofs and canopies are outdoor shelter, and raised structures (layer >= 1 or a
    minimum level above ground) have walkable space underneath, so neither counts.
    """
    if "building" not in tags or tags["building"] in OPEN_STRUCTURES:
        return False
    try:
        if int(tags.get("layer", "0")) >= 1:
            return False
    except ValueError:
        pass
    return tags.get("min_level") in (None, "0") and tags.get("building:min_level") in (None, "0")


class FootprintIndex:
    """Fast point-in-building lookup over enclosed ground-level footprints."""

    CELL = 0.0005  # degrees, about 55 m

    def __init__(self, footprints: list[list[tuple[float, float]]]) -> None:
        from shade import point_in_ring

        self._point_in_ring = point_in_ring
        self.grid: dict[tuple[int, int], list[tuple[float, float, float, float, list]]] = {}
        for ring in footprints:
            lats = [point[0] for point in ring]
            lons = [point[1] for point in ring]
            box = (min(lats), max(lats), min(lons), max(lons), ring)
            for row in range(int(box[0] / self.CELL), int(box[1] / self.CELL) + 1):
                for column in range(int(box[2] / self.CELL), int(box[3] / self.CELL) + 1):
                    self.grid.setdefault((row, column), []).append(box)

    def contains(self, latitude: float, longitude: float) -> bool:
        for south, north, west, east, ring in self.grid.get((int(latitude / self.CELL), int(longitude / self.CELL)), ()):
            if south <= latitude <= north and west <= longitude <= east and self._point_in_ring(latitude, longitude, ring):
                return True
        return False


def load_osm(path: Path = NETWORK_PATH) -> OsmData:
    root = ET.parse(path).getroot()
    coordinates: dict[int, tuple[float, float]] = {}
    named_nodes = []
    for node in root.findall("node"):
        node_id = int(node.attrib["id"])
        coordinates[node_id] = (float(node.attrib["lat"]), float(node.attrib["lon"]))
        tags = {tag.attrib.get("k"): tag.attrib.get("v") for tag in node.findall("tag")}
        if tags.get("name"):
            named_nodes.append((node_id, tags["name"], tags))
    ways = [
        OsmWay(
            int(way.attrib["id"]),
            [int(nd.attrib["ref"]) for nd in way.findall("nd")],
            {tag.attrib.get("k"): tag.attrib.get("v") for tag in way.findall("tag")},
        )
        for way in root.findall("way")
    ]
    return OsmData(coordinates, ways, named_nodes)
