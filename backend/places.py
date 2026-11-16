"""Place search over the named features in the local OSM extract (PRD S-02).

Search stays offline and inside the study area; no external geocoder is used.
"""

from __future__ import annotations

from osm import OsmData

KIND_TAGS = ("amenity", "shop", "leisure", "tourism", "office", "building", "highway", "landuse", "railway", "public_transport")


def kind_of(tags: dict[str, str]) -> str:
    for key in KIND_TAGS:
        value = tags.get(key)
        if value:
            if key == "highway":
                return "street" if value not in {"bus_stop", "crossing", "traffic_signals"} else value.replace("_", " ")
            if key == "building":
                return "building" if value in {"yes", "university", "school"} else value.replace("_", " ")
            return value.replace("_", " ")
    return "place"


class PlaceIndex:
    def __init__(self, places: list[dict]) -> None:
        self.places = places

    @classmethod
    def from_osm(cls, osm: OsmData, inside) -> "PlaceIndex":
        places: dict[str, dict] = {}

        def add(identifier: str, name: str, tags: dict[str, str], latitude: float, longitude: float) -> None:
            if not inside(latitude, longitude):
                return
            kind = kind_of(tags).lower()
            # One entry per name: a building and the amenity inside it are the same place to a walker.
            key = name.casefold()
            if key not in places:
                places[key] = {"id": identifier, "name": name, "kind": kind, "latitude": round(latitude, 6), "longitude": round(longitude, 6)}

        for node_id, name, tags in osm.named_nodes:
            latitude, longitude = osm.coordinates[node_id]
            add(f"n{node_id}", name, tags, latitude, longitude)
        for way in osm.ways:
            name = way.tags.get("name")
            points = [osm.coordinates[node] for node in way.node_ids if node in osm.coordinates]
            if not name or not points:
                continue
            if "highway" in way.tags:
                # Use the middle node of a street so the point sits on the street itself.
                latitude, longitude = points[len(points) // 2]
            else:
                latitude = sum(point[0] for point in points) / len(points)
                longitude = sum(point[1] for point in points) / len(points)
            add(f"w{way.way_id}", name, way.tags, latitude, longitude)
        return cls(sorted(places.values(), key=lambda place: place["name"].casefold()))

    def search(self, query: str, limit: int = 8) -> list[dict]:
        needle = query.strip().casefold()
        if len(needle) < 2:
            return []
        starts = [place for place in self.places if place["name"].casefold().startswith(needle)]
        words = [place for place in self.places if place not in starts and any(word.startswith(needle) for word in place["name"].casefold().split())]
        contains = [place for place in self.places if place not in starts and place not in words and needle in place["name"].casefold()]
        return (starts + words + contains)[:limit]
