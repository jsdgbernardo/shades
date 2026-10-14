"""Approximate route shade analysis using the local building-height GeoTIFF."""

from __future__ import annotations

import math
import struct
from array import array
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


HEIGHT_PATH = Path(__file__).parents[1] / "datasets" / "building-heights" / "2026_HEIGHT_GVSSM.tif"
LOCAL_ZONE = ZoneInfo("Asia/Manila")


class HeightRaster:
    def __init__(self, width: int, height: int, origin_lon: float, origin_lat: float, pixel_size: float, values: array) -> None:
        self.width = width
        self.height = height
        self.origin_lon = origin_lon
        self.origin_lat = origin_lat
        self.pixel_size = pixel_size
        self.values = values

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
        raster_values = array("f", [0.0]) * (width * height)

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
                    raster_values[target] = value if math.isfinite(value) and 0 <= value < 1000 else 0.0

        return cls(width, height, origin_lon, origin_lat, pixel_size, raster_values)

    def height_at(self, latitude: float, longitude: float) -> float:
        column = int((longitude - self.origin_lon) / self.pixel_size)
        row = int((self.origin_lat - latitude) / self.pixel_size)
        if not (0 <= column < self.width and 0 <= row < self.height):
            return 0.0
        return float(self.values[row * self.width + column])


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


def solar_position(travel_time: str, latitude: float, longitude: float) -> tuple[float, float]:
    parsed = datetime.fromisoformat(travel_time.replace("Z", "+00:00"))
    local_time = parsed.replace(tzinfo=LOCAL_ZONE) if parsed.tzinfo is None else parsed.astimezone(LOCAL_ZONE)
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


def analyze_route(geometry: list[list[float]], travel_time: str, raster: HeightRaster) -> dict[str, object]:
    if len(geometry) < 2:
        return {"status": "computed", "sun_exposed_percent": 0, "shaded_percent": 0, "rating": "No route segment"}

    elevation, azimuth = solar_position(travel_time, geometry[0][1], geometry[0][0])
    exposed_distance = 0.0
    shaded_distance = 0.0
    segments = []
    for first, second in zip(geometry, geometry[1:]):
        distance = distance_meters(first[1], first[0], second[1], second[0])
        midpoint_lon = (first[0] + second[0]) / 2
        midpoint_lat = (first[1] + second[1]) / 2
        shade_level = shadow_level(midpoint_lat, midpoint_lon, elevation, azimuth, raster)
        shaded = shade_level > 0
        status = "shaded" if shaded else "sun-exposed"
        if shaded:
            shaded_distance += distance
        else:
            exposed_distance += distance
        segments.append({"geometry": [first, second], "status": status, "shade_level": shade_level})

    total = exposed_distance + shaded_distance
    exposed_percent = round(exposed_distance / total * 100, 1) if total else 0
    rating = "Low exposure" if exposed_percent < 35 else "Moderate exposure" if exposed_percent < 70 else "High exposure"
    return {
        "status": "computed",
        "sun_exposed_percent": exposed_percent,
        "shaded_percent": round(100 - exposed_percent, 1),
        "rating": rating,
        "segments": segments,
        "sun_elevation_degrees": round(elevation, 1),
    }


def shadow_level(latitude: float, longitude: float, elevation: float, azimuth: float, raster: HeightRaster) -> int:
    if elevation <= 0:
        return 4
    elevation_radians = math.radians(elevation)
    meters_per_degree_lat = 111_320
    meters_per_degree_lon = 111_320 * math.cos(math.radians(latitude))
    toward_sun_east = math.sin(math.radians(azimuth))
    toward_sun_north = math.cos(math.radians(azimuth))
    highest_level = 0
    for distance in range(2, 201, 2):
        sample_lat = latitude + toward_sun_north * distance / meters_per_degree_lat
        sample_lon = longitude + toward_sun_east * distance / meters_per_degree_lon
        building_height = raster.height_at(sample_lat, sample_lon)
        clearance = 1.7 + distance * math.tan(elevation_radians)
        if building_height > clearance:
            ratio = building_height / max(clearance, 1)
            highest_level = max(highest_level, min(4, 1 + int(ratio)))
    return highest_level


def distance_meters(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> float:
    earth_radius_m = 6_371_000
    start_lat, start_lon, end_lat, end_lon = map(math.radians, (start_lat, start_lon, end_lat, end_lon))
    delta_lat = end_lat - start_lat
    delta_lon = end_lon - start_lon
    value = math.sin(delta_lat / 2) ** 2 + math.cos(start_lat) * math.cos(end_lat) * math.sin(delta_lon / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(value))