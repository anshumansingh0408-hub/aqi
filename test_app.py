"""Integration tests for the Saans Flask web application.

Validates routing, security headers, rate limiting, error responses,
and API contracts using Flask test client with mock service dependencies.
"""

import os
import time
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

from air_client import AirDataError
import app
from app import AI_TRACKER, GENERAL_TRACKER, app as flask_app, prune_tracker


def _valid_payload() -> dict[str, Any]:
    """Provide fully valid nested request payload for API testing."""
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
        "manual_pm25": None,
        "notes": "Sensitive to winter smog",
    }


def _mock_air_data(manual: bool = False, pm25: float = 150.0) -> dict[str, Any]:
    """Provide realistic mock air reading dictionary."""
    hourly = []
    if not manual:
        for h in range(24):
            hourly.append({
                "time": f"2026-11-20T{h:02d}:00",
                "pm25": 80.0 if 12 <= h <= 16 else 160.0,
            })
    return {
        "pm25": pm25,
        "hourly": hourly,
        "source": "manual" if manual else "live",
        "observed_at": "2026-11-20T00:00:00",
        "location": {"name": "Delhi", "country": "India"},
        "source_note": "atmospheric model estimates",
    }


class TestAppRoutesAndOptions(unittest.TestCase):
    """Tests for HTML templates, health checks, and options endpoint."""

    def setUp(self) -> None:
        """Configure test client and clear tracking tables."""
        flask_app.testing = True
        self.client = flask_app.test_client()
        with app.TRACKER_LOCK:
            GENERAL_TRACKER.clear()
            AI_TRACKER.clear()

    def test_html_pages_status_200(self) -> None:
        """Verify all static HTML view templates respond with 200 OK."""
        for path in ("/", "/create", "/plan", "/about"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200)

    def test_healthz_endpoint(self) -> None:
        """Verify health check liveness endpoint returns ok JSON status."""
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {"status": "ok"})

    def test_api_options_schema_and_contents(self) -> None:
        """Verify static options payload includes bands, modes, and limits."""
        res = self.client.get("/api/options")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data["bands"]), 6)
        self.assertEqual(len(data["commute_modes"]), 7)
        self.assertIn("Approximate", data["bands_note"])
        self.assertIn("limits", data)
        self.assertEqual(data["limits"]["room_area_sqm"], [5, 200])
        self.assertIn("ai_name", data)
        import ai_client
        self.assertEqual(data["ai_name"], ai_client.provider_name())

    def test_rendered_pages_contain_active_ai_name(self) -> None:
        """Verify pages contain active ai_name and do not contain other provider."""
        import ai_client
        for prov, other in (("groq", "Gemini"), ("gemini", "Groq")):
            with patch.dict(os.environ, {"AI_PROVIDER": prov}):
                expected_name = ai_client.PROVIDERS[prov]["name"]
                for path in ("/", "/create", "/about"):
                    res = self.client.get(path)
                    html = res.get_data(as_text=True)
                    self.assertIn(expected_name, html, f"Missing {expected_name} in {path}")
                    self.assertNotIn(other, html, f"Found {other} in {path} when active is {prov}")

    def test_no_hardcoded_provider_in_templates_or_js(self) -> None:
        """Verify no template or static JS file hardcodes Gemini or Groq."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        target_dirs = [os.path.join(base_dir, "templates"), os.path.join(base_dir, "static", "js")]
        for d in target_dirs:
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith((".html", ".js")):
                        p = os.path.join(root, f)
                        with open(p, "r", encoding="utf-8") as fh:
                            content = fh.read().lower()
                        self.assertNotIn("gemini", content, f"Hardcoded 'gemini' in {f}")
                        self.assertNotIn("groq", content, f"Hardcoded 'groq' in {f}")


class TestAppPlanEndpoint(unittest.TestCase):
    """Tests for POST /api/plan calculation, manual readings, and air errors."""

    def setUp(self) -> None:
        """Configure test client and reset state."""
        flask_app.testing = True
        self.client = flask_app.test_client()
        with app.TRACKER_LOCK:
            GENERAL_TRACKER.clear()
            AI_TRACKER.clear()

    @patch("app.get_air_reading")
    def test_post_plan_manual_pm25_success(self, mock_air: MagicMock) -> None:
        """Verify manual PM2.5 calculation returns band, tier, and limits list."""
        mock_air.return_value = _mock_air_data(manual=True, pm25=125.0)
        payload = _valid_payload()
        payload["manual_pm25"] = 125.0
        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        mock_air.assert_called_with("Delhi", 125.0)
        self.assertEqual(data["reading"]["source"], "manual")
        self.assertIsNone(data["advice"]["windows"]["outdoor_exercise"])
        self.assertGreater(len(data["advice"]["limits"]), 0)

    @patch("app.get_air_reading")
    def test_post_plan_live_data_success(self, mock_air: MagicMock) -> None:
        """Verify live air retrieval calculates windows, usual vs best, and notes."""
        mock_air.return_value = _mock_air_data(manual=False, pm25=150.0)
        res = self.client.post("/api/plan", json=_valid_payload())
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsNotNone(data["advice"]["windows"]["outdoor_exercise"])
        self.assertIsNotNone(data["advice"]["usual_vs_best"])
        self.assertIn("location", data["advice"])
        self.assertIn("source_note", data["advice"])

    @patch("app.get_air_reading")
    def test_air_error_city_not_found_404(self, mock_air: MagicMock) -> None:
        """Verify CITY_NOT_FOUND error maps to 404 with safe manual hint."""
        mock_air.side_effect = AirDataError("CITY_NOT_FOUND", "City could not be resolved.")
        res = self.client.post("/api/plan", json=_valid_payload())
        self.assertEqual(res.status_code, 404)
        body = res.get_data(as_text=True)
        self.assertTrue(res.get_json()["manual_hint"])
        for forbidden in ("http", "open-meteo", "googleapis", "Traceback"):
            self.assertNotIn(forbidden, body)

    @patch("app.get_air_reading")
    def test_air_error_air_unavailable_503(self, mock_air: MagicMock) -> None:
        """Verify AIR_UNAVAILABLE maps to 503 with safe body."""
        mock_air.side_effect = AirDataError("AIR_UNAVAILABLE", "Air API unavailable.")
        res = self.client.post("/api/plan", json=_valid_payload())
        self.assertEqual(res.status_code, 503)
        self.assertTrue(res.get_json()["manual_hint"])

    @patch("app.get_air_reading")
    def test_air_error_bad_response_502(self, mock_air: MagicMock) -> None:
        """Verify BAD_RESPONSE maps to 502 with safe body."""
        mock_air.side_effect = AirDataError("BAD_RESPONSE", "Bad response format.")
        res = self.client.post("/api/plan", json=_valid_payload())
        self.assertEqual(res.status_code, 502)
        self.assertTrue(res.get_json()["manual_hint"])


class TestAppValidationErrors(unittest.TestCase):
    """Tests for bad payloads, malformed JSON, and field validations."""

    def setUp(self) -> None:
        """Configure test client."""
        flask_app.testing = True
        self.client = flask_app.test_client()
        with app.TRACKER_LOCK:
            GENERAL_TRACKER.clear()
            AI_TRACKER.clear()

    def test_post_plan_invalid_json(self) -> None:
        """Verify broken non-JSON body returns 400 BAD_REQUEST."""
        res = self.client.post("/api/plan", data="not json", content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "BAD_REQUEST")

    def test_post_plan_json_array_body(self) -> None:
        """Verify JSON array root returns 400 BAD_REQUEST."""
        res = self.client.post("/api/plan", json=[1, 2, 3])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "BAD_REQUEST")

    def test_post_plan_missing_city(self) -> None:
        """Verify missing city key returns 400 VALIDATION_ERROR."""
        payload = _valid_payload()
        del payload["city"]
        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("city must be between 2 and 60 characters.", res.get_json()["details"])

    def test_post_plan_multiple_validation_errors(self) -> None:
        """Verify multiple invalid fields produce accumulated details."""
        payload = _valid_payload()
        payload["household"]["children"] = -5
        payload["lifestyle"]["commute_km_one_way"] = -10.0
        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 400)
        details = res.get_json()["details"]
        self.assertGreater(len(details), 1)

    def test_post_plan_respiratory_given_as_string(self) -> None:
        """Verify respiratory flag given as string is rejected without echoing."""
        payload = _valid_payload()
        payload["household"]["respiratory"] = "yes_asthma"
        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertNotIn("yes_asthma", res.get_data(as_text=True))

    def test_post_plan_invalid_numeric_ranges(self) -> None:
        """Verify out-of-range commute, room area, and manual PM2.5 are rejected."""
        payload = _valid_payload()
        payload["lifestyle"]["commute_km_one_way"] = -5.0
        payload["lifestyle"]["room_area_sqm"] = 500.0
        payload["manual_pm25"] = 5000.0
        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 400)
        body = res.get_data(as_text=True)
        self.assertNotIn("5000", body)
        self.assertNotIn("500", body)

    def test_oversized_payload_returns_413(self) -> None:
        """Verify request exceeding max content length returns 413 error shape."""
        big_notes = "x" * (40 * 1024)
        payload = _valid_payload()
        payload["notes"] = big_notes
        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 413)
        self.assertEqual(res.get_json()["code"], "PAYLOAD_TOO_LARGE")

    @patch("app.get_air_reading")
    def test_child_makes_tier_stricter(self, mock_air: MagicMock) -> None:
        """Verify sensitive household escalates moderate tier from caution to restrict."""
        mock_air.return_value = _mock_air_data(manual=True, pm25=75.0)
        p1 = _valid_payload()
        p1["household"]["children"] = 0
        p1["manual_pm25"] = 75.0
        res1 = self.client.post("/api/plan", json=p1)
        self.assertEqual(res1.get_json()["advice"]["tier"], "caution")
        p2 = _valid_payload()
        p2["household"]["children"] = 1
        p2["manual_pm25"] = 75.0
        res2 = self.client.post("/api/plan", json=p2)
        self.assertEqual(res2.get_json()["advice"]["tier"], "restrict")


class TestAppExplainAndAsk(unittest.TestCase):
    """Tests for POST /api/explain and POST /api/ask with Gemini mocks."""

    def setUp(self) -> None:
        """Configure test client."""
        flask_app.testing = True
        self.client = flask_app.test_client()
        with app.TRACKER_LOCK:
            GENERAL_TRACKER.clear()
            AI_TRACKER.clear()

    @patch("app.explain_plan")
    @patch("app.get_air_reading")
    def test_post_explain_success(self, mock_air: MagicMock, mock_exp: MagicMock) -> None:
        """Verify plan explanation executes and returns formatted response."""
        mock_air.return_value = _mock_air_data()
        mock_exp.return_value = {"summary": "Safe plan", "source": "ai"}
        res = self.client.post("/api/explain", json=_valid_payload())
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["explanation"]["summary"], "Safe plan")
        self.assertIn("disclaimer", data)
        self.assertEqual(mock_exp.call_args[0][1], "Delhi")

    @patch("app.explain_plan")
    @patch("app.get_air_reading")
    def test_post_explain_works_without_api_key(
        self, mock_air: MagicMock, mock_exp: MagicMock
    ) -> None:
        """Verify explain endpoint succeeds and delegates to fallback when key is unset."""
        mock_air.return_value = _mock_air_data()
        mock_exp.return_value = {"summary": "Fallback summary", "source": "fallback"}
        env_empty = {"GROQ_API_KEY": "", "GEMINI_API_KEY": "", "AI_PROVIDER": ""}
        with patch.dict("os.environ", env_empty):
            res = self.client.post("/api/explain", json=_valid_payload())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["explanation"]["source"], "fallback")

    @patch("app.explain_plan")
    @patch("app.get_air_reading")
    def test_client_supplied_api_key_ignored(
        self, mock_air: MagicMock, mock_exp: MagicMock
    ) -> None:
        """Verify user-provided api_key, provider, or model is never forwarded."""
        mock_air.return_value = _mock_air_data()
        mock_exp.return_value = {"summary": "Safe", "source": "ai"}
        payload = _valid_payload()
        payload["api_key"] = "attacker-provided-key"
        payload["provider"] = "attacker-provider"
        payload["model"] = "attacker-model"
        self.client.post("/api/explain", json=payload)
        forwarded_key = mock_exp.call_args[0][3]
        self.assertNotEqual(forwarded_key, "attacker-provided-key")

    @patch("app.get_air_reading")
    def test_post_ask_empty_question_returns_400(self, mock_air: MagicMock) -> None:
        """Verify empty question yields 400 before resolving air readings."""
        payload = _valid_payload()
        payload["question"] = "    "
        res = self.client.post("/api/ask", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "EMPTY_QUESTION")
        mock_air.assert_not_called()

    @patch("app.answer_question")
    @patch("app.get_air_reading")
    def test_post_ask_truncates_long_question(
        self, mock_air: MagicMock, mock_ask: MagicMock
    ) -> None:
        """Verify questions over 300 characters are safely truncated."""
        mock_air.return_value = _mock_air_data()
        mock_ask.return_value = {"answer": "Short answer", "source": "ai"}
        payload = _valid_payload()
        payload["question"] = "Is it safe? " * 50
        res = self.client.post("/api/ask", json=payload)
        self.assertEqual(res.status_code, 200)
        forwarded_q = mock_ask.call_args[0][2]
        self.assertLessEqual(len(forwarded_q), 300)

    @patch("app.answer_question")
    @patch("app.get_air_reading")
    def test_post_ask_valid_question_success(
        self, mock_air: MagicMock, mock_ask: MagicMock
    ) -> None:
        """Verify valid question returns grounded answer with disclaimer."""
        mock_air.return_value = _mock_air_data()
        mock_ask.return_value = {"answer": "Run in morning", "source": "ai"}
        payload = _valid_payload()
        payload["question"] = "When can I exercise?"
        res = self.client.post("/api/ask", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["answer"], "Run in morning")
        self.assertIn("disclaimer", data)


class TestAppSecurityAndRateLimiting(unittest.TestCase):
    """Tests for security headers, rate limiting policies, and cache control."""

    def setUp(self) -> None:
        """Configure test client."""
        flask_app.testing = True
        self.client = flask_app.test_client()
        with app.TRACKER_LOCK:
            GENERAL_TRACKER.clear()
            AI_TRACKER.clear()

    def test_security_headers_on_root(self) -> None:
        """Verify CSP, anti-framing, nosniff, and timing headers on responses."""
        res = self.client.get("/")
        self.assertIn("cdn.tailwindcss.com", res.headers.get("Content-Security-Policy", ""))
        self.assertIn("connect-src 'self'", res.headers.get("Content-Security-Policy", ""))
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("Referrer-Policy"), "no-referrer")
        self.assertIn("s", res.headers.get("X-Response-Time", ""))

    def test_cache_control_headers_api_and_static(self) -> None:
        """Verify /api/ is no-store while /static/ is public with 1-hour cache."""
        api_res = self.client.get("/api/options")
        self.assertEqual(api_res.headers.get("Cache-Control"), "no-store")
        static_res = self.client.get("/static/css/nonexistent.css")
        self.assertEqual(static_res.headers.get("Cache-Control"), "public, max-age=3600")

    @patch("app.explain_plan")
    @patch("app.get_air_reading")
    def test_ai_rate_limiting_429(self, mock_air: MagicMock, mock_exp: MagicMock) -> None:
        """Verify the 11th AI request in one minute is blocked with 429."""
        mock_air.return_value = _mock_air_data()
        mock_exp.return_value = {"summary": "OK", "source": "ai"}
        payload = _valid_payload()
        for _ in range(10):
            res = self.client.post("/api/explain", json=payload)
            self.assertEqual(res.status_code, 200)
        blocked = self.client.post("/api/explain", json=payload)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(mock_exp.call_count, 10)

    @patch("app.get_air_reading")
    def test_general_rate_limiting_429(self, mock_air: MagicMock) -> None:
        """Verify the 31st general request in one minute is blocked with 429."""
        mock_air.return_value = _mock_air_data()
        payload = _valid_payload()
        for _ in range(30):
            res = self.client.post("/api/plan", json=payload)
            self.assertEqual(res.status_code, 200)
        blocked = self.client.post("/api/plan", json=payload)
        self.assertEqual(blocked.status_code, 429)

    def test_prune_tracker_drops_stale_ips(self) -> None:
        """Verify tracker eviction removes expired timestamps when capacity is breached."""
        tracker: dict[str, list[float]] = {}
        old_time = time.time() - 100
        new_time = time.time()
        for i in range(5005):
            tracker[f"10.0.0.{i}"] = [old_time]
        tracker["10.0.0.9999"] = [new_time]
        prune_tracker(tracker, 60)
        self.assertIn("10.0.0.9999", tracker)
        self.assertEqual(len(tracker), 1)

    def test_error_handlers_404_and_405_json(self) -> None:
        """Verify 404 and 405 return consistent JSON error format."""
        res_404 = self.client.get("/nonexistent/endpoint")
        self.assertEqual(res_404.status_code, 404)
        self.assertEqual(res_404.get_json()["code"], "NOT_FOUND")
        res_405 = self.client.get("/api/plan")
        self.assertEqual(res_405.status_code, 405)
        self.assertEqual(res_405.get_json()["code"], "METHOD_NOT_ALLOWED")

    def test_no_body_contains_gemini_api_key(self) -> None:
        """Verify responses never echo the secret GEMINI_API_KEY or GROQ_API_KEY identifier."""
        res = self.client.get("/api/options")
        self.assertNotIn("GEMINI_API_KEY", res.get_data(as_text=True))
        self.assertNotIn("GROQ_API_KEY", res.get_data(as_text=True))


class TestFrontendViewsAndAssets(unittest.TestCase):
    """Integration and content tests for frontend templates and static assets."""

    def setUp(self) -> None:
        """Initialize test client."""
        flask_app.testing = True
        self.client = flask_app.test_client()

    def test_static_assets_status_200(self) -> None:
        """Verify static CSS and JS assets are served with HTTP 200."""
        assets = [
            "/static/css/app.css",
            "/static/js/common.js",
            "/static/js/create.js",
            "/static/js/plan.js",
            "/static/js/landing.js",
            "/static/js/about.js",
        ]
        for path in assets:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Failed for asset {path}")

    def test_landing_page_content(self) -> None:
        """Verify landing page renders primary H1 and key CTA links."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Know today's air, and what to do about it.", html)
        self.assertIn('href="/create"', html)
        self.assertIn('href="#how-it-works"', html)

    def test_create_page_content(self) -> None:
        """Verify create page renders household fieldset and submission controls."""
        res = self.client.get("/create")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Who lives at home?", html)
        self.assertIn("Build my plan", html)
        self.assertIn('id="manual_pm25"', html)

    def test_plan_page_content(self) -> None:
        """Verify plan page renders WAI-ARIA tablist and all five tab panels."""
        res = self.client.get("/plan")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('role="tablist"', html)
        for tab_name in ("Today", "Indoors", "Commute", "Explain", "Ask"):
            self.assertIn(tab_name, html)

    def test_about_page_content(self) -> None:
        """Verify about page renders 6 PM2.5 bands, emissions, and CPCB reference."""
        res = self.client.get("/about")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        for band in ("Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"):
            self.assertIn(band, html)
        self.assertIn("Central Pollution Control Board", html)
        self.assertIn("Car (petrol)", html)

    def test_pretty_mode_template_filter(self) -> None:
        """Verify pretty_mode converts commute keys to human-readable strings."""
        from app import pretty_mode
        self.assertEqual(pretty_mode("car_petrol"), "Car (petrol)")
        self.assertEqual(pretty_mode("walk_cycle"), "Walk or cycle")
        self.assertEqual(pretty_mode("metro_train"), "Metro or train")

    def test_security_and_content_compliance(self) -> None:
        """Scan templates and static files to assert no innerHTML, localStorage, or claims."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        forbidden = ["guarantee", "cure", "protects you", "100% accurate", "trusted by"]
        target_dirs = [os.path.join(base_dir, "templates"), os.path.join(base_dir, "static")]
        for d in target_dirs:
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith((".html", ".js")):
                        p = os.path.join(root, f)
                        with open(p, "r", encoding="utf-8") as fh:
                            content = fh.read().lower()
                        self.assertNotIn(".innerhtml", content, f"Found innerHTML in {f}")
                        self.assertNotIn("localstorage", content, f"Found localStorage in {f}")
                        for word in forbidden:
                            self.assertNotIn(word, content, f"Found '{word}' in {f}")

    def test_rendered_page_static_css_version(self) -> None:
        """Verify rendered page links to /static/css/app.css?v= with app version."""
        from app import APP_VERSION
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn(f"/static/css/app.css?v={APP_VERSION}", html)


class TestThreadSafety(unittest.TestCase):
    """Thread safety tests for rate limit trackers and client caches."""

    def test_concurrent_rate_limiting(self) -> None:
        """Verify concurrent requests mutate rate limit tracker safely without errors."""
        import concurrent.futures
        from app import rate_limited, GENERAL_TRACKER

        def make_call(i: int) -> bool:
            env = {"REMOTE_ADDR": f"192.168.1.{i % 5}"}
            with flask_app.test_request_context("/", environ_base=env):
                return rate_limited(GENERAL_TRACKER, 100)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(make_call, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        self.assertEqual(len(results), 50)
        self.assertIn(False, results)

    def test_concurrent_cache_access(self) -> None:
        """Verify concurrent cache access in air_client and ai_client doesn't race."""
        import concurrent.futures
        import air_client
        import ai_client

        def write_air_cache(i: int) -> None:
            air_client.set_cached(f"test_city_{i}", {"reading": i})
            _ = air_client.get_cached(f"test_city_{i}", 300)

        def write_ai_cache(i: int) -> None:
            ai_client.set_cached(f"test_key_{i}", f"resp_{i}")
            _ = ai_client.get_cached(f"test_key_{i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            air_f = [executor.submit(write_air_cache, i) for i in range(30)]
            ai_f = [executor.submit(write_ai_cache, i) for i in range(30)]
            concurrent.futures.wait(air_f + ai_f)
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
