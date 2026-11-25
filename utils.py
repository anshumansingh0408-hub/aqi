"""Utility functions for input validation, sanitization, rate limiting, and formatting.

Provides helpers for the Saans air quality advisory system.
"""

import hashlib
import time
from typing import Any, Optional
import unicodedata


def sanitize_text_input(text: str, max_length: int) -> str:
    """Sanitize text input by removing control characters, stripping, and truncating.

    Args:
        text: Raw input string to clean.
        max_length: Maximum allowed character length.

    Returns:
        Cleaned, stripped, and truncated string.
    """
    if not text:
        return ""
    filtered = "".join(
        ch for ch in str(text)
        if ch != "\x00" and (unicodedata.category(ch)[0] != "C" or ch in ("\r", "\n", "\t"))
    )
    trimmed = filtered.strip()
    return trimmed[:max_length] if max_length > 0 else trimmed


def generate_cache_key(*parts: str) -> str:
    """Generate an MD5 hex digest cache key from string parts.

    Args:
        *parts: Variable length string components.

    Returns:
        Hexadecimal 32-character MD5 hash string.
    """
    joined = ":".join(str(p) for p in parts)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def check_rate_limit(
    ip: str, tracker: dict[str, list[float]], max_requests: int,
    window_seconds: int, current_time: Optional[float] = None,
) -> bool:
    """Sliding window rate limit checker mutating the tracker dictionary.

    Args:
        ip: Client IP address string.
        tracker: Dict mapping IP to request timestamps.
        max_requests: Max requests in window.
        window_seconds: Window interval in seconds.
        current_time: Optional explicit timestamp for testing.

    Returns:
        True if permitted, False if rate limited.
    """
    now = time.time() if current_time is None else current_time
    cutoff = now - window_seconds
    timestamps = [t for t in tracker.get(ip, []) if t > cutoff]
    if len(timestamps) >= max_requests:
        tracker[ip] = timestamps
        return False
    timestamps.append(now)
    tracker[ip] = timestamps
    return True


def format_pm25(value: float) -> str:
    """Format PM2.5 value with one decimal place and unit.

    Args:
        value: PM2.5 concentration in micrograms per cubic meter.

    Returns:
        Formatted string (e.g. '142.5 µg/m3').
    """
    return f"{value:.1f} µg/m3"


def _validate_city(data: dict[str, Any], cleaned: dict[str, Any], errors: list[str]) -> None:
    """Validate and sanitize city name input.

    Args:
        data: Raw input dictionary.
        cleaned: Cleaned output dictionary.
        errors: Error accumulator list.
    """
    raw_city = data.get("city")
    if not isinstance(raw_city, str):
        errors.append("city must be between 2 and 60 characters.")
        cleaned["city"] = ""
        return
    city = sanitize_text_input(raw_city, 60)
    if 2 <= len(city) <= 60:
        cleaned["city"] = city
    else:
        errors.append("city must be between 2 and 60 characters.")
        cleaned["city"] = city


def _validate_household_counts(
    hh: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate children and elderly counts in household.

    Args:
        hh: Household dictionary.
        cleaned: Cleaned household dictionary.
        errors: Error accumulator list.
    """
    for key in ("children", "elderly"):
        val = hh.get(key, 0)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or int(val) != val:
            errors.append(f"household.{key} must be a whole number from 0 to 10.")
            cleaned[key] = 0
        elif 0 <= int(val) <= 10:
            cleaned[key] = int(val)
        else:
            errors.append(f"household.{key} must be a whole number from 0 to 10.")
            cleaned[key] = 0


def _validate_household_flags(
    hh: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate respiratory, heart, and pregnancy health flags.

    Args:
        hh: Household dictionary.
        cleaned: Cleaned household dictionary.
        errors: Error accumulator list.
    """
    for key in ("respiratory", "heart", "pregnant"):
        val = hh.get(key, False)
        if type(val) is bool:
            cleaned[key] = val
        else:
            errors.append(f"household.{key} must be a boolean.")
            cleaned[key] = False


def _validate_household(data: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    """Validate household demographics and health vulnerabilities.

    Args:
        data: Raw payload dictionary.
        errors: Error accumulator list.

    Returns:
        Cleaned household dictionary.
    """
    raw_hh = data.get("household")
    cleaned = {"children": 0, "elderly": 0, "respiratory": False, "heart": False, "pregnant": False}
    if not isinstance(raw_hh, dict):
        errors.append("household must be an object.")
        return cleaned
    _validate_household_counts(raw_hh, cleaned, errors)
    _validate_household_flags(raw_hh, cleaned, errors)
    return cleaned


def _validate_heating_cooking(
    ls: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate heating and cooking fuels in lifestyle.

    Args:
        ls: Lifestyle dictionary.
        cleaned: Cleaned lifestyle dictionary.
        errors: Error accumulator list.
    """
    heat = ls.get("heating", "none")
    if heat in ("electric", "gas", "biomass", "none"):
        cleaned["heating"] = heat
    else:
        errors.append("lifestyle.heating must be one of: electric, gas, biomass, none.")
        cleaned["heating"] = "none"
    cook = ls.get("cooking", "lpg")
    if cook in ("lpg", "induction", "biomass"):
        cleaned["cooking"] = cook
    else:
        errors.append("lifestyle.cooking must be one of: lpg, induction, biomass.")
        cleaned["cooking"] = "lpg"


def _validate_lifestyle_flags(
    ls: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate purifier ownership and smoker flags.

    Args:
        ls: Lifestyle dictionary.
        cleaned: Cleaned lifestyle dictionary.
        errors: Error accumulator list.
    """
    for key in ("has_purifier", "smokers"):
        val = ls.get(key, False)
        if type(val) is bool:
            cleaned[key] = val
        else:
            errors.append(f"lifestyle.{key} must be a boolean.")
            cleaned[key] = False


COMMUTE_MODES = (
    "car_petrol", "car_diesel", "car_electric", "two_wheeler",
    "bus", "metro_train", "walk_cycle",
)


def _validate_commute_mode_km(
    ls: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate commute mode and distance.

    Args:
        ls: Lifestyle dictionary.
        cleaned: Cleaned lifestyle dictionary.
        errors: Error accumulator list.
    """
    mode = ls.get("commute_mode", "car_petrol")
    if mode in COMMUTE_MODES:
        cleaned["commute_mode"] = mode
    else:
        errors.append(f"lifestyle.commute_mode must be one of: {', '.join(COMMUTE_MODES)}.")
        cleaned["commute_mode"] = "car_petrol"
    km = ls.get("commute_km_one_way", 0.0)
    is_num = not isinstance(km, bool) and isinstance(km, (int, float))
    if is_num and 0.0 <= float(km) <= 200.0:
        cleaned["commute_km_one_way"] = float(km)
    else:
        errors.append("lifestyle.commute_km_one_way must be a number from 0 to 200.")
        cleaned["commute_km_one_way"] = 0.0


def _validate_commute_days(
    ls: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate commute days per week.

    Args:
        ls: Lifestyle dictionary.
        cleaned: Cleaned lifestyle dictionary.
        errors: Error accumulator list.
    """
    days = ls.get("commute_days_per_week", 0)
    is_valid_days = (
        not isinstance(days, bool)
        and isinstance(days, (int, float))
        and int(days) == days
        and 0 <= int(days) <= 7
    )
    if not is_valid_days:
        errors.append("lifestyle.commute_days_per_week must be a whole number from 0 to 7.")
        cleaned["commute_days_per_week"] = 0
    else:
        cleaned["commute_days_per_week"] = int(days)


def _validate_room_area(
    ls: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate room area in square meters.

    Args:
        ls: Lifestyle dictionary.
        cleaned: Cleaned lifestyle dictionary.
        errors: Error accumulator list.
    """
    area = ls.get("room_area_sqm", 20.0)
    is_valid_area = (
        not isinstance(area, bool)
        and isinstance(area, (int, float))
        and 5.0 <= float(area) <= 200.0
    )
    if not is_valid_area:
        errors.append("lifestyle.room_area_sqm must be a number from 5 to 200.")
        cleaned["room_area_sqm"] = 20.0
    else:
        cleaned["room_area_sqm"] = float(area)


def _validate_outdoor_hour(
    ls: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate usual outdoor exercise hour.

    Args:
        ls: Lifestyle dictionary.
        cleaned: Cleaned lifestyle dictionary.
        errors: Error accumulator list.
    """
    hr = ls.get("usual_outdoor_hour", 8)
    is_valid_hr = (
        not isinstance(hr, bool)
        and isinstance(hr, (int, float))
        and int(hr) == hr
        and 0 <= int(hr) <= 23
    )
    if not is_valid_hr:
        errors.append("lifestyle.usual_outdoor_hour must be a whole number from 0 to 23.")
        cleaned["usual_outdoor_hour"] = 8
    else:
        cleaned["usual_outdoor_hour"] = int(hr)


def _default_lifestyle() -> dict[str, Any]:
    """Provide default lifestyle dictionary.

    Returns:
        Dict with default values.
    """
    return {
        "heating": "none", "cooking": "lpg", "has_purifier": False, "smokers": False,
        "commute_mode": "car_petrol", "commute_km_one_way": 0.0,
        "commute_days_per_week": 0, "room_area_sqm": 20.0, "usual_outdoor_hour": 8,
    }


def _validate_lifestyle(data: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    """Validate lifestyle choices and housing specifications.

    Args:
        data: Raw payload dictionary.
        errors: Error accumulator list.

    Returns:
        Cleaned lifestyle dictionary.
    """
    raw_ls = data.get("lifestyle")
    cleaned = _default_lifestyle()
    if not isinstance(raw_ls, dict):
        errors.append("lifestyle must be an object.")
        return cleaned
    _validate_heating_cooking(raw_ls, cleaned, errors)
    _validate_lifestyle_flags(raw_ls, cleaned, errors)
    _validate_commute_mode_km(raw_ls, cleaned, errors)
    _validate_commute_days(raw_ls, cleaned, errors)
    _validate_room_area(raw_ls, cleaned, errors)
    _validate_outdoor_hour(raw_ls, cleaned, errors)
    return cleaned


def _validate_manual_and_notes(
    data: dict[str, Any], cleaned: dict[str, Any], errors: list[str]
) -> None:
    """Validate optional manual PM2.5 reading and notes fields.

    Args:
        data: Raw payload dictionary.
        cleaned: Cleaned output dictionary.
        errors: Error accumulator list.
    """
    raw_pm = data.get("manual_pm25")
    if raw_pm is not None:
        is_num = not isinstance(raw_pm, bool) and isinstance(raw_pm, (int, float))
        if is_num and 0.0 <= float(raw_pm) <= 1000.0:
            cleaned["manual_pm25"] = float(raw_pm)
        else:
            errors.append("manual_pm25 must be a number from 0 to 1000 or null.")
            cleaned["manual_pm25"] = None
    else:
        cleaned["manual_pm25"] = None
    notes = data.get("notes")
    cleaned["notes"] = sanitize_text_input(str(notes), 300) if notes is not None else ""


def validate_inputs(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate and sanitize user submission payload, accumulating all validation errors.

    Args:
        data: Unsanitized input dictionary from form or JSON request.

    Returns:
        Tuple containing cleaned data dictionary and list of validation error strings.
    """
    errors: list[str] = []
    cleaned: dict[str, Any] = {}
    _validate_city(data, cleaned, errors)
    cleaned["household"] = _validate_household(data, errors)
    cleaned["lifestyle"] = _validate_lifestyle(data, errors)
    _validate_manual_and_notes(data, cleaned, errors)
    return cleaned, errors
