"""CLI helper to demonstrate Gemini AI plan explanation and fallback generation.

Usage:
    python scripts/try_ai.py
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor import generate_advice  # noqa: E402
from ai_client import build_explain_prompt, call_gemini, explain_plan  # noqa: E402


def _build_sample_advice() -> dict:
    """Build a synthetic sample advice dictionary for testing."""
    inputs = {
        "city": "Delhi",
        "household": {"children": 1, "elderly": 1, "respiratory": True},
        "lifestyle": {
            "room_area_sqm": 22.0,
            "commute_km_one_way": 8.0,
            "commute_mode": "car_petrol",
            "commute_days": 5,
            "cooking": "lpg",
            "has_purifier": False,
            "smokers": False,
            "usual_exercise_hour": 7,
        },
    }
    hourly = [
        {"time": f"2026-11-20T{h:02d}:00", "pm25": 90.0 if 12 <= h <= 16 else 180.0}
        for h in range(24)
    ]
    air = {
        "pm25": 175.0,
        "hourly": hourly,
        "source": "live",
        "observed_at": "2026-11-20T00:00:00",
    }
    return generate_advice(inputs, air)


def main() -> None:
    """Run plan explanation via Gemini API or fallback."""
    advice = _build_sample_advice()
    api_key = os.environ.get("GEMINI_API_KEY", "")
    city = "Delhi"
    notes = "Family member has mild asthma and sensitivity to winter dust."

    print("=== Running explain_plan ===")
    res = explain_plan(advice, city, notes, api_key)
    print(f"Source: {res.get('source')}")
    print(f"AI Error: {res.get('ai_error', False)}")
    print(f"Grounding Removed: {res.get('grounding_removed', 0)}")
    print(f"Summary: {res.get('summary')}")
    routine = res.get("daily_routine", [])
    if routine:
        first = routine[0]
        print(f"First Routine Item: [{first.get('time_of_day')}] {first.get('suggestion')}")

    if res.get("source") == "fallback" and api_key.strip():
        print("\n=== AI fallback triggered. Inspecting raw error ===")
        try:
            prompt = build_explain_prompt(advice, city, notes)
            call_gemini(prompt, api_key, expect_json=True)
        except Exception as exc:
            err_msg = str(exc)
            if api_key in err_msg:
                err_msg = err_msg.replace(api_key, "[REDACTED]")
            print(f"Raw call error: {err_msg}")


if __name__ == "__main__":
    main()
