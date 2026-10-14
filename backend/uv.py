"""Optional UV context from the keyless Open-Meteo forecast API."""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


API_URL = "https://api.open-meteo.com/v1/forecast"
LOCAL_ZONE = ZoneInfo("Asia/Manila")
_CACHE: dict[tuple[float, float, str], dict[str, object]] = {}


def uv_category(value: float) -> str:
    if value < 3:
        return "Low"
    if value < 6:
        return "Moderate"
    if value < 8:
        return "High"
    if value < 11:
        return "Very high"
    return "Extreme"


def fetch_uv_context(latitude: float, longitude: float, travel_time: str) -> dict[str, object]:
    local_time = datetime.fromisoformat(travel_time.replace("Z", "+00:00"))
    if local_time.tzinfo is None:
        local_time = local_time.replace(tzinfo=LOCAL_ZONE)
    else:
        local_time = local_time.astimezone(LOCAL_ZONE)
    target = local_time.replace(minute=0, second=0, microsecond=0)
    cache_key = (round(latitude, 3), round(longitude, 3), target.isoformat())
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    parameters = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "uv_index",
            "timezone": "Asia/Manila",
            "past_days": 92,
            "forecast_days": 16,
        }
    )
    try:
        request = Request(f"{API_URL}?{parameters}", headers={"User-Agent": "shades-prototype/0.1"})
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
        times = payload.get("hourly", {}).get("time", [])
        values = payload.get("hourly", {}).get("uv_index", [])
        target_string = target.strftime("%Y-%m-%dT%H:%M")
        if target_string not in times:
            return {"status": "unavailable", "message": "UV data is not available for the selected time."}
        value = values[times.index(target_string)]
        if value is None:
            return {"status": "unavailable", "message": "UV data is not available for the selected time."}
        result = {
            "status": "available",
            "index": round(float(value), 1),
            "category": uv_category(float(value)),
            "source": "Open-Meteo",
        }
    except (OSError, ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError):
        result = {"status": "unavailable", "message": "UV data could not be retrieved."}

    _CACHE[cache_key] = result
    return result