"""Smoke test utility for validating live Saans deployment endpoints.

Usage:
    python scripts/smoke_test.py https://your-url
    python scripts/smoke_test.py http://localhost:8080
"""

import sys
from typing import Any
import requests


def _valid_manual_payload() -> dict[str, Any]:
    """Provide valid baseline request payload with manual PM2.5."""
    return {
        "city": "Delhi",
        "household": {
            "children": 1,
            "elderly": 0,
            "respiratory": False,
            "heart": False,
            "pregnant": False,
        },
        "lifestyle": {
            "heating": "electric",
            "cooking": "lpg",
            "has_purifier": False,
            "smokers": False,
            "commute_mode": "car_petrol",
            "commute_km_one_way": 10.0,
            "commute_days_per_week": 5,
            "room_area_sqm": 25.0,
            "usual_outdoor_hour": 8,
        },
        "manual_pm25": 180,
        "notes": "",
    }


def main() -> None:
    """Execute 10 end-to-end smoke test assertions against target URL."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/smoke_test.py <base_url>")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    timeout = 30
    failed = False

    def report(name: str, passed: bool, extra: str = "") -> None:
        nonlocal failed
        status = "PASS" if passed else "FAIL"
        suffix = f" - {extra}" if extra else ""
        print(f"[{status}] {name}{suffix}")
        if not passed:
            failed = True

    # 1. GET /healthz returns 200
    try:
        r1 = requests.get(f"{base_url}/healthz", timeout=timeout)
        report("1. GET /healthz returns 200", r1.status_code == 200)
    except Exception as exc:
        report("1. GET /healthz returns 200", False, str(exc))

    # 2. GET / returns 200 and contains 'Start planning'
    try:
        r2 = requests.get(f"{base_url}/", timeout=timeout)
        p2 = r2.status_code == 200 and "Start planning" in r2.text
        report("2. GET / returns 200 and contains 'Start planning'", p2)
    except Exception as exc:
        report("2. GET / returns 200 and contains 'Start planning'", False, str(exc))

    # 3. GET /api/options returns six bands and seven commute modes
    try:
        r3 = requests.get(f"{base_url}/api/options", timeout=timeout)
        d3 = r3.json()
        p3 = (
            r3.status_code == 200
            and len(d3.get("bands", [])) == 6
            and len(d3.get("commute_modes", [])) == 7
        )
        report("3. GET /api/options returns six bands and seven commute modes", p3)
    except Exception as exc:
        report("3. GET /api/options returns six bands and seven commute modes", False, str(exc))

    # 4. POST /api/plan with Delhi payload and manual_pm25 180
    payload_manual = _valid_manual_payload()
    try:
        r4 = requests.post(f"{base_url}/api/plan", json=payload_manual, timeout=timeout)
        d4 = r4.json()
        band = d4.get("advice", {}).get("air", {}).get("band", {})
        band_key = band.get("key") if isinstance(band, dict) else str(band)
        tier = d4.get("advice", {}).get("tier")
        p4 = r4.status_code == 200 and band_key == "very_poor" and tier is not None
        report("4. POST /api/plan (manual 180) returns 200, very_poor band, and tier", p4)
    except Exception as exc:
        report("4. POST /api/plan (manual 180)", False, str(exc))

    # 5. POST /api/plan live lookup
    payload_live = _valid_manual_payload()
    payload_live["manual_pm25"] = None
    try:
        r5 = requests.post(f"{base_url}/api/plan", json=payload_live, timeout=timeout)
        if r5.status_code == 200:
            d5 = r5.json()
            is_live = d5.get("reading", {}).get("source") == "live"
            windows = d5.get("advice", {}).get("windows", {})
            has_windows = any(v is not None for v in windows.values())
            hourly = d5.get("advice", {}).get("hourly", [])
            p5 = is_live and (has_windows or len(hourly) >= 12)
            if p5:
                report("5. POST /api/plan live lookup from Open-Meteo", True)
            else:
                report(
                    "5. POST /api/plan live lookup from Open-Meteo",
                    False,
                    "Live lookup did not work from this host (incomplete window forecast data)",
                )
        else:
            report(
                "5. POST /api/plan live lookup from Open-Meteo",
                False,
                f"Live lookup did not work from this host (HTTP {r5.status_code})",
            )
    except Exception as exc:
        report(
            "5. POST /api/plan live lookup from Open-Meteo",
            False,
            f"Live lookup did not work from this host: {exc}",
        )

    # 6. POST /api/plan Nowhereville12345 returns 404 with manual_hint true
    payload_404 = _valid_manual_payload()
    payload_404["city"] = "Nowhereville12345"
    payload_404["manual_pm25"] = None
    try:
        r6 = requests.post(f"{base_url}/api/plan", json=payload_404, timeout=timeout)
        d6 = r6.json()
        p6 = r6.status_code == 404 and d6.get("manual_hint") is True
        report("6. POST /api/plan (unknown city) returns 404 with manual_hint", p6)
    except Exception as exc:
        report("6. POST /api/plan (unknown city)", False, str(exc))

    # 7. POST /api/plan invalid payload returns 400 with at least 2 details
    payload_inv = {
        "city": "Delhi",
        "household": {"children": -1},
        "lifestyle": {"room_area_sqm": 500},
    }
    try:
        r7 = requests.post(f"{base_url}/api/plan", json=payload_inv, timeout=timeout)
        d7 = r7.json()
        details = d7.get("details", [])
        p7 = r7.status_code == 400 and len(details) >= 2
        report("7. POST /api/plan (invalid payload) returns 400 with >= 2 details", p7)
    except Exception as exc:
        report("7. POST /api/plan (invalid payload)", False, str(exc))

    # 8. POST /api/explain returns explanation with all 7 keys and source
    try:
        r8 = requests.post(f"{base_url}/api/explain", json=payload_manual, timeout=timeout)
        d8 = r8.json()
        exp = d8.get("explanation", {})
        exp_keys = [
            "summary",
            "daily_routine",
            "indoor_tips",
            "commute_swap",
            "impact_statements",
            "community_actions",
            "watch_outs",
        ]
        has_keys = all(k in exp for k in exp_keys)
        source = exp.get("source", "unknown")
        p8 = r8.status_code == 200 and has_keys and source in ("ai", "fallback")
        report(
            "8. POST /api/explain returns all 7 keys",
            p8,
            f"source is '{source}'",
        )
    except Exception as exc:
        report("8. POST /api/explain", False, str(exc))

    # 9. POST /api/ask returns an answer
    payload_ask = _valid_manual_payload()
    payload_ask["question"] = "When is the best time for a walk?"
    try:
        r9 = requests.post(f"{base_url}/api/ask", json=payload_ask, timeout=timeout)
        d9 = r9.json()
        answer = d9.get("answer", "")
        p9 = r9.status_code == 200 and bool(answer)
        report("9. POST /api/ask returns answer", p9)
    except Exception as exc:
        report("9. POST /api/ask", False, str(exc))

    # 10. Response headers check
    try:
        r10 = requests.get(f"{base_url}/api/options", timeout=timeout)
        h = r10.headers
        has_resp_time = "X-Response-Time" in h
        has_csp = "Content-Security-Policy" in h
        has_cache_no_store = h.get("Cache-Control") == "no-store"
        p10 = has_resp_time and has_csp and has_cache_no_store
        report(
            "10. Headers include X-Response-Time, CSP, and Cache-Control: no-store",
            p10,
        )
    except Exception as exc:
        report("10. Headers check", False, str(exc))

    if failed:
        print("\nSmoke test FAILED. One or more assertions failed.")
        sys.exit(1)
    else:
        print("\nAll 10 smoke test checks PASSED successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
