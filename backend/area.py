"""The study area (PRD O-01) and the routing-tile grid. Single source of truth for the backend;
the frontend reads the area from /api/health.

Metro Manila. Building heights exist only inside the Quezon City height raster
(`datasets/building-heights/2026_HEIGHT_GVSSM.tif`); elsewhere sections are "shade unknown",
which counts as direct sun (PRD E-03).
"""

from __future__ import annotations

import math
from datetime import timedelta, timezone

# Manila time. A fixed offset (the Philippines has no daylight saving), because some hosts have
# no time-zone database.
LOCAL_ZONE = timezone(timedelta(hours=8), "Asia/Manila")

STUDY_AREA = {
    "name": "Metro Manila",
    "south": 14.35,
    "north": 14.79,
    "west": 120.90,
    "east": 121.15,
}

# Routing tiles are TILE_DEG × TILE_DEG degrees (about 2.2 km). Build and runtime must agree.
TILE_DEG = 0.02
COORD_DECIMALS = 7

# Ateneo / Katipunan: where the map opens, and where place search ranks from when no trip point is set.
HOME = (14.6400, 121.0770)
# Longest walking trip, straight-line, that the API will route (user decision).
MAX_TRIP_M = 10_000
# Longest walking route searched for (detours make walks longer than the straight line).
MAX_WALK_M = 15_000


def tile_of(latitude: float, longitude: float) -> tuple[int, int]:
    """Tile (column, row) holding a point. Coordinates must already be rounded to COORD_DECIMALS."""
    return (
        math.floor((longitude - STUDY_AREA["west"]) / TILE_DEG),
        math.floor((latitude - STUDY_AREA["south"]) / TILE_DEG),
    )


def in_study_area(latitude: float, longitude: float) -> bool:
    return STUDY_AREA["south"] <= latitude <= STUDY_AREA["north"] and STUDY_AREA["west"] <= longitude <= STUDY_AREA["east"]
