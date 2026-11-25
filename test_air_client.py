"""Unit tests for the Saans air quality and geocoding client.

Validates Open-Meteo API parsing, caching, eviction, and error handling using mock HTTP calls.
"""

import time
from typing import Any
import unittest
from unittest.mock import MagicMock, patch
import requests
from air_client import (
    _CACHE,
    _CACHE_LOCK,
    CONFIG,
    SOURCE_NOTE,
    AirDataError,
    _get_json,
    fetch_air_quality,
    geocode_city,
    get_air_reading,
    get_cached,
    parse_air_response,
    set_cached,
)


def _mock_geo_response() -> dict[str, Any]:
    """Provide realistic geocoding response based on Open-Meteo format."""
    return {
        "results": [
            {
                "id": 1273294,
                "name": "Delhi",
                "latitude": 28.65195,
                "longitude": 77.23149,
                "country": "India",
                "admin1": "National Capital Territory of Delhi",
            },
            {
                "id": 5114824,
                "name": "Delhi",
                "latitude": 42.27814,
                "longitude": -74.91599,
                "country": "United States",
                "admin1": "New York",
            },
            {
                "id": 5342522,
                "name": "Delhi",
                "latitude": 37.43216,
                "longitude": -120.77854,
                "country": "United States",
                "admin1": "California",
            },
            {
                "id": 4990729,
                "name": "Delhi",
                "latitude": 42.74837,
                "longitude": -84.49776,
                "country": "United States",
                "admin1": "Michigan",
            },
        ],
        "generationtime_ms": 0.12,
    }


def _mock_air_response() -> dict[str, Any]:
    """Provide realistic air quality response based on Open-Meteo format."""
    times = [f"2026-11-18T{h:02d}:00" for h in range(24)] + [
        f"2026-11-19T{h:02d}:00" for h in range(24)
    ]
    pms = [float(50 + (i % 30)) for i in range(48)]
    return {
        "latitude": 28.7,
        "longitude": 77.2,
        "current": {"time": "2026-11-18T10:30", "interval": 3600, "pm2_5": 78.5},
        "hourly": {"time": times, "pm2_5": pms},
    }


class TestAirClientGeocoding(unittest.TestCase):
    """Tests for geocoding, alternatives extraction, and caching."""

    def setUp(self) -> None:
        """Clear cache before each test run."""
        with _CACHE_LOCK:
            _CACHE.clear()

    @patch("requests.get")
    def test_geocode_city_success_and_caching(self, mock_get: MagicMock) -> None:
        """Verify geocoding parses first result, alternatives, and caches case-insensitively."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = _mock_geo_response()
        mock_get.return_value = mock_resp

        res1 = geocode_city("Delhi")
        self.assertEqual(res1["name"], "Delhi")
        self.assertEqual(res1["admin1"], "National Capital Territory of Delhi")
        self.assertEqual(res1["country"], "India")
        self.assertAlmostEqual(res1["latitude"], 28.65195)
        self.assertAlmostEqual(res1["longitude"], 77.23149)
        self.assertEqual(len(res1["alternatives"]), 3)
        self.assertEqual(res1["alternatives"][0]["admin1"], "New York")
        self.assertEqual(mock_get.call_count, 1)

        # Second call with different casing should hit cache
        res2 = geocode_city("DELHI")
        self.assertEqual(res2["name"], "Delhi")
        self.assertEqual(mock_get.call_count, 1)

    @patch("requests.get")
    def test_geocode_city_empty_results_raises_city_not_found(
        self, mock_get: MagicMock
    ) -> None:
        """Verify empty results list raises CITY_NOT_FOUND."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {"results": []}
        mock_get.return_value = mock_resp

        with self.assertRaises(AirDataError) as ctx:
            geocode_city("NonexistentCityXYZ")
        self.assertEqual(ctx.exception.code, "CITY_NOT_FOUND")

    @patch("requests.get")
    def test_geocode_city_missing_results_key_raises_city_not_found(
        self, mock_get: MagicMock
    ) -> None:
        """Verify response without results key raises CITY_NOT_FOUND."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {"generationtime_ms": 0.05}
        mock_get.return_value = mock_resp

        with self.assertRaises(AirDataError) as ctx:
            geocode_city("Nowhere")
        self.assertEqual(ctx.exception.code, "CITY_NOT_FOUND")

    @patch("requests.get")
    def test_geocode_city_invalid_coordinates(self, mock_get: MagicMock) -> None:
        """Verify non-numeric or out-of-range coordinates raise BAD_RESPONSE."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_get.return_value = mock_resp

        # Non-numeric coordinate
        mock_resp.json.return_value = {
            "results": [{"name": "BadCity", "latitude": "invalid", "longitude": 77.0}]
        }
        with self.assertRaises(AirDataError) as ctx1:
            geocode_city("BadCity")
        self.assertEqual(ctx1.exception.code, "BAD_RESPONSE")

        # Out-of-range latitude
        mock_resp.json.return_value = {
            "results": [{"name": "PoleCity", "latitude": 95.0, "longitude": 10.0}]
        }
        with self.assertRaises(AirDataError) as ctx2:
            geocode_city("PoleCity")
        self.assertEqual(ctx2.exception.code, "BAD_RESPONSE")


class TestAirClientParsing(unittest.TestCase):
    """Tests for pure air quality response parsing."""

    def test_parse_air_response_forward_window_and_order(self) -> None:
        """Verify 24-hour forward window starts at current hour and maintains chronological order.
        """
        data = _mock_air_response()
        res = parse_air_response(data)
        self.assertEqual(res["pm25"], 78.5)
        self.assertEqual(res["observed_at"], "2026-11-18T10:30")
        self.assertEqual(len(res["hourly"]), 24)
        self.assertEqual(res["hourly"][0]["time"], "2026-11-18T10:00")
        self.assertEqual(res["hourly"][23]["time"], "2026-11-19T09:00")

    def test_parse_air_response_current_pm_fallback_to_hourly(self) -> None:
        """Verify None current PM2.5 falls back to the hourly value of the current hour."""
        data = _mock_air_response()
        data["current"]["pm2_5"] = None
        # In mock data, index 10 has 2026-11-18T10:00 with value 50 + (10 % 30) = 60.0
        res = parse_air_response(data)
        self.assertEqual(res["pm25"], 60.0)

    def test_parse_air_response_both_missing_raises_bad_response(self) -> None:
        """Verify error when both current PM2.5 and current hour forecast are missing."""
        data = _mock_air_response()
        data["current"]["pm2_5"] = None
        data["hourly"]["pm2_5"][10] = None
        with self.assertRaises(AirDataError) as ctx:
            parse_air_response(data)
        self.assertEqual(ctx.exception.code, "BAD_RESPONSE")

    def test_parse_air_response_negative_and_non_numeric_become_none(self) -> None:
        """Verify invalid or negative hourly PM2.5 values are parsed as None."""
        data = _mock_air_response()
        data["hourly"]["pm2_5"][10] = -5.0
        data["hourly"]["pm2_5"][11] = "bad_val"
        res = parse_air_response(data)
        self.assertIsNone(res["hourly"][0]["pm25"])
        self.assertIsNone(res["hourly"][1]["pm25"])

    def test_parse_air_response_fewer_than_24_entries(self) -> None:
        """Verify graceful handling when fewer than 24 forecast entries remain."""
        data = {
            "current": {"time": "2026-11-18T20:00", "pm2_5": 65.0},
            "hourly": {
                "time": ["2026-11-18T20:00", "2026-11-18T21:00", "2026-11-18T22:00"],
                "pm2_5": [65.0, 70.0, 75.0],
            },
        }
        res = parse_air_response(data)
        self.assertEqual(res["pm25"], 65.0)
        self.assertEqual(len(res["hourly"]), 3)


class TestAirClientHttpAndErrors(unittest.TestCase):
    """Tests for HTTP error handling, payload bounds, and user-safe messages."""

    def setUp(self) -> None:
        """Clear cache before each test run."""
        with _CACHE_LOCK:
            _CACHE.clear()

    @patch("requests.get")
    def test_get_json_timeout_raises_air_unavailable(self, mock_get: MagicMock) -> None:
        """Verify timeout raises AIR_UNAVAILABLE without leaking URL or parameters."""
        mock_get.side_effect = requests.Timeout("Connection timed out after 8s")
        with self.assertRaises(AirDataError) as ctx:
            _get_json("https://example.com/api", {"city": "Delhi"})
        self.assertEqual(ctx.exception.code, "AIR_UNAVAILABLE")
        msg = ctx.exception.message.lower()
        self.assertNotIn("http", msg)
        self.assertNotIn("delhi", msg)
        self.assertNotIn("example.com", msg)

    @patch("requests.get")
    def test_get_json_connection_error_raises_air_unavailable(
        self, mock_get: MagicMock
    ) -> None:
        """Verify connection error raises AIR_UNAVAILABLE with user-safe message."""
        mock_get.side_effect = requests.ConnectionError("DNS lookup failed")
        with self.assertRaises(AirDataError) as ctx:
            _get_json("https://example.com/api", {})
        self.assertEqual(ctx.exception.code, "AIR_UNAVAILABLE")
        self.assertNotIn("http", ctx.exception.message.lower())

    @patch("requests.get")
    def test_get_json_http_500_raises_air_unavailable(self, mock_get: MagicMock) -> None:
        """Verify HTTP 500 status code raises AIR_UNAVAILABLE."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.content = b"Internal Server Error"
        mock_get.return_value = mock_resp
        with self.assertRaises(AirDataError) as ctx:
            _get_json("https://example.com/api", {})
        self.assertEqual(ctx.exception.code, "AIR_UNAVAILABLE")

    @patch("requests.get")
    def test_get_json_body_over_size_limit_raises_bad_response(
        self, mock_get: MagicMock
    ) -> None:
        """Verify responses exceeding MAX_RESPONSE_BYTES raise BAD_RESPONSE."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"x" * (CONFIG["MAX_RESPONSE_BYTES"] + 10)
        mock_get.return_value = mock_resp
        with self.assertRaises(AirDataError) as ctx:
            _get_json("https://example.com/api", {})
        self.assertEqual(ctx.exception.code, "BAD_RESPONSE")

    @patch("requests.get")
    def test_get_json_array_response_raises_bad_response(
        self, mock_get: MagicMock
    ) -> None:
        """Verify responses returning a JSON list raise BAD_RESPONSE."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[1, 2, 3]"
        mock_resp.json.return_value = [1, 2, 3]
        mock_get.return_value = mock_resp
        with self.assertRaises(AirDataError) as ctx:
            _get_json("https://example.com/api", {})
        self.assertEqual(ctx.exception.code, "BAD_RESPONSE")


class TestAirReadingAndCache(unittest.TestCase):
    """Tests for high-level reading retrieval, cache expiry, and eviction."""

    def setUp(self) -> None:
        """Clear cache before each test run."""
        with _CACHE_LOCK:
            _CACHE.clear()

    @patch("requests.get")
    def test_get_air_reading_manual_makes_zero_requests(
        self, mock_get: MagicMock
    ) -> None:
        """Verify manual PM2.5 bypasses all network calls and returns manual schema."""
        res = get_air_reading("Delhi", manual_pm25=125.0)
        self.assertEqual(mock_get.call_count, 0)
        self.assertEqual(res["pm25"], 125.0)
        self.assertEqual(res["hourly"], [])
        self.assertEqual(res["source"], "manual")
        self.assertIsNone(res["location"])
        self.assertEqual(res["source_note"], "Value entered by you.")

    @patch("requests.get")
    def test_get_air_reading_live_full_schema(self, mock_get: MagicMock) -> None:
        """Verify live retrieval executes geocoding and air quality lookups."""
        geo_resp = MagicMock()
        geo_resp.status_code = 200
        geo_resp.content = b"{}"
        geo_resp.json.return_value = _mock_geo_response()

        air_resp = MagicMock()
        air_resp.status_code = 200
        air_resp.content = b"{}"
        air_resp.json.return_value = _mock_air_response()

        mock_get.side_effect = [geo_resp, air_resp]
        res = get_air_reading("Delhi")
        self.assertEqual(res["source"], "live")
        self.assertEqual(res["source_note"], SOURCE_NOTE)
        self.assertIsNotNone(res["location"])
        self.assertEqual(res["location"]["name"], "Delhi")
        self.assertEqual(len(res["hourly"]), 24)
        self.assertEqual(mock_get.call_count, 2)

    @patch("requests.get")
    def test_fetch_air_quality_caching_and_expiration(
        self, mock_get: MagicMock
    ) -> None:
        """Verify coordinate rounding hits cache and expired entries are refetched."""
        air_resp = MagicMock()
        air_resp.status_code = 200
        air_resp.content = b"{}"
        air_resp.json.return_value = _mock_air_response()
        mock_get.return_value = air_resp

        # Coordinate (28.651, 77.231) rounds to 28.65:77.23
        fetch_air_quality(28.651, 77.231)
        self.assertEqual(mock_get.call_count, 1)

        # Coordinate (28.654, 77.229) rounds to 28.65:77.23 -> cache hit
        fetch_air_quality(28.654, 77.229)
        self.assertEqual(mock_get.call_count, 1)

        # Patch time forward beyond TTL (900 seconds)
        with patch("time.time", return_value=time.time() + 1000):
            fetch_air_quality(28.651, 77.231)
            self.assertEqual(mock_get.call_count, 2)

    def test_cache_eviction_and_immutability(self) -> None:
        """Verify cache drops oldest entries past capacity and protects stored objects."""
        # Test immutability
        orig_obj = {"city": "Delhi", "data": [1, 2, 3]}
        set_cached("test:mut", orig_obj, ttl=300)
        retrieved = get_cached("test:mut", ttl=300)
        retrieved["data"].append(4)  # type: ignore[index]
        fresh = get_cached("test:mut", ttl=300)
        self.assertEqual(fresh["data"], [1, 2, 3])

        # Test capacity eviction
        for i in range(CONFIG["CACHE_MAX_ENTRIES"] + 10):
            set_cached(f"key:{i}", {"val": i}, ttl=3600)
        with _CACHE_LOCK:
            self.assertLessEqual(len(_CACHE), CONFIG["CACHE_MAX_ENTRIES"])


if __name__ == "__main__":
    unittest.main()
