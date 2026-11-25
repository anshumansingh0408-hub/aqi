"""Unit tests for utility functions in the Saans system.

Tests input validation error collection, text sanitization, rate limiting, and formatting.
"""

import unittest
from utils import (
    check_rate_limit,
    format_pm25,
    generate_cache_key,
    sanitize_text_input,
    validate_inputs,
)


class TestUtils(unittest.TestCase):
    """Test suite for utility functions."""

    def test_sanitize_text_input(self) -> None:
        """Verify removal of control characters, null bytes, and trimming."""
        raw = "\x00Hello\r\n\t World\x07\x1f   "
        sanitized = sanitize_text_input(raw, 20)
        self.assertEqual(sanitized, "Hello\r\n\t World")
        self.assertEqual(sanitize_text_input("Long string", 4), "Long")
        self.assertEqual(sanitize_text_input("", 10), "")

    def test_generate_cache_key(self) -> None:
        """Verify MD5 hex generation from parts."""
        key1 = generate_cache_key("city", "delhi", "2026-11-18")
        key2 = generate_cache_key("city", "delhi", "2026-11-18")
        key3 = generate_cache_key("city", "mumbai", "2026-11-18")
        self.assertEqual(len(key1), 32)
        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)

    def test_format_pm25(self) -> None:
        """Verify PM2.5 float formatting with one decimal and unit."""
        self.assertEqual(format_pm25(142.53), "142.5 µg/m3")
        self.assertEqual(format_pm25(0.0), "0.0 µg/m3")
        self.assertEqual(format_pm25(300), "300.0 µg/m3")

    def test_check_rate_limit_sliding_window(self) -> None:
        """Verify rate limiting blocks the 16th call when limit is 15 within the window."""
        tracker: dict[str, list[float]] = {}
        ip = "192.168.1.1"
        base_time = 1000.0
        for _ in range(15):
            allowed = check_rate_limit(
                ip, tracker, max_requests=15, window_seconds=60, current_time=base_time
            )
            self.assertTrue(allowed)
        blocked = check_rate_limit(
            ip, tracker, max_requests=15, window_seconds=60, current_time=base_time + 10
        )
        self.assertFalse(blocked)
        after_window = check_rate_limit(
            ip, tracker, max_requests=15, window_seconds=60, current_time=base_time + 65
        )
        self.assertTrue(after_window)

    def test_validate_inputs_valid_payload(self) -> None:
        """Verify clean data parsing for a fully valid payload."""
        data = {
            "city": "New Delhi",
            "household": {
                "children": 2, "elderly": 1, "respiratory": True, "heart": False, "pregnant": False,
            },
            "lifestyle": {
                "heating": "electric", "cooking": "lpg", "has_purifier": True, "smokers": False,
                "commute_mode": "metro_train", "commute_km_one_way": 15.0,
                "commute_days_per_week": 5, "room_area_sqm": 35.0, "usual_outdoor_hour": 7,
            },
            "manual_pm25": 145.0,
            "notes": "Elderly parent with asthma.",
        }
        cleaned, errors = validate_inputs(data)
        self.assertEqual(errors, [])
        self.assertEqual(cleaned["city"], "New Delhi")
        self.assertEqual(cleaned["household"]["children"], 2)
        self.assertEqual(cleaned["lifestyle"]["commute_mode"], "metro_train")
        self.assertEqual(cleaned["manual_pm25"], 145.0)

    def test_validate_inputs_collects_multiple_errors(self) -> None:
        """Verify multiple invalid fields simultaneously accumulate into errors."""
        bad_data = {
            "city": "A",
            "household": {
                "children": 15,
                "respiratory": "invalid_bool",
            },
            "lifestyle": {
                "heating": "nuclear",
                "cooking": "wood",
                "commute_mode": "teleport",
                "commute_km_one_way": 500.0,
                "commute_days_per_week": 10,
                "room_area_sqm": 2.0,
                "usual_outdoor_hour": 25,
            },
            "manual_pm25": 2000.0,
        }
        cleaned, errors = validate_inputs(bad_data)
        self.assertGreater(len(errors), 5)
        self.assertTrue(any("city" in e.lower() for e in errors))
        self.assertTrue(any("household.children" in e for e in errors))
        self.assertTrue(any("household.respiratory" in e for e in errors))
        self.assertTrue(any("lifestyle.heating" in e for e in errors))
        self.assertTrue(any("lifestyle.cooking" in e for e in errors))
        self.assertTrue(any("lifestyle.commute_mode" in e for e in errors))
        self.assertTrue(any("lifestyle.room_area_sqm" in e for e in errors))
        self.assertTrue(any("manual_pm25" in e for e in errors))
        for err in errors:
            self.assertNotIn("nuclear", err)
            self.assertNotIn("wood", err)
            self.assertNotIn("teleport", err)

    def test_validate_inputs_strips_control_characters_from_city(self) -> None:
        """Verify control characters in city name are stripped before length validation."""
        data = {
            "city": "\x01\x02Delhi\x03\x04\x1f",
            "household": {"children": 0, "elderly": 0},
            "lifestyle": {
                "heating": "none", "cooking": "induction", "has_purifier": False, "smokers": False,
                "commute_mode": "walk_cycle", "commute_km_one_way": 2.0,
                "commute_days_per_week": 3, "room_area_sqm": 18.0, "usual_outdoor_hour": 8,
            },
        }
        cleaned, errors = validate_inputs(data)
        self.assertEqual(errors, [])
        self.assertEqual(cleaned["city"], "Delhi")

    def test_validate_inputs_nested_structure_and_types(self) -> None:
        """Verify validation enforces nested object structures and strict boolean types."""
        invalid_nested = {
            "city": "Mumbai",
            "household": "not_an_object",
            "lifestyle": 12345,
        }
        cleaned, errors = validate_inputs(invalid_nested)
        self.assertTrue(any("household must be an object" in e for e in errors))
        self.assertTrue(any("lifestyle must be an object" in e for e in errors))
        self.assertIsInstance(cleaned["household"], dict)
        self.assertIsInstance(cleaned["lifestyle"], dict)


if __name__ == "__main__":
    unittest.main()
