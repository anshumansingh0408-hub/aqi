"""Flask application for Saans, a GenAI urban air quality assistant.

Architecture:
- advisor.py: Pure, stateless deterministic rules engine for health band classification,
  window optimization, CADR purifier sizing, and commute carbon emissions.
- air_client.py: Open-Meteo atmospheric model geocoding and forecast retrieval.
- ai_client.py: Language model explanations and chat answers with strict numeric grounding.
- utils.py: Input validation, rate limiting, and sanitization.

All endpoints are stateless: every API call carries the inputs and the server recomputes
the advice.
"""

import os
import threading
import time
from typing import Any, Optional

from flask import Flask, Response, g, jsonify, render_template, request
from flask_compress import Compress
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from advisor import ACTIVITY_HOURS, EMISSION_FACTORS, PM25_BANDS, generate_advice
import ai_client
from ai_client import AI_DISCLAIMER, CONFIG as AI_CONFIG, answer_question, explain_plan
from air_client import AirDataError, get_air_reading
from utils import check_rate_limit, sanitize_text_input, validate_inputs

app = Flask(__name__)
# x_for=1 trusts one proxy hop (Railway). Without a proxy a client could spoof X-Forwarded-For
# and dodge the rate limit.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
Compress(app)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024

APP_VERSION = "1.0.0"

APP_CONFIG: dict[str, int] = {
    "RATE_LIMIT_GENERAL": 30,
    "RATE_LIMIT_AI": 10,
    "RATE_LIMIT_WINDOW": 60,
    "TRACKER_MAX_IPS": 5000,
}
GENERAL_TRACKER: dict[str, list[float]] = {}
AI_TRACKER: dict[str, list[float]] = {}
TRACKER_LOCK = threading.Lock()


@app.context_processor
def inject_version() -> dict[str, str]:
    """Provide static asset cache-busting version string and AI name to templates.

    Returns:
        Dictionary mapping app_version and ai_name.
    """
    return {
        "app_version": APP_VERSION,
        "ai_name": ai_client.provider_name(),
    }


def get_api_key() -> str:
    """Retrieve secret language model API key from active provider resolution.

    Returns:
        Configured API key string or empty string.
    """
    return ai_client.resolve_api_key()


def client_ip() -> str:
    """Extract client IP address from request context.

    Returns:
        IP address string.
    """
    return str(request.remote_addr or "unknown")


def error_response(
    message: str, code: str, status: int,
    details: Optional[list[str]] = None, manual_hint: bool = False,
) -> tuple[Response, int]:
    """Generate consistent JSON error payload without echoing inputs.

    Args:
        message: Safe, human-readable error description.
        code: Machine-readable uppercase error tag.
        status: HTTP status code.
        details: Optional list of specific validation errors.
        manual_hint: Whether to signal manual PM2.5 fallback.

    Returns:
        Flask JSON response tuple with HTTP status code.
    """
    payload = {
        "error": message,
        "code": code,
        "details": details or [],
        "manual_hint": manual_hint,
    }
    return jsonify(payload), status


def parse_body() -> tuple[Optional[dict[str, Any]], Optional[tuple[Response, int]]]:
    """Parse JSON request payload verifying dictionary object structure.

    Returns:
        Tuple of (decoded_dict, None) or (None, error_response_tuple).
    """
    if not request.is_json:
        return None, error_response("Request body must be a valid JSON object.", "BAD_REQUEST", 400)
    try:
        data = request.get_json(silent=True)
    except RequestEntityTooLarge:
        raise
    except Exception:
        return None, error_response("Invalid JSON payload.", "BAD_REQUEST", 400)
    if not isinstance(data, dict):
        return None, error_response("Request body must be a JSON object.", "BAD_REQUEST", 400)
    return data, None


def prune_tracker(tracker: dict[str, list[float]], window: int) -> None:
    """Evict stale IP timestamp lists when capacity limit is breached.

    Args:
        tracker: Dictionary mapping IP to timestamp arrays.
        window: Sliding window duration in seconds.
    """
    if len(tracker) <= APP_CONFIG["TRACKER_MAX_IPS"]:
        return
    cutoff = time.time() - window
    stale = [ip for ip, ts in tracker.items() if not ts or max(ts) < cutoff]
    for ip in stale:
        tracker.pop(ip, None)


def rate_limited(tracker: dict[str, list[float]], limit: int) -> bool:
    """Assess whether client IP has exceeded the allowed request threshold.

    Args:
        tracker: IP tracking dictionary.
        limit: Permitted calls per window.

    Returns:
        True if client is rate limited, False if permitted.
    """
    with TRACKER_LOCK:
        prune_tracker(tracker, APP_CONFIG["RATE_LIMIT_WINDOW"])
        allowed = check_rate_limit(
            client_ip(), tracker, limit, APP_CONFIG["RATE_LIMIT_WINDOW"]
        )
        return not allowed


def air_error_response(err: AirDataError) -> tuple[Response, int]:
    """Map atmospheric data errors to safe HTTP responses with manual fallback hint.

    Args:
        err: Raised AirDataError instance.

    Returns:
        Mapped error response tuple.
    """
    status_map = {"CITY_NOT_FOUND": 404, "AIR_UNAVAILABLE": 503, "BAD_RESPONSE": 502}
    status = status_map.get(err.code, 502)
    msg = f"{err.message} You can enter today's PM2.5 yourself instead."
    return error_response(msg, err.code, status, manual_hint=True)


def _resolve_air(
    cleaned: dict[str, Any]
) -> tuple[Optional[dict[str, Any]], Optional[tuple[Response, int]]]:
    """Fetch live or manual air readings handling AirDataError.

    Args:
        cleaned: Sanitized input dictionary.

    Returns:
        Tuple of (air_data, None) or (None, error_response_tuple).
    """
    try:
        air = get_air_reading(cleaned["city"], cleaned.get("manual_pm25"))
        return air, None
    except AirDataError as err:
        return None, air_error_response(err)


def build_advice_or_error(
    data: dict[str, Any]
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[tuple[Response, int]]]:
    """Validate request, fetch air metrics, and synthesize advisory plan.

    Args:
        data: Raw request dictionary.

    Returns:
        Tuple of (advice, cleaned_inputs, error_response_tuple).
    """
    cleaned, errors = validate_inputs(data)
    if errors:
        err = error_response("Please fix the highlighted fields.", "VALIDATION_ERROR", 400, errors)
        return None, None, err
    air, err_resp = _resolve_air(cleaned)
    if err_resp is not None:
        return None, None, err_resp
    assert air is not None
    advice = generate_advice(cleaned, air)
    advice["location"] = air.get("location")
    advice["source_note"] = air.get("source_note")
    return advice, cleaned, None


def reading_summary(advice: dict[str, Any]) -> dict[str, Any]:
    """Extract compact summary of the current air reading.

    Args:
        advice: Synthesized advisory plan dictionary.

    Returns:
        Dictionary containing PM2.5 value, timestamp, and source.
    """
    air = advice.get("air", {})
    return {
        "pm25": air.get("pm25", 0.0),
        "observed_at": air.get("observed_at", ""),
        "source": air.get("source", "live"),
    }


def _commute_mode_options() -> list[dict[str, str]]:
    """Build formatted commute mode list for UI selection.

    Returns:
        List of value/label dictionaries.
    """
    labels = {
        "car_petrol": "Car (petrol)",
        "car_diesel": "Car (diesel)",
        "car_electric": "Car (electric)",
        "two_wheeler": "Two-wheeler",
        "bus": "Bus",
        "metro_train": "Metro or train",
        "walk_cycle": "Walk or cycle",
    }
    return [{"value": k, "label": labels.get(k, k)} for k in EMISSION_FACTORS]


CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def _options_limits() -> dict[str, Any]:
    """Return static input limits for options payload.

    Returns:
        Limits dictionary.
    """
    return {
        "city_chars": 60,
        "notes_chars": AI_CONFIG["MAX_NOTES_CHARS"],
        "question_chars": AI_CONFIG["MAX_QUESTION_CHARS"],
        "room_area_sqm": [5, 200],
        "max_pm25_manual": 1000,
    }


def _options_payload() -> dict[str, Any]:
    """Assemble static options, band definitions, and validation limits.

    Returns:
        Full options dictionary.
    """
    note = (
        "Approximate. Bands use PM2.5 breakpoints and an hourly reading, "
        "not the 24-hour average used for official AQI."
    )
    bands = [
        {"key": b["key"], "label": b["label"], "min": b["min"], "max": b["max"]}
        for b in PM25_BANDS
    ]
    return {
        "bands": bands,
        "bands_note": note,
        "commute_modes": _commute_mode_options(),
        "heating": ["electric", "gas", "biomass", "none"],
        "cooking": ["lpg", "induction", "biomass"],
        "activity_hours": ACTIVITY_HOURS,
        "limits": _options_limits(),
        "ai_name": ai_client.provider_name(),
    }


@app.before_request
def start_timer() -> None:
    """Record request arrival timestamp for timing header."""
    g.start = time.time()


def _apply_cache_headers(response: Response, path: str) -> None:
    """Apply path-specific caching rules to HTTP response.

    Args:
        response: Outgoing Response object.
        path: Requested URL path.
    """
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"


@app.after_request
def apply_security_headers(response: Response) -> Response:
    """Attach baseline security, performance timing, and caching headers.

    Args:
        response: Outgoing Response object.

    Returns:
        Response with security headers attached.
    """
    duration = time.time() - getattr(g, "start", time.time())
    response.headers["X-Response-Time"] = f"{duration:.3f}s"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = CSP_POLICY
    _apply_cache_headers(response, request.path)
    return response


@app.errorhandler(404)
def handle_404(_err: Any) -> tuple[Response, int]:
    """Handle 404 Not Found error with JSON body.

    Args:
        _err: Exception or error payload.

    Returns:
        Error response tuple.
    """
    return error_response("The requested URL was not found on the server.", "NOT_FOUND", 404)


@app.errorhandler(405)
def handle_405(_err: Any) -> tuple[Response, int]:
    """Handle 405 Method Not Allowed error with JSON body.

    Args:
        _err: Exception or error payload.

    Returns:
        Error response tuple.
    """
    return error_response(
        "The method is not allowed for the requested URL.", "METHOD_NOT_ALLOWED", 405
    )


@app.errorhandler(413)
def handle_413(_err: Any) -> tuple[Response, int]:
    """Handle 413 Payload Too Large error with JSON body.

    Args:
        _err: Exception or error payload.

    Returns:
        Error response tuple.
    """
    return error_response("Request entity is too large.", "PAYLOAD_TOO_LARGE", 413)


@app.errorhandler(500)
def handle_500(_err: Any) -> tuple[Response, int]:
    """Handle 500 Internal Server Error with generic JSON message.

    Args:
        _err: Exception or error payload.

    Returns:
        Error response tuple.
    """
    return error_response("An unexpected internal server error occurred.", "SERVER_ERROR", 500)


@app.route("/", methods=["GET"])
def route_landing() -> str:
    """Render the landing overview page.

    Returns:
        Rendered HTML template.
    """
    return render_template("landing.html")


@app.route("/create", methods=["GET"])
def route_create() -> str:
    """Render the household plan configuration page.

    Returns:
        Rendered HTML template.
    """
    return render_template("create.html")


@app.route("/plan", methods=["GET"])
def route_plan() -> str:
    """Render the generated air-quality plan display page.

    Returns:
        Rendered HTML template.
    """
    return render_template("plan.html")


@app.template_filter("pretty_mode")
def pretty_mode(key: str) -> str:
    """Format commute mode key into human-readable label.

    Args:
        key: Commute mode key string.

    Returns:
        Formatted mode label string.
    """
    labels = {
        "car_petrol": "Car (petrol)",
        "car_diesel": "Car (diesel)",
        "car_electric": "Car (electric)",
        "two_wheeler": "Two-wheeler",
        "bus": "Bus",
        "metro_train": "Metro or train",
        "walk_cycle": "Walk or cycle",
    }
    return labels.get(key, key.replace("_", " ").title())


def about_context() -> dict[str, Any]:
    """Build context dictionary for the about and methodology page.

    Returns:
        Context with bands, emission factors, room specs, and activity hours.
    """
    return {
        "bands": PM25_BANDS,
        "emission_factors": EMISSION_FACTORS,
        "ceiling_m": 2.7,
        "target_ach": 4,
        "activity_hours": ACTIVITY_HOURS,
    }


@app.route("/about", methods=["GET"])
def route_about() -> str:
    """Render the about and methodology page.

    Returns:
        Rendered HTML template.
    """
    return render_template("about.html", **about_context())


@app.route("/healthz", methods=["GET"])
def route_healthz() -> tuple[Response, int]:
    """Provide service liveness health check endpoint.

    Returns:
        JSON response indicating ok status.
    """
    return jsonify({"status": "ok"}), 200


@app.route("/api/options", methods=["GET"])
def route_options() -> tuple[Response, int]:
    """Return static selection metadata, bands, and form limits.

    Returns:
        JSON response containing options schema.
    """
    return jsonify(_options_payload()), 200


@app.route("/api/plan", methods=["POST"])
def route_api_plan() -> tuple[Response, int]:
    """Compute stateless advisory plan from submitted inputs.

    Returns:
        JSON response with computed plan or error payload.
    """
    if rate_limited(GENERAL_TRACKER, APP_CONFIG["RATE_LIMIT_GENERAL"]):
        msg = "Too many requests. Please wait a minute and try again."
        return error_response(msg, "RATE_LIMITED", 429)
    data, err_resp = parse_body()
    if err_resp is not None:
        return err_resp
    assert data is not None
    advice, _cleaned, build_err = build_advice_or_error(data)
    if build_err is not None:
        return build_err
    assert advice is not None
    return jsonify({"advice": advice, "reading": reading_summary(advice)}), 200


@app.route("/api/explain", methods=["POST"])
def route_api_explain() -> tuple[Response, int]:
    """Generate Gemini explanation of advisory plan with rule-based fallback.

    Returns:
        JSON response with structured explanation or error payload.
    """
    if rate_limited(AI_TRACKER, APP_CONFIG["RATE_LIMIT_AI"]):
        msg = "Too many requests. Please wait a minute and try again."
        return error_response(msg, "RATE_LIMITED", 429)
    data, err_resp = parse_body()
    if err_resp is not None:
        return err_resp
    assert data is not None
    advice, cleaned, build_err = build_advice_or_error(data)
    if build_err is not None:
        return build_err
    assert advice is not None and cleaned is not None
    explanation = explain_plan(advice, cleaned["city"], cleaned["notes"], get_api_key())
    payload = {
        "explanation": explanation,
        "reading": reading_summary(advice),
        "disclaimer": AI_DISCLAIMER,
    }
    return jsonify(payload), 200


def _extract_user_question(
    data: Any
) -> tuple[str, Optional[tuple[Response, int]]]:
    """Extract and validate user question string.

    Args:
        data: Request payload dictionary.

    Returns:
        Tuple of (sanitized_question, error_response_tuple).
    """
    raw_q = data.get("question") if isinstance(data, dict) else ""
    q_str = str(raw_q) if raw_q is not None else ""
    q = sanitize_text_input(q_str, AI_CONFIG["MAX_QUESTION_CHARS"])
    if not q:
        return "", error_response("Question cannot be empty.", "EMPTY_QUESTION", 400)
    return q, None


def _format_ask_payload(res: dict[str, Any], advice: dict[str, Any]) -> dict[str, Any]:
    """Build response payload dictionary for user Q&A.

    Args:
        res: Answer result dictionary.
        advice: Plan dictionary.

    Returns:
        JSON response payload.
    """
    return {
        "answer": res.get("answer", ""),
        "source": res.get("source", "ai"),
        "reading": reading_summary(advice),
        "disclaimer": AI_DISCLAIMER,
    }


@app.route("/api/ask", methods=["POST"])
def route_api_ask() -> tuple[Response, int]:
    """Answer user inquiry grounded strictly in the computed plan.

    Returns:
        JSON response with grounded answer or error payload.
    """
    if rate_limited(AI_TRACKER, APP_CONFIG["RATE_LIMIT_AI"]):
        msg = "Too many requests. Please wait a minute and try again."
        return error_response(msg, "RATE_LIMITED", 429)
    data, err_resp = parse_body()
    if err_resp is not None:
        return err_resp
    assert data is not None
    q, q_err = _extract_user_question(data)
    if q_err is not None:
        return q_err
    advice, cleaned, build_err = build_advice_or_error(data)
    if build_err is not None:
        return build_err
    assert advice is not None and cleaned is not None
    res = answer_question(advice, cleaned["city"], q, get_api_key())
    return jsonify(_format_ask_payload(res, advice)), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
