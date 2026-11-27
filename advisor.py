"""Pure, stateless advice logic for winter smog.

No Flask or network dependencies. It turns a PM2.5 reading, an optional hourly
PM2.5 forecast and a household profile into precautions, safer time windows,
commute comparisons, purifier sizing and an indoor checklist. It gives general
precautions, not medical advice.
"""

import datetime
import math
from typing import Any, Optional

# Assumption to verify against CPCB's published AQI breakpoints; not a measured fact.
# Hourly readings are not the 24-hour average CPCB uses,
# so any band derived from them is approximate.
PM25_BANDS: list[dict[str, Any]] = [
    {"key": "good", "label": "Good", "min": 0, "max": 30},
    {"key": "satisfactory", "label": "Satisfactory", "min": 31, "max": 60},
    {"key": "moderate", "label": "Moderate", "min": 61, "max": 90},
    {"key": "poor", "label": "Poor", "min": 91, "max": 120},
    {"key": "very_poor", "label": "Very Poor", "min": 121, "max": 250},
    {"key": "severe", "label": "Severe", "min": 251, "max": None},
]

# Assumption to verify against public health risk tier frameworks; not a measured fact.
TIERS: tuple[str, ...] = ("normal", "caution", "restrict", "avoid")

# Assumption to verify against health advisory action matrices; not a measured fact.
TIER_BY_BAND: dict[str, tuple[str, str]] = {
    "good": ("normal", "normal"),
    "satisfactory": ("normal", "caution"),
    "moderate": ("caution", "restrict"),
    "poor": ("restrict", "avoid"),
    "very_poor": ("avoid", "avoid"),
    "severe": ("avoid", "avoid"),
}

# Assumption to verify against diurnal smog dispersion and exposure patterns; not a measured fact.
ACTIVITY_HOURS: dict[str, tuple[int, int]] = {
    "outdoor_exercise": (6, 20),
    "errands": (8, 19),
    "window_ventilation": (9, 17),
    "kids_outdoor_play": (8, 18),
}

# Assumption to verify against transport emissions databases; approximate planning factors.
EMISSION_FACTORS: dict[str, float] = {
    "car_petrol": 0.192,
    "car_diesel": 0.171,
    "car_electric": 0.053,
    "two_wheeler": 0.100,
    "bus": 0.089,
    "metro_train": 0.041,
    "walk_cycle": 0.0,
}

# Assumption to verify against calendar planning standards; not a measured fact.
WEEKS_PER_MONTH: float = 4.33

# Assumption to verify against architectural standards; not a measured fact.
CEILING_M: float = 2.7

# Assumption to verify against air purifier ventilation guidelines; not a measured fact.
TARGET_ACH: int = 4

# Assumption to verify against volumetric conversion standards; not a measured fact.
M3H_TO_CFM: float = 0.588

# Assumption to verify against urban mobility studies; not a measured fact.
WALK_CYCLE_MAX_KM: float = 5.0

# General health precaution advisory; not medical advice.
MEDICAL_NOTE: str = (
    "These are general precautions. If anyone in your home has a heart or lung condition, "
    "follow your doctor's advice."
)

# Climate impact disclaimer note.
CLIMATE_NOTE: str = (
    "CO2 is a climate impact. Fewer petrol and diesel trips also mean fewer local emissions, "
    "but we do not put a number on how much cleaner your street's air gets."
)


def pm25_band(pm25: float) -> dict[str, Any]:
    """Return the matching PM2.5 band dictionary for a concentration.

    Args:
        pm25: PM2.5 reading in micrograms per cubic meter.

    Returns:
        Dictionary with key, label, min, and max defining the air quality band.

    Raises:
        ValueError: If pm25 is negative or not a valid number.
    """
    if not isinstance(pm25, (int, float)) or isinstance(pm25, bool) or math.isnan(pm25) or pm25 < 0:
        raise ValueError("PM2.5 value must be a non-negative number.")
    if pm25 <= 30.0:
        return dict(PM25_BANDS[0])
    if pm25 <= 60.0:
        return dict(PM25_BANDS[1])
    if pm25 <= 90.0:
        return dict(PM25_BANDS[2])
    if pm25 <= 120.0:
        return dict(PM25_BANDS[3])
    if pm25 <= 250.0:
        return dict(PM25_BANDS[4])
    return dict(PM25_BANDS[5])


def pm25_to_aqi(pm25: float) -> int:
    """Convert PM2.5 concentration in ug/m3 to India CPCB National AQI.

    Args:
        pm25: Float PM2.5 concentration.

    Returns:
        Calculated integer Air Quality Index (0 to 500).
    """
    if not isinstance(pm25, (int, float)) or isinstance(pm25, bool) or math.isnan(pm25) or pm25 < 0:
        return 0
    if pm25 <= 30.0:
        return round((50.0 / 30.0) * pm25)
    if pm25 <= 60.0:
        return round(50.0 + (50.0 / 30.0) * (pm25 - 30.0))
    if pm25 <= 90.0:
        return round(100.0 + (100.0 / 30.0) * (pm25 - 60.0))
    if pm25 <= 120.0:
        return round(200.0 + (100.0 / 30.0) * (pm25 - 90.0))
    if pm25 <= 250.0:
        return round(300.0 + (100.0 / 130.0) * (pm25 - 120.0))
    return min(500, round(400.0 + (100.0 / 130.0) * (pm25 - 250.0)))


def household_sensitivity(household: dict[str, Any]) -> dict[str, Any]:
    """Assess household vulnerability to air pollution based on demographic profile.

    Args:
        household: Dictionary containing member counts and medical status flags.

    Returns:
        Dictionary with sensitivity flag and list of readable sensitive group names.
    """
    groups: list[str] = []
    if household.get("children", 0) >= 1:
        groups.append("Children")
    if household.get("elderly", 0) >= 1:
        groups.append("Elderly")
    if bool(household.get("respiratory")):
        groups.append("Respiratory conditions")
    if bool(household.get("heart")):
        groups.append("Heart conditions")
    if bool(household.get("pregnant")):
        groups.append("Pregnant individuals")
    return {"sensitive": len(groups) > 0, "groups": groups}


def advice_tier(band_key: str, sensitive: bool) -> str:
    """Determine the action advisory tier for a given PM2.5 band and sensitivity status.

    Args:
        band_key: Air quality band identifier string.
        sensitive: Whether the household contains sensitive individuals.

    Returns:
        One of the action tiers: 'normal', 'caution', 'restrict', or 'avoid'.

    Raises:
        ValueError: If the band_key is not recognized.
    """
    pair = TIER_BY_BAND.get(band_key)
    if pair is None:
        raise ValueError(f"Unknown PM2.5 band key: '{band_key}'")
    return pair[1] if sensitive else pair[0]


def _exercise_guidance(tier: str) -> dict[str, Any]:
    """Return activity guidance for outdoor exercise under a specific tier.

    Args:
        tier: Action advisory tier.

    Returns:
        Dictionary with allowed flag and advice string.
    """
    if tier == "normal":
        return {"allowed": True, "advice": "Outdoor exercise permitted as usual."}
    if tier == "caution":
        return {"allowed": True, "advice": "Outdoor workouts permitted; keep it light and shorter."}
    if tier == "restrict":
        return {"allowed": False, "advice": "Move workouts indoors; avoid outdoor exertion."}
    return {"allowed": False, "advice": "Avoid outdoor workouts; choose indoor alternatives."}


def _play_guidance(tier: str) -> dict[str, Any]:
    """Return activity guidance for kids outdoor play under a specific tier.

    Args:
        tier: Action advisory tier.

    Returns:
        Dictionary with allowed flag and advice string.
    """
    if tier == "normal":
        return {"allowed": True, "advice": "Outdoor play permitted freely."}
    if tier == "caution":
        return {"allowed": True, "advice": "Keep play shorter and away from traffic corridors."}
    if tier == "restrict":
        return {"allowed": False, "advice": "Keep children indoors with active indoor games."}
    return {"allowed": False, "advice": "Avoid all outdoor play; keep activities strictly indoors."}


def _errands_guidance(tier: str) -> dict[str, Any]:
    """Return activity guidance for errands under a specific tier.

    Args:
        tier: Action advisory tier.

    Returns:
        Dictionary with allowed flag and advice string.
    """
    mask_note = (
        "Combine trips and wear a well-fitted N95 or FFP2 mask. Cloth and surgical masks "
        "do little against fine particles, while an N95 or FFP2 mask helps filter particles "
        "without complete protection."
    )
    if tier == "normal":
        return {"allowed": True, "advice": "Run errands normally."}
    if tier == "caution":
        return {"allowed": True, "advice": "Routine errands allowed; avoid peak traffic hours."}
    return {"allowed": True, "advice": mask_note}


def _ventilation_guidance(tier: str) -> dict[str, Any]:
    """Return activity guidance for window ventilation under a specific tier.

    Args:
        tier: Action advisory tier.

    Returns:
        Dictionary with allowed flag and advice string.
    """
    if tier == "normal":
        return {"allowed": True, "advice": "Open windows freely for natural ventilation."}
    if tier == "caution":
        adv = "Ventilate during warmer daytime hours when air is clearer."
        return {"allowed": True, "advice": adv}
    return {
        "allowed": False,
        "advice": "Open windows only in the cleanest daytime window for 10-15 minutes, then close.",
    }


def _guidance_for_activity(activity: str, tier: str) -> dict[str, Any]:
    """Dispatch activity guidance for a specific activity name and tier.

    Args:
        activity: Name of the activity.
        tier: Current action advisory tier.

    Returns:
        Dictionary with allowed flag and advice string.
    """
    if activity == "outdoor_exercise":
        return _exercise_guidance(tier)
    if activity == "kids_outdoor_play":
        return _play_guidance(tier)
    if activity == "errands":
        return _errands_guidance(tier)
    return _ventilation_guidance(tier)


def activity_guidance(tier: str) -> dict[str, dict[str, Any]]:
    """Generate activity-specific precautionary guidance for the specified tier.

    Args:
        tier: Air quality action tier ('normal', 'caution', 'restrict', 'avoid').

    Returns:
        Mapping of activity names to permission status and tailored advice.

    Raises:
        ValueError: If tier is invalid.
    """
    if tier not in TIERS:
        raise ValueError(f"Unknown tier: '{tier}'")
    return {act: _guidance_for_activity(act, tier) for act in ACTIVITY_HOURS}


def _parse_entry_hour(entry: dict[str, Any]) -> int:
    """Extract integer hour from ISO formatted time string.

    Args:
        entry: Hourly reading dictionary.

    Returns:
        Integer hour (0-23).
    """
    return datetime.datetime.fromisoformat(entry["time"]).hour


def find_best_window(
    hourly: list[dict[str, Any]], earliest: int, latest: int, hours: int = 1
) -> Optional[dict[str, Any]]:
    """Identify the optimal time window with the lowest average PM2.5 levels.

    Args:
        hourly: Chronological list of hourly readings with time and pm25 fields.
        earliest: Earliest allowed start hour (0-23).
        latest: Latest allowed start hour (0-23).
        hours: Consecutive duration of the window in hours.

    Returns:
        Dictionary with start time, start hour, and average PM2.5, or None.
    """
    if not hourly or hours < 1 or len(hourly) < hours:
        return None
    best_candidate: Optional[dict[str, Any]] = None
    min_avg = float("inf")
    for i in range(len(hourly) - hours + 1):
        win = hourly[i:i + hours]
        st_hour = _parse_entry_hour(win[0])
        if not (earliest <= st_hour <= latest) or any(item.get("pm25") is None for item in win):
            continue
        avg = sum(float(item["pm25"]) for item in win) / hours
        if avg < min_avg:
            min_avg = avg
            best_candidate = {"start": win[0]["time"], "hour": st_hour, "avg_pm25": round(avg, 1)}
    return best_candidate


def _calc_reduction_pct(usual_pm25: float, best_pm25: float) -> int:
    """Calculate integer percentage reduction between usual and best PM2.5.

    Args:
        usual_pm25: Baseline PM2.5 level.
        best_pm25: Optimized PM2.5 level.

    Returns:
        Integer percentage reduction (0-100).
    """
    if usual_pm25 <= 0.0 or best_pm25 >= usual_pm25:
        return 0
    return int(round(max(0.0, (usual_pm25 - best_pm25) / usual_pm25 * 100)))


# Note for next occurrence forecast comparisons.
USUAL_NOTE: str = (
    "Usual time refers to the next time you are due to go out at that hour. "
    "All figures are forecast values, not a promise."
)


def _find_usual_entry(
    hourly: list[dict[str, Any]], hour: int
) -> Optional[dict[str, Any]]:
    """Locate the next hourly entry matching the specified hour.

    Args:
        hourly: Hourly readings list.
        hour: Target hour (0-23).

    Returns:
        First matching entry or None.
    """
    return next((e for e in hourly if _parse_entry_hour(e) == hour), None)


def compare_usual_vs_best(
    hourly: list[dict[str, Any]], usual_hour: int, earliest: int, latest: int
) -> Optional[dict[str, Any]]:
    """Compare air quality at the household's usual hour against the best window.

    Args:
        hourly: Hourly readings list.
        usual_hour: Usual activity start hour (0-23).
        earliest: Earliest possible start hour.
        latest: Latest possible start hour.

    Returns:
        Comparison dictionary with percentage reduction, or None.
    """
    if not hourly:
        return None
    usual = _find_usual_entry(hourly, usual_hour)
    if usual is None or usual.get("pm25") is None:
        return None
    best = find_best_window(hourly, earliest, latest, hours=1)
    if best is None:
        return None
    u_pm25, b_pm25 = float(usual["pm25"]), float(best["avg_pm25"])
    return {
        "usual_hour": usual_hour, "usual_pm25": u_pm25, "best_hour": best["hour"],
        "best_pm25": b_pm25, "reduction_pct": _calc_reduction_pct(u_pm25, b_pm25),
        "is_forecast": True, "note": USUAL_NOTE,
    }


def commute_emissions(
    mode: str, km_one_way: float, days_per_week: int, occupants: int = 1
) -> float:
    """Compute monthly CO2 emissions in kg for a given commute mode.

    Args:
        mode: Commute transport mode string.
        km_one_way: One-way distance in kilometers.
        days_per_week: Commute frequency in days per week (0-7).
        occupants: Vehicle occupancy count (used for carpool calculations).

    Returns:
        Estimated monthly CO2 emissions in kg, rounded to 1 decimal place.

    Raises:
        ValueError: For unknown modes or negative numeric inputs.
    """
    if km_one_way < 0 or days_per_week < 0 or occupants < 0:
        raise ValueError("Commute parameters cannot be negative.")
    if mode == "carpool":
        factor = EMISSION_FACTORS["car_petrol"] / max(occupants, 2)
    elif mode in EMISSION_FACTORS:
        factor = EMISSION_FACTORS[mode]
    else:
        raise ValueError(f"Unknown commute mode: '{mode}'")
    monthly_kg = factor * km_one_way * 2.0 * days_per_week * WEEKS_PER_MONTH
    return round(monthly_kg, 1)


def _commute_factor(alt: str, occupants: int) -> float:
    """Return the emission factor for an alternative mode.

    Args:
        alt: Transport mode identifier.
        occupants: Occupancy count for carpool.

    Returns:
        Factor in kg CO2 per passenger-km.
    """
    if alt == "carpool":
        return EMISSION_FACTORS["car_petrol"] / max(occupants, 2)
    return EMISSION_FACTORS[alt]


def compare_commute(
    mode: str, km_one_way: float, days_per_week: int, occupants: int = 2
) -> list[dict[str, Any]]:
    """Compare current commute emissions against lower-carbon alternatives.

    Args:
        mode: Current transport mode.
        km_one_way: Commute distance one way in km.
        days_per_week: Days travelled per week.
        occupants: Carpool vehicle occupancy count.

    Returns:
        List of alternatives saving > 0.5 kg CO2, sorted by saving descending.
    """
    current_kg = commute_emissions(mode, km_one_way, days_per_week, occupants)
    alternatives = ["bus", "metro_train", "carpool", "two_wheeler", "walk_cycle"]
    results: list[dict[str, Any]] = []
    for alt in alternatives:
        if alt == mode or (alt == "walk_cycle" and km_one_way > WALK_CYCLE_MAX_KM):
            continue
        alt_kg = commute_emissions(alt, km_one_way, days_per_week, occupants)
        saving = round(current_kg - alt_kg, 1)
        if saving > 0.5:
            fac = _commute_factor(alt, occupants)
            results.append({
                "mode": alt, "monthly_kg": alt_kg, "saving_kg": saving,
                "assumption": f"Assumes {fac:.3f} kg CO2 per passenger-km",
            })
    results.sort(key=lambda x: x["saving_kg"], reverse=True)
    return results


def purifier_sizing(room_area_sqm: float) -> dict[str, Any]:
    """Calculate recommended air purifier clean air delivery rate (CADR) for a room.

    Args:
        room_area_sqm: Room floor area in square meters.

    Returns:
        Dictionary containing volume, CADR ratings, and sizing assumptions.

    Raises:
        ValueError: If room area is not within [5, 200] sqm.
    """
    if room_area_sqm < 5 or room_area_sqm > 200:
        raise ValueError("Room area must be between 5 and 200 square meters.")
    volume = round(room_area_sqm * CEILING_M, 1)
    min_cadr_m3h = round(volume * TARGET_ACH)
    min_cadr_cfm = round(min_cadr_m3h * M3H_TO_CFM)
    assumption = (
        "Assumes a 2.7 m ceiling and about 4 air changes per hour; "
        "check the CADR (clean air delivery rate) printed on the purifier."
    )
    return {
        "room_area_sqm": room_area_sqm, "volume_m3": volume,
        "min_cadr_m3h": min_cadr_m3h, "min_cadr_cfm": min_cadr_cfm,
        "assumption": assumption,
    }


def _checklist_ventilation_items(tier: str) -> list[dict[str, str]]:
    """Generate ventilation and gap sealing checklist items for smog tiers.

    Args:
        tier: Current action advisory tier.

    Returns:
        List of ventilation checklist item dicts.
    """
    if tier not in ("restrict", "avoid"):
        return []
    a1 = "Open windows only in the cleanest daytime window, for 10-15 minutes, then close them"
    a2 = "Seal door and window gaps, keep the sensitive person's room closed"
    return [
        {
            "action": a1,
            "why": "Brief airing refreshes air with minimal outdoor particle intake.",
            "effort": "easy",
        },
        {
            "action": a2,
            "why": "Reduces draft infiltration; keeps vulnerable family members protected.",
            "effort": "moderate",
        },
    ]


def _checklist_purifier_items(
    tier: str, lifestyle: dict[str, Any]
) -> list[dict[str, str]]:
    """Generate air purifier recommendation or operation checklist items.

    Args:
        tier: Current advisory tier.
        lifestyle: Household lifestyle parameters.

    Returns:
        List of purifier checklist items.
    """
    if not lifestyle.get("has_purifier", False) and tier != "normal":
        return [{
            "action": "Suggest a purifier sized by the room (refer to the purifier sizing result)",
            "why": "Significantly cuts indoor PM2.5; sized according to room CADR requirements.",
            "effort": "moderate",
        }]
    if lifestyle.get("has_purifier", False):
        return [{
            "action": (
                "Run it on the room where people spend most time, "
                "keep doors closed, replace filters on schedule"
            ),
            "why": "Continuous filtration in primary living zones maximizes particulate reduction.",
            "effort": "easy",
        }]
    return []


def _checklist_lifestyle_items(
    tier: str, lifestyle: dict[str, Any]
) -> list[dict[str, str]]:
    """Build ventilation and purifier items for the indoor checklist.

    Args:
        tier: Current advisory tier.
        lifestyle: Household lifestyle parameters.

    Returns:
        List of checklist item dictionaries.
    """
    items = _checklist_ventilation_items(tier)
    items.extend(_checklist_purifier_items(tier, lifestyle))
    return items


def _checklist_combustion_items(lifestyle: dict[str, Any]) -> list[dict[str, str]]:
    """Build biomass and smoking mitigation items for the checklist.

    Args:
        lifestyle: Household lifestyle parameters.

    Returns:
        List of combustion checklist items.
    """
    items: list[dict[str, str]] = []
    if lifestyle.get("heating") == "biomass" or lifestyle.get("cooking") == "biomass":
        items.append({
            "action": (
                "Suggest switching to electric, gas or induction where possible, "
                "and use the chimney or exhaust fan while cooking"
            ),
            "why": "Biomass burning releases heavy indoor fine particulate matter.",
            "effort": "moderate",
        })
    if lifestyle.get("smokers", False):
        items.append({
            "action": "Smoke outdoors only, never in rooms where children are",
            "why": "Secondhand smoke dramatically spikes indoor PM2.5 concentrations.",
            "effort": "easy",
        })
    return items


def _checklist_hygiene_items() -> list[dict[str, str]]:
    """Build universal cleaning, exhaust, and plant indoor hygiene items.

    Returns:
        List of standard indoor air hygiene actions.
    """
    return [
        {
            "action": "Wet-mop or damp-dust rather than dry sweeping; use exhaust fan when cooking",
            "why": "Damp wiping traps settled dust rather than resuspending PM2.5 particles.",
            "effort": "easy",
        },
        {
            "action": "Indoor plants",
            "why": (
                "Plants do very little to clean indoor air at home scale and are not a "
                "replacement for ventilation control or a purifier."
            ),
            "effort": "easy",
        },
    ]


def _checklist_source_items(lifestyle: dict[str, Any]) -> list[dict[str, str]]:
    """Build combustion and common indoor hygiene checklist items.

    Args:
        lifestyle: Household lifestyle parameters.

    Returns:
        List of checklist item dictionaries.
    """
    items = _checklist_combustion_items(lifestyle)
    items.extend(_checklist_hygiene_items())
    return items


def indoor_checklist(
    tier: str, household: dict[str, Any], lifestyle: dict[str, Any]
) -> list[dict[str, str]]:
    """Generate practical indoor air quality checklist items tailored to the household.

    Args:
        tier: Current action advisory tier.
        household: Demographic and vulnerability information.
        lifestyle: Heating, cooking, and air management habits.

    Returns:
        List of applicable checklist actions with rationale and effort level.
    """
    items = _checklist_lifestyle_items(tier, lifestyle)
    items.extend(_checklist_source_items(lifestyle))
    return items


def _build_windows(hourly: list[dict[str, Any]]) -> dict[str, Optional[dict[str, Any]]]:
    """Compute optimal time windows for outdoor exercise, errands, and ventilation.

    Args:
        hourly: List of hourly forecast readings.

    Returns:
        Dictionary mapping activity to best window dictionary or None.
    """
    acts = {
        "outdoor_exercise": ACTIVITY_HOURS["outdoor_exercise"],
        "errands": ACTIVITY_HOURS["errands"],
        "window_ventilation": ACTIVITY_HOURS["window_ventilation"],
    }
    res: dict[str, Optional[dict[str, Any]]] = {}
    for k, rng in acts.items():
        res[k] = find_best_window(hourly, rng[0], rng[1]) if hourly else None
    res["exercise"] = res["outdoor_exercise"]
    res["ventilation"] = res["window_ventilation"]
    return res


def _build_air_summary(air: dict[str, Any], pm25: float) -> dict[str, Any]:
    """Package air observation summary dictionary.

    Args:
        air: Air dictionary.
        pm25: Float PM2.5 level.

    Returns:
        Air summary dictionary.
    """
    return {
        "pm25": pm25,
        "aqi": pm25_to_aqi(pm25),
        "band": pm25_band(pm25),
        "source": air.get("source", "live"),
        "observed_at": air.get("observed_at", ""),
    }


def _build_commute_summary(ls: dict[str, Any]) -> dict[str, Any]:
    """Build commute emission status and alternatives dictionary.

    Args:
        ls: Lifestyle dictionary.

    Returns:
        Commute emissions dictionary.
    """
    mode = ls.get("commute_mode", "car_petrol")
    km = float(ls.get("commute_km_one_way", 0.0))
    days = int(ls.get("commute_days_per_week", 0))
    return {
        "current_monthly_kg": commute_emissions(mode, km, days),
        "alternatives": compare_commute(mode, km, days),
        "note": CLIMATE_NOTE,
    }


def generate_advice(inputs: dict[str, Any], air: dict[str, Any]) -> dict[str, Any]:
    """Synthesize air readings, household factors, and lifestyle into advice.

    Args:
        inputs: User input parameters including city, household, and lifestyle.
        air: Air quality status including PM2.5, hourly readings, and source.

    Returns:
        Comprehensive advice dictionary covering precautions, windows, and commute.
    """
    pm25, ls = float(air["pm25"]), inputs.get("lifestyle", {})
    sens = household_sensitivity(inputs.get("household", {}))
    tier = advice_tier(pm25_band(pm25)["key"], sens["sensitive"])
    hourly = air.get("hourly", [])
    limits = ["Hourly forecast unavailable; windows cannot be scheduled."] if not hourly else []
    u_hr, area = int(ls.get("usual_outdoor_hour", 8)), float(ls.get("room_area_sqm", 20.0))
    return {
        "air": _build_air_summary(air, pm25), "sensitivity": sens, "tier": tier,
        "guidance": activity_guidance(tier), "windows": _build_windows(hourly),
        "usual_vs_best": compare_usual_vs_best(hourly, u_hr, 6, 20) if hourly else None,
        "commute": _build_commute_summary(ls), "purifier": purifier_sizing(area),
        "indoor_checklist": indoor_checklist(tier, inputs.get("household", {}), ls),
        "medical_note": MEDICAL_NOTE, "limits": limits,
    }
