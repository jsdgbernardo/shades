"""Route shade analysis using the local building-height GeoTIFF and the sun position.

Each route is cut into pieces of about PIECE_M metres. From each piece's midpoint the
model looks toward the sun and checks whether a building is tall enough to block it.

Labels:
- ``shaded``: a building with known height blocks the sun (or the sun is below the horizon).
- ``sun``: nothing blocks the sun and every relevant height sample is known.
- ``unknown``: nothing known blocks the sun, but some samples have no height data.
  Unknown is counted as direct sun in every figure (PRD E-03).
- ``covered``: the edge is marked covered by users (PRD S-11). Counted as shaded.
"""

from __future__ import annotations

import math
import struct
from array import array
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


HEIGHT_PATH = Path(__file__).parents[1] / "datasets" / "building-heights" / "2026_HEIGHT_GVSSM.tif"
LOCAL_ZONE = ZoneInfo("Asia/Manila")
EYE_HEIGHT_M = 1.7
SAMPLE_STEP_M = 2
MAX_RAY_M = 200
PIECE_M = 10.0
WALKING_SPEED_M_PER_MIN = 80.0
SUN_LABELS = {"sun", "unknown"}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


class HeightRaster:
    """Building heights in metres. NaN means the height is unknown."""

    def __init__(self, width: int, height: int, origin_lon: float, origin_lat: float, pixel_size: float, values: array) -> None:
        self.width = width
        self.height = height
        self.origin_lon = origin_lon
        self.origin_lat = origin_lat
        self.pixel_size = pixel_size
        self.values = values
        finite = [value for value in values if not math.isnan(value)]
        self.max_height = max(finite) if finite else 0.0

    @classmethod
    def from_file(cls, path: Path = HEIGHT_PATH) -> "HeightRaster":
        data = path.read_bytes()
        if data[:2] != b"II" or struct.unpack_from("<H", data, 2)[0] != 42:
            raise ValueError("Only little-endian classic GeoTIFF files are supported")

        ifd_offset = struct.unpack_from("<I", data, 4)[0]
        entry_count = struct.unpack_from("<H", data, ifd_offset)[0]
        tags: dict[int, tuple[int, int, int]] = {}
        for index in range(entry_count):
            offset = ifd_offset + 2 + index * 12
            tag, data_type, count = struct.unpack_from("<HHI", data, offset)
            value_offset = struct.unpack_from("<I", data, offset + 8)[0]
            tags[tag] = (data_type, count, value_offset)

        def values(tag: int) -> list[int | float]:
            data_type, count, value_offset = tags[tag]
            widths = {3: 2, 4: 4, 12: 8}
            width = widths[data_type]
            if count * width <= 4 and data_type == 3:
                return [value_offset & 0xFFFF]
            if count * width <= 4 and data_type == 4:
                return [value_offset]
            location = value_offset
            if data_type == 3:
                return list(struct.unpack_from(f"<{count}H", data, location))
            if data_type == 4:
                return list(struct.unpack_from(f"<{count}I", data, location))
            return list(struct.unpack_from(f"<{count}d", data, location))

        width = int(values(256)[0])
        height = int(values(257)[0])
        tile_width = int(values(322)[0])
        tile_height = int(values(323)[0])
        tile_offsets = [int(value) for value in values(324)]
        tile_counts = [int(value) for value in values(325)]
        pixel_scale = values(33550)
        tiepoint = values(33922)
        origin_lon = float(tiepoint[3])
        origin_lat = float(tiepoint[4])
        pixel_size = float(pixel_scale[0])
        raster_values = array("f", [math.nan]) * (width * height)

        for tile_index, (tile_offset, tile_count) in enumerate(zip(tile_offsets, tile_counts)):
            raw = unpack_packbits(data[tile_offset:tile_offset + tile_count])
            tile_column = tile_index % math.ceil(width / tile_width)
            tile_row = tile_index // math.ceil(width / tile_width)
            actual_width = min(tile_width, width - tile_column * tile_width)
            actual_height = min(tile_height, height - tile_row * tile_height)
            source_stride = len(raw) // 4 // actual_height
            for row in range(actual_height):
                for column in range(actual_width):
                    source_offset = (row * source_stride + column) * 4
                    value = struct.unpack_from("<f", raw, source_offset)[0]
                    target = (tile_row * tile_height + row) * width + tile_column * tile_width + column
                    # Non-finite or out-of-range values are nodata: keep them unknown, never zero (PRD D-01).
                    raster_values[target] = value if math.isfinite(value) and 0 <= value < 1000 else math.nan

        return cls(width, height, origin_lon, origin_lat, pixel_size, raster_values)

    def cell(self, latitude: float, longitude: float) -> tuple[int, int] | None:
        column = int((longitude - self.origin_lon) / self.pixel_size)
        row = int((self.origin_lat - latitude) / self.pixel_size)
        if not (0 <= column < self.width and 0 <= row < self.height):
            return None
        return row, column

    def height_at(self, latitude: float, longitude: float) -> float | None:
        """Height in metres, 0 for open ground, or None when the height is unknown."""
        cell = self.cell(latitude, longitude)
        if cell is None:
            return None
        value = float(self.values[cell[0] * self.width + cell[1]])
        return None if math.isnan(value) else value

    def mark_unknown_cells(self, path: Path) -> int:
        """Mark raster cells listed in a build output file (uint32 indices) as unknown height.

        build_tiles.py computes these with mark_unknown_footprints over all OSM buildings, so
        the API does not need to load building footprints at startup.
        """
        cells = array("I")
        if Path(path).exists():
            with open(path, "rb") as handle:
                cells.frombytes(handle.read())
        size = len(self.values)
        for index in cells:
            if index < size:
                self.values[index] = math.nan
        return len(cells)

    def mark_unknown_footprints(self, footprints: list[list[tuple[float, float]]]) -> dict[str, int]:
        """Flag building footprints that the raster reports as open ground.

        A footprint whose cells all read 0 is a building without height data, so its cells
        become unknown instead of being treated as zero height (PRD D-01, E-03).
        Returns counts for the data report.
        """
        with_height = 0
        without_height = 0
        for ring in footprints:
            cells = self._cells_in_polygon(ring)
            if not cells:
                continue
            heights = [self.values[row * self.width + column] for row, column in cells]
            if any(not math.isnan(value) and value > 0 for value in heights):
                with_height += 1
                continue
            without_height += 1
            for row, column in cells:
                self.values[row * self.width + column] = math.nan
        return {"buildings": with_height + without_height, "with_height": with_height, "without_height": without_height}

    def _cells_in_polygon(self, ring: list[tuple[float, float]]) -> list[tuple[int, int]]:
        lats = [point[0] for point in ring]
        lons = [point[1] for point in ring]
        first = self.cell(max(lats), min(lons))
        last = self.cell(min(lats), max(lons))
        if first is None or last is None:
            return []
        cells = []
        for row in range(first[0], last[0] + 1):
            for column in range(first[1], last[1] + 1):
                latitude = self.origin_lat - (row + 0.5) * self.pixel_size
                longitude = self.origin_lon + (column + 0.5) * self.pixel_size
                if point_in_ring(latitude, longitude, ring):
                    cells.append((row, column))
        if not cells:
            # Footprints smaller than one cell: use the cell under the centroid.
            centre = self.cell(sum(lats) / len(lats), sum(lons) / len(lons))
            if centre:
                cells.append(centre)
        return cells


def point_in_ring(latitude: float, longitude: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    for (lat_a, lon_a), (lat_b, lon_b) in zip(ring, ring[1:]):
        if (lat_a > latitude) != (lat_b > latitude):
            crossing = lon_a + (latitude - lat_a) * (lon_b - lon_a) / (lat_b - lat_a)
            if longitude < crossing:
                inside = not inside
    return inside


def unpack_packbits(data: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(data):
        control = struct.unpack_from("<b", data, index)[0]
        index += 1
        if 0 <= control <= 127:
            count = control + 1
            output.extend(data[index:index + count])
            index += count
        elif -127 <= control <= -1:
            output.extend(data[index:index + 1] * (1 - control))
            index += 1
    return bytes(output)


def parse_local_time(travel_time: str) -> datetime:
    parsed = datetime.fromisoformat(travel_time.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=LOCAL_ZONE) if parsed.tzinfo is None else parsed.astimezone(LOCAL_ZONE)


def shift_time(travel_time: str, minutes: int) -> str:
    return (parse_local_time(travel_time) + timedelta(minutes=minutes)).isoformat(timespec="minutes")


def solar_position(travel_time: str, latitude: float, longitude: float) -> tuple[float, float]:
    """Sun elevation and azimuth (degrees clockwise from north), NOAA general solar position equations."""
    local_time = parse_local_time(travel_time)
    utc_time = local_time.astimezone(timezone.utc)
    day = utc_time.timetuple().tm_yday
    hour = utc_time.hour + utc_time.minute / 60 + utc_time.second / 3600
    gamma = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    equation = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    declination = 0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    offset_minutes = local_time.utcoffset().total_seconds() / 60
    solar_minutes = (local_time.hour * 60 + local_time.minute + equation + 4 * longitude - offset_minutes) % 1440
    hour_angle = math.radians(solar_minutes / 4 - 180)
    latitude_radians = math.radians(latitude)
    zenith = math.acos(math.sin(latitude_radians) * math.sin(declination) + math.cos(latitude_radians) * math.cos(declination) * math.cos(hour_angle))
    elevation = 90 - math.degrees(zenith)
    azimuth = (math.degrees(math.atan2(math.sin(hour_angle), math.cos(hour_angle) * math.sin(latitude_radians) - math.tan(declination) * math.cos(latitude_radians))) + 180) % 360
    return elevation, azimuth


def compass(azimuth: float) -> str:
    return COMPASS[int((azimuth % 360 + 22.5) // 45) % 8]


@dataclass
class ExposureModel:
    """Sun/shade classifier for one travel time. Results are memoized per segment."""

    raster: HeightRaster
    travel_time: str
    latitude: float
    longitude: float
    elevation: float = field(init=False)
    azimuth: float = field(init=False)
    _cache: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.elevation, self.azimuth = solar_position(self.travel_time, self.latitude, self.longitude)

    def classify_point(self, latitude: float, longitude: float) -> tuple[str, dict[str, float | str]]:
        if self.elevation <= 0:
            return "shaded", {"cause": "night"}
        tan_elevation = math.tan(math.radians(self.elevation))
        # Beyond this distance even the tallest building in the raster cannot reach the sight line.
        max_distance = min(MAX_RAY_M, (self.raster.max_height - EYE_HEIGHT_M) / tan_elevation)
        meters_per_degree_lat = 111_320
        meters_per_degree_lon = 111_320 * math.cos(math.radians(latitude))
        toward_east = math.sin(math.radians(self.azimuth))
        toward_north = math.cos(math.radians(self.azimuth))
        unknown = False
        distance = SAMPLE_STEP_M
        while distance <= max_distance:
            height = self.raster.height_at(
                latitude + toward_north * distance / meters_per_degree_lat,
                longitude + toward_east * distance / meters_per_degree_lon,
            )
            if height is None:
                unknown = True
            elif height > EYE_HEIGHT_M + distance * tan_elevation:
                return "shaded", {"cause": "building", "height_m": round(height, 1), "distance_m": distance}
            distance += SAMPLE_STEP_M
        return ("unknown", {"cause": "no_height"}) if unknown else ("sun", {"cause": "open"})

    def segment_pieces(self, first: list[float], second: list[float]) -> list[dict]:
        """Split one [lon, lat] segment into ~PIECE_M pieces and classify each."""
        key = (tuple(first), tuple(second))
        if key in self._cache:
            return self._cache[key]
        length = distance_meters(first[1], first[0], second[1], second[0])
        count = max(1, math.ceil(length / PIECE_M))
        pieces = []
        for index in range(count):
            start = interpolate(first, second, index / count)
            end = interpolate(first, second, (index + 1) / count)
            midpoint = interpolate(first, second, (index + 0.5) / count)
            label, detail = self.classify_point(midpoint[1], midpoint[0])
            pieces.append({"geometry": [start, end], "label": label, "length_m": length / count, "detail": detail})
        self._cache[key] = pieces
        return pieces

    def segment_lengths(self, first: list[float], second: list[float]) -> tuple[float, float]:
        """(shaded length, sun-or-unknown length) of one segment, for route cost."""
        shaded = exposed = 0.0
        for piece in self.segment_pieces(first, second):
            if piece["label"] in SUN_LABELS:
                exposed += piece["length_m"]
            else:
                shaded += piece["length_m"]
        return shaded, exposed


def interpolate(first: list[float], second: list[float], fraction: float) -> list[float]:
    return [first[0] + (second[0] - first[0]) * fraction, first[1] + (second[1] - first[1]) * fraction]


def section_reason(label: str, details: list[dict], azimuth: float) -> str:
    if label == "covered":
        return "Marked as covered by users, so it counts as shaded."
    if label == "unknown":
        return "Shade unknown: there is no building height data nearby, so it counts as direct sun."
    if label == "sun":
        return "Direct sun: no building blocks the sun here at this time."
    if any(detail.get("cause") == "night" for detail in details):
        return "No direct sun: the sun is below the horizon at this time."
    tallest = max((detail.get("height_m", 0) for detail in details), default=0)
    return f"Shaded by buildings up to about {round(tallest)} m tall on the {compass(azimuth)} side, toward the sun."


def analyze_route(
    geometry: list[list[float]],
    travel_time: str,
    raster: HeightRaster,
    covered: list[bool] | None = None,
    model: ExposureModel | None = None,
) -> dict[str, object]:
    """Sections and sun-exposure figures for a [lon, lat] route geometry.

    ``covered[i]`` marks geometry segment i (between points i and i+1) as user-covered.
    """
    if model is None:
        latitude, longitude = (geometry[0][1], geometry[0][0]) if geometry else (0.0, 0.0)
        model = ExposureModel(raster, travel_time, latitude, longitude)
    pieces = []
    for index, (first, second) in enumerate(zip(geometry, geometry[1:])):
        segment = model.segment_pieces(first, second)
        if covered and covered[index]:
            segment = [{**piece, "label": "covered", "detail": {"cause": "covered"}} for piece in segment]
        pieces.extend(segment)

    sections: list[dict] = []
    lengths = {"shaded": 0.0, "sun": 0.0, "unknown": 0.0, "covered": 0.0}
    for piece in pieces:
        lengths[piece["label"]] += piece["length_m"]
        current = sections[-1] if sections else None
        if current and current["label"] == piece["label"]:
            current["geometry"].append(piece["geometry"][1])
            current["length_m"] += piece["length_m"]
            current["details"].append(piece["detail"])
        else:
            sections.append({
                "label": piece["label"],
                "geometry": [piece["geometry"][0], piece["geometry"][1]],
                "length_m": piece["length_m"],
                "details": [piece["detail"]],
            })

    output_sections = []
    for section in sections:
        output_sections.append({
            "label": section["label"],
            "geometry": section["geometry"],
            "length_m": round(section["length_m"], 1),
            "reason": section_reason(section["label"], section["details"], model.azimuth),
        })

    total = sum(lengths.values())
    exposed = lengths["sun"] + lengths["unknown"]
    return {
        "status": "computed",
        "sun_percent": round(exposed / total * 100, 1) if total else 0.0,
        "sun_minutes": round(exposed / WALKING_SPEED_M_PER_MIN, 1),
        "shaded_percent": round((lengths["shaded"] + lengths["covered"]) / total * 100, 1) if total else 0.0,
        "unknown_percent": round(lengths["unknown"] / total * 100, 1) if total else 0.0,
        "covered_percent": round(lengths["covered"] / total * 100, 1) if total else 0.0,
        "sun_length_m": round(exposed, 1),
        "unknown_length_m": round(lengths["unknown"], 1),
        "sections": output_sections,
        "sun_elevation_degrees": round(model.elevation, 1),
        "sun_azimuth_degrees": round(model.azimuth, 1),
    }


def distance_meters(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> float:
    earth_radius_m = 6_371_000
    start_lat, start_lon, end_lat, end_lon = map(math.radians, (start_lat, start_lon, end_lat, end_lon))
    delta_lat = end_lat - start_lat
    delta_lon = end_lon - start_lon
    value = math.sin(delta_lat / 2) ** 2 + math.cos(start_lat) * math.cos(end_lat) * math.sin(delta_lon / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(value))
