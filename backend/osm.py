"""OpenStreetMap building rules shared by the data build (build_tiles.py) and the tests.

The API no longer parses OSM at startup; it reads the prebuilt tiles (see tiles.py).
"""

from __future__ import annotations

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
