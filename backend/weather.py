"""Weather context from the keyless Open-Meteo forecast API.

UV, temperature, heat index and humidity are shown as readings for context only. They never
affect route choice or any sun-exposure figure (PRD F-07, F-10, F-11, C-03). Each value has its
own availability so one missing value never hides the others or blocks a route (F-12).
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


API_URL = "https://api.open-meteo.com/v1/forecast"
LOCAL_ZONE = ZoneInfo("Asia/Manila")
SOURCE = "Open-Meteo"
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


def heat_index_c(temperature_c: float | None, humidity_percent: float | None) -> float | None:
    """US National Weather Service heat index (Rothfusz regression with NWS adjustments)."""
    if temperature_c is None or humidity_percent is None:
        return None
    t = temperature_c * 9 / 5 + 32
    rh = humidity_percent
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (simple + t) / 2 < 80:
        index_f = simple
    else:
        index_f = (
            -42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
            - 0.00683783 * t * t - 0.05481717 * rh * rh + 0.00122874 * t * t * rh
            + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh
        )
        if rh < 13 and 80 <= t <= 112:
            index_f -= ((13 - rh) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
        elif rh > 85 and 80 <= t <= 87:
            index_f += ((rh - 85) / 10) * ((87 - t) / 5)
    return (index_f - 32) * 5 / 9


def reading(value: float | None, **extra: object) -> dict[str, object]:
    if value is None:
        return {"status": "not available"}
    return {"status": "available", "value": round(float(value), 1), **extra}


def build_weather(uv: float | None, temperature_c: float | None, humidity: float | None) -> dict[str, object]:
    """Weather context with independent availability for each reading."""
    return {
        "source": SOURCE,
        "uv": reading(uv, category=uv_category(uv)) if uv is not None else reading(None),
        "temperature_c": reading(temperature_c),
        "humidity_percent": reading(humidity),
        "heat_index_c": reading(heat_index_c(temperature_c, humidity)),
    }


def target_hour(travel_time: str) -> datetime:
    local_time = datetime.fromisoformat(travel_time.replace("Z", "+00:00"))
    local_time = local_time.replace(tzinfo=LOCAL_ZONE) if local_time.tzinfo is None else local_time.astimezone(LOCAL_ZONE)
    return local_time.replace(minute=0, second=0, microsecond=0)


def fetch_weather(latitude: float, longitude: float, travel_time: str) -> dict[str, object]:
    target = target_hour(travel_time)
    cache_key = (round(latitude, 3), round(longitude, 3), target.isoformat())
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    parameters = urlencode({
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "uv_index,temperature_2m,relative_humidity_2m",
        "timezone": "Asia/Manila",
        "past_days": 92,
        "forecast_days": 16,
    })
    try:
        request = Request(f"{API_URL}?{parameters}", headers={"User-Agent": "shades-prototype/0.2"})
        with urlopen(request, timeout=5) as response:
            hourly = json.load(response).get("hourly", {})
    except (OSError, ValueError, json.JSONDecodeError):
        # Do not cache failures, so the next request can try again.
        return build_weather(None, None, None)

    times = hourly.get("time", [])
    target_string = target.strftime("%Y-%m-%dT%H:%M")
    if target_string not in times:
        result = build_weather(None, None, None)
    else:
        index = times.index(target_string)

        def value(name: str) -> float | None:
            values = hourly.get(name, [])
            return values[index] if index < len(values) and isinstance(values[index], (int, float)) else None

        result = build_weather(value("uv_index"), value("temperature_2m"), value("relative_humidity_2m"))
    _CACHE[cache_key] = result
    return result
