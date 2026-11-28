"""Fetches a PM2.5 reading and a 24-hour forecast for a city from Open-Meteo.

No API key needed, with caching, timeouts and a manual fallback. The data comes
from atmospheric model estimates, not a ground sensor, so it can differ from
nearby monitoring stations.
"""

import datetime
import logging
import threading
import time
from typing import Any, Optional
import requests

logger = logging.getLogger(__name__)

# Configuration
GEOCODE_URL: str = "https://geocoding-api.open-meteo.com/v1/search"
AIR_URL: str = "https://air-quality-api.open-meteo.com/v1/air-quality"
CONFIG: dict[str, int] = {
    "TIMEOUT_SECONDS": 8,
    "MAX_RESPONSE_BYTES": 500000,
    "AIR_CACHE_TTL": 900,
    "GEOCODE_CACHE_TTL": 86400,
    "CACHE_MAX_ENTRIES": 300,
    "FORECAST_HOURS": 24,
}
SOURCE_NOTE: str = (
    "Estimated from an atmospheric model via Open-Meteo. It can differ from "
    "nearby ground monitors, so you can enter a reading yourself."
)
_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()


class AirDataError(Exception):
    """Exception raised for air quality service and parsing errors."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize with an error code and user-safe message.

        Args:
            code: Machine-readable error code ('CITY_NOT_FOUND', 'AIR_UNAVAILABLE', 'BAD_RESPONSE').
            message: User-safe error description.
        """
        super().__init__(message)
        self.code = code
        self.message = message


def _clone(val: Any) -> Any:
    """Create a deep copy of primitives, dicts, and lists without mutating cache.

    Args:
        val: Value to copy.

    Returns:
        Deep copy of the provided value.
    """
    if isinstance(val, dict):
        return {k: _clone(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_clone(v) for v in val]
    return val


def _evict_cache(now: float) -> None:
    """Drop expired and oldest cache entries when exceeding limits.

    Args:
        now: Current timestamp in seconds.
    """
    expired = [k for k, v in _CACHE.items() if now - v["created_at"] > v.get("ttl", 86400)]
    for k in expired:
        _CACHE.pop(k, None)
    while len(_CACHE) >= CONFIG["CACHE_MAX_ENTRIES"]:
        oldest = min(_CACHE.keys(), key=lambda k: _CACHE[k]["created_at"])
        _CACHE.pop(oldest, None)


def get_cached(key: str, ttl: int) -> Optional[Any]:
    """Retrieve an unexpired value copy from the cache.

    Args:
        key: Cache key string.
        ttl: Maximum age in seconds before expiring.

    Returns:
        Deep copy of the cached value, or None if expired/missing.
    """
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        if time.time() - entry["created_at"] > ttl:
            _CACHE.pop(key, None)
            return None
        return _clone(entry["value"])


def set_cached(key: str, value: Any, ttl: Optional[int] = None) -> None:
    """Store value in the cache with timestamp and eviction.

    Args:
        key: Unique cache key string.
        value: Any serializable object to store.
        ttl: Optional time-to-live in seconds.
    """
    def_ttl = CONFIG["GEOCODE_CACHE_TTL"] if key.startswith("geo:") else CONFIG["AIR_CACHE_TTL"]
    entry_ttl = ttl if ttl is not None else def_ttl
    now = time.time()
    with _CACHE_LOCK:
        _evict_cache(now)
        _CACHE[key] = {"value": _clone(value), "created_at": now, "ttl": entry_ttl}


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute HTTP GET request and safely decode JSON response object.

    Args:
        url: Service endpoint URL.
        params: URL query parameters dictionary.

    Returns:
        Decoded JSON dictionary.

    Raises:
        AirDataError: On timeout, HTTP error, size overflow, or bad format.
    """
    try:
        resp = requests.get(url, params=params, timeout=CONFIG["TIMEOUT_SECONDS"])
    except (requests.Timeout, requests.ConnectionError, requests.RequestException) as exc:
        logger.warning("Air quality HTTP request failed: %s", exc)
        raise AirDataError("AIR_UNAVAILABLE", "The air quality service is not responding.")
    if resp.status_code != 200:
        raise AirDataError("AIR_UNAVAILABLE", "The air quality service is not responding.")
    if len(resp.content) > CONFIG["MAX_RESPONSE_BYTES"]:
        raise AirDataError("BAD_RESPONSE", "The service response exceeded the maximum size limit.")
    try:
        data = resp.json()
    except Exception:
        raise AirDataError("BAD_RESPONSE", "The service returned an unparseable response.")
    if not isinstance(data, dict):
        raise AirDataError("BAD_RESPONSE", "The service response format was unexpected.")
    return data


def _validate_coords(first: dict[str, Any]) -> tuple[float, float]:
    """Validate latitude and longitude from geocoding result.

    Args:
        first: First geocoding result item.

    Returns:
        Tuple of validated (latitude, longitude) floats.

    Raises:
        AirDataError: If coordinates are missing, non-numeric, or out of range.
    """
    lat, lon = first.get("latitude"), first.get("longitude")
    if isinstance(lat, bool) or isinstance(lon, bool) or not isinstance(lat, (int, float)):
        raise AirDataError("BAD_RESPONSE", "Geocoding returned an invalid latitude coordinate.")
    if not isinstance(lon, (int, float)):
        raise AirDataError("BAD_RESPONSE", "Geocoding returned an invalid longitude coordinate.")
    flat, flon = float(lat), float(lon)
    if not (-90.0 <= flat <= 90.0 and -180.0 <= flon <= 180.0):
        raise AirDataError("BAD_RESPONSE", "Geocoding coordinates outside geographical limits.")
    return flat, flon


def _extract_alternatives(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract up to 3 alternative geocoding locations.

    Args:
        results: Full results list from geocoding API.

    Returns:
        List of alternative location dictionaries.
    """
    return [
        {
            "name": r.get("name", ""),
            "admin1": r.get("admin1", ""),
            "country": r.get("country", ""),
        }
        for r in results[1:4]
    ]


def _fetch_geocode_results(city: str) -> list[dict[str, Any]]:
    """Query geocoding API and validate non-empty results list.

    Args:
        city: City name query string.

    Returns:
        List of location result dictionaries.

    Raises:
        AirDataError: If city is not found or results are missing.
    """
    params = {"name": city.strip(), "count": 5, "language": "en", "format": "json"}
    data = _get_json(GEOCODE_URL, params)
    results = data.get("results")
    if not results or not isinstance(results, list):
        msg = "We could not find that city. Check the spelling or enter today's PM2.5 yourself."
        raise AirDataError("CITY_NOT_FOUND", msg)
    return results


def geocode_city(city: str) -> dict[str, Any]:
    """Resolve a city name to geographical coordinates with caching.

    Args:
        city: City name string.

    Returns:
        Dictionary with name, admin1, country, latitude, longitude, and alternatives.

    Raises:
        AirDataError: When city cannot be found or coordinates are invalid.
    """
    key = "geo:" + city.strip().lower()
    cached = get_cached(key, CONFIG["GEOCODE_CACHE_TTL"])
    if cached is not None:
        return cached
    results = _fetch_geocode_results(city)
    first = results[0]
    lat, lon = _validate_coords(first)
    res = {
        "name": first.get("name", ""), "admin1": first.get("admin1", ""),
        "country": first.get("country", ""), "latitude": lat, "longitude": lon,
        "alternatives": _extract_alternatives(results),
    }
    set_cached(key, res, CONFIG["GEOCODE_CACHE_TTL"])
    return res


def _clean_pm(val: Any) -> Optional[float]:
    """Sanitize raw PM2.5 value, treating negative or non-numeric values as None.

    Args:
        val: Raw concentration value.

    Returns:
        Float concentration or None.
    """
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        return f if f >= 0.0 else None
    except (ValueError, TypeError):
        return None


def _find_start_hour_index(times: list[str], cur_hour_str: str) -> int:
    """Find index of the first hourly entry at or after the current hour.

    Args:
        times: List of hourly timestamp strings.
        cur_hour_str: Truncated current hour ISO string.

    Returns:
        Starting index in times list.
    """
    for idx, t in enumerate(times):
        if t >= cur_hour_str:
            return idx
    return len(times)


def _build_forward_hourly(
    times: list[str], pms: list[Any], start_idx: int
) -> list[dict[str, Any]]:
    """Build forward hourly forecast window up to FORECAST_HOURS.

    Args:
        times: List of hourly ISO timestamps.
        pms: Parallel list of raw PM2.5 concentrations.
        start_idx: Starting index for forward window.

    Returns:
        List of hourly forecast dictionaries with time and pm25 fields.
    """
    limit = min(start_idx + CONFIG["FORECAST_HOURS"], len(times))
    res: list[dict[str, Any]] = []
    for i in range(start_idx, limit):
        val = _clean_pm(pms[i]) if i < len(pms) else None
        res.append({"time": times[i], "pm25": val})
    return res


def _parse_current_hour(c_time: str) -> str:
    """Format the current observation time truncated to the hour.

    Args:
        c_time: Observation ISO timestamp string.

    Returns:
        Truncated hour string (YYYY-MM-DDTHH:00).
    """
    try:
        dt = datetime.datetime.fromisoformat(c_time)
        return dt.strftime("%Y-%m-%dT%H:00")
    except (ValueError, TypeError):
        return c_time[:13] + ":00" if len(c_time) >= 13 else ""


def parse_air_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse Open-Meteo air quality response into structured forecast data.

    Args:
        payload: Decoded response dictionary from air quality API.

    Returns:
        Dictionary with current pm25, hourly forecast list, and observed_at string.

    Raises:
        AirDataError: When essential air quality data is missing.
    """
    cur = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    c_time = str(cur.get("time", ""))
    cur_hour = _parse_current_hour(c_time)
    times = hourly.get("time", []) if isinstance(hourly.get("time"), list) else []
    pms = hourly.get("pm2_5", []) if isinstance(hourly.get("pm2_5"), list) else []
    start_idx = _find_start_hour_index(times, cur_hour)
    forward = _build_forward_hourly(times, pms, start_idx)
    pm25 = _clean_pm(cur.get("pm2_5"))
    if pm25 is None and start_idx < len(times) and times[start_idx][:13] == cur_hour[:13]:
        pm25 = _clean_pm(pms[start_idx]) if start_idx < len(pms) else None
    if pm25 is None:
        raise AirDataError("BAD_RESPONSE", "The air quality data was incomplete.")
    return {"pm25": pm25, "hourly": forward, "observed_at": c_time}


def fetch_air_quality(latitude: float, longitude: float) -> dict[str, Any]:
    """Fetch and parse air quality forecast for coordinates with caching.

    Args:
        latitude: Geographical latitude float.
        longitude: Geographical longitude float.

    Returns:
        Parsed air quality dictionary.
    """
    key = f"air:{latitude:.2f}:{longitude:.2f}"
    cached = get_cached(key, CONFIG["AIR_CACHE_TTL"])
    if cached is not None:
        return cached
    params = {
        "latitude": latitude, "longitude": longitude, "current": "pm2_5",
        "hourly": "pm2_5", "forecast_days": 2, "timezone": "auto",
    }
    data = _get_json(AIR_URL, params)
    res = parse_air_response(data)
    set_cached(key, res, CONFIG["AIR_CACHE_TTL"])
    return res


def get_air_reading(city: str, manual_pm25: Optional[float] = None) -> dict[str, Any]:
    """Retrieve air reading and forecast for city or return manual override.

    Args:
        city: Target city name.
        manual_pm25: Optional user-supplied manual PM2.5 concentration.

    Returns:
        Full air reading schema dictionary with location, readings, and source.
    """
    if manual_pm25 is not None:
        return {
            "pm25": float(manual_pm25), "hourly": [], "source": "manual",
            "observed_at": "entered by you", "location": None,
            "source_note": "Value entered by you.",
        }
    geo = geocode_city(city)
    air = fetch_air_quality(geo["latitude"], geo["longitude"])
    loc = {
        "name": geo["name"], "admin1": geo["admin1"], "country": geo["country"],
        "alternatives": geo.get("alternatives", []),
    }
    return {
        "pm25": air["pm25"], "hourly": air["hourly"], "source": "live",
        "observed_at": air["observed_at"], "location": loc, "source_note": SOURCE_NOTE,
    }
