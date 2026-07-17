"""NWS weather forecast service for Titan locations.

Powers the winter weather widget on /snow-plows.  Hits api.weather.gov
(free, no auth, government source) and caches results for 1 hour to be
polite + reduce latency.

NWS docs: https://www.weather.gov/documentation/services-web-api
The flow is two-step:
  1. /points/{lat},{lon}  -> returns the forecast office + gridX,gridY
  2. /gridpoints/{office}/{gx},{gy}/forecast  -> returns 7-day forecast
We hard-code step 1 results so we don't hit the points endpoint every time
(the gridpoints don't change for a fixed lat/lon).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


# (display name, NWS forecast URL, headline location)
# Resolved once via /points/{lat},{lon} and pinned here.
LOCATIONS: dict[str, dict[str, str]] = {
    "spokane": {
        "name": "Spokane HQ",
        "headline": "E Sprague, Spokane Valley WA",
        "forecast_url": "https://api.weather.gov/gridpoints/OTX/140,90/forecast",
    },
    "boise": {
        "name": "Boise",
        "headline": "Garden City / Boise ID",
        "forecast_url": "https://api.weather.gov/gridpoints/BOI/154,80/forecast",
    },
}

USER_AGENT = "NelsonTruckEquipment/0.1 (sales@nelsontruck.com)"
CACHE_TTL_SEC = 3600  # 1 hour — NWS asks polite consumers to cache

# In-process cache: { location_key: (timestamp, payload) }
_cache: dict[str, tuple[float, dict]] = {}


@dataclass
class ForecastPeriod:
    name: str               # "Tonight", "Wednesday", "Wednesday Night", ...
    is_daytime: bool
    temperature: int        # in temperatureUnit
    temperature_unit: str   # "F" or "C"
    short_forecast: str     # "Slight Chance Rain Showers then Mostly Cloudy"
    detailed_forecast: str  # full sentence-form forecast
    pop: int | None         # probability of precipitation 0-100, or None
    wind_speed: str         # "1 to 6 mph"
    wind_direction: str     # "S"
    icon_url: str           # NWS-hosted icon URL


def _classify_snow_risk(period: dict) -> str:
    """Heuristic: derive a snow risk tier from short_forecast + temperature.

    Tiers: 'snow' (active/likely snow), 'wintry' (mix/freezing), 'cold' (no
    precipitation but cold enough that a storm would be snow), 'none'.

    The widget uses this to highlight which days a contractor should be
    prepping their plow.  Customers in our market care about THIS more than
    the raw temp.
    """
    short = (period.get("shortForecast") or "").lower()
    temp = period.get("temperature") or 0
    pop = (period.get("probabilityOfPrecipitation") or {}).get("value") or 0

    if any(k in short for k in ("snow", "blizzard", "flurr", "ice pellet")):
        return "snow"
    if any(k in short for k in ("wintry", "freezing rain", "sleet", "ice", "freezing")):
        return "wintry"
    if temp <= 32 and pop >= 30:
        # Cold + precip — likely snow even if forecast text says "rain"
        return "snow"
    if temp <= 32:
        return "cold"
    return "none"


def _to_period(p: dict) -> dict:
    """Trim the NWS period dict to what the frontend needs."""
    return {
        "name": p.get("name", ""),
        "is_daytime": p.get("isDaytime", True),
        "temperature": p.get("temperature"),
        "temperature_unit": p.get("temperatureUnit", "F"),
        "short_forecast": p.get("shortForecast", ""),
        "detailed_forecast": p.get("detailedForecast", ""),
        "pop": (p.get("probabilityOfPrecipitation") or {}).get("value"),
        "wind_speed": p.get("windSpeed", ""),
        "wind_direction": p.get("windDirection", ""),
        "icon_url": p.get("icon", ""),
        "snow_risk": _classify_snow_risk(p),
        "start_time": p.get("startTime"),
        "end_time": p.get("endTime"),
    }


async def fetch_forecast(location_key: str) -> dict:
    """Async fetch from NWS for a single Titan location.  Cached for 1h."""
    if location_key not in LOCATIONS:
        raise ValueError(f"Unknown location: {location_key}")

    # Cache hit?
    now = time.time()
    if location_key in _cache:
        ts, payload = _cache[location_key]
        if now - ts < CACHE_TTL_SEC:
            return payload

    loc = LOCATIONS[location_key]
    url = loc["forecast_url"]
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json()

    periods = [_to_period(p) for p in data.get("properties", {}).get("periods", [])]
    payload = {
        "key": location_key,
        "name": loc["name"],
        "headline": loc["headline"],
        "updated_at": data.get("properties", {}).get("updated"),
        "periods": periods,
    }
    _cache[location_key] = (now, payload)
    return payload


async def fetch_all_locations() -> list[dict]:
    """Fetch forecasts for every Titan location in parallel."""
    import asyncio
    tasks = [fetch_forecast(k) for k in LOCATIONS]
    return list(await asyncio.gather(*tasks))
