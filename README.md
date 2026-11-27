# Saans: Urban Air Quality Assistant

Saans gives families a plan for days of heavy winter smog (a reading for their city, a routine for their household, indoor air steps and commute alternatives), with the reasoning shown. Every figure is produced by deterministic, tested rules or verified against them.

Live demo: <ADD RAILWAY URL>

## Features

- **Location-specific reading:** Resolves your city via Open-Meteo or accepts a manual PM2.5 measurement from a local monitor.
- **Household profile:** Tailors guidance to children, older adults, lung or heart conditions, and pregnancy.
- **Low-emission daily routine:** Identifies cleaner daylight windows for exercise, errands, and airing the home based on diurnal thermal dispersion.
- **Indoor air checklist and purifier sizing:** Provides prioritized indoor interventions and computes minimum CADR ratings based on room dimensions.
- **Commute alternatives with CO2 figures:** Calculates estimated monthly travel emissions and compares cleaner transit swaps with stated assumptions.
- **Plain-language explanation of impact:** Synthesizes the computed plan into conversational advice using a language model (Groq by default, Google Gemini as an alternative), strictly grounded in the rules engine output.
- **Questions about your own plan:** Interactive Q&A strictly constrained to your computed plan details.

## How It Works

- `advisor.py` is a deterministic, tested rules engine that produces every number.
- `air_client.py` fetches a PM2.5 reading and a 24-hour forecast from Open-Meteo.
- `ai_client.py` asks the language model (Groq by default, Google Gemini as an alternative) to explain the computed plan, and any figure with a unit that is not in the plan is removed from the AI's output before the user sees it.
- If the language model is unavailable or rate-limited, the app builds the explanation directly from the rules engine. If the Groq free tier rate-limits a request, the app falls back to rule-based explanations; failed calls are not cached.
- A manual PM2.5 entry works with no network call.

## Architecture

```
saans/
├── app.py                     # Flask web server, stateless API endpoints, rate limiting, and security headers
├── advisor.py                 # Deterministic rule engine for PM2.5 bands, activity windows, and purifier sizing
├── air_client.py              # Open-Meteo geocoding and air quality client with in-memory caching and timeouts
├── ai_client.py               # Multi-provider AI client (Groq, Gemini) with strict numeric grounding and fallback
├── utils.py                   # Input validation, sliding-window rate limit logic, and text sanitization
├── test_advisor.py            # Unit tests for bands, activity hours, commute formulas, and purifier sizing
├── test_air_client.py         # Unit tests for geocoding, air API response parsing, and cache invalidation
├── test_ai_client.py          # Unit tests for prompt construction, numeric grounding, and LLM error handling
├── test_app.py                # Integration tests for routes, validation, rate limits, headers, and views
├── test_quality.py            # AST quality gate enforcing docstrings, type annotations, and function length limits
├── test_utils.py              # Unit tests for rate limiting, cache key generation, and nested input validation
├── requirements.txt           # Python application dependencies (Flask, requests, flask-compress, gunicorn)
├── pyproject.toml             # Configuration for pytest and flake8 code quality tools
├── .env                       # Environment variables configuration template (not tracked in git)
├── .gitignore                 # Git ignore rules for virtual environments, secrets, and cache artifacts
├── Dockerfile                 # Container image specification for deployment environments
├── .dockerignore              # Docker build exclusion rules
├── Procfile                   # Process runner declaration for container and platform deployments
├── README.md                  # Project overview, architecture, assumptions, security, and setup documentation
├── scripts/
│   ├── smoke_test.py          # Deployment smoke test script verifying live endpoints without pytest
│   ├── try_ai.py              # CLI diagnostic tool to run AI explanations and inspect fallback logic
│   └── try_air.py             # CLI diagnostic tool to query Open-Meteo readings and best activity windows
├── static/
│   ├── css/
│   │   └── app.css            # Stylesheet containing accessible focus rings, band chips, and print rules
│   └── js/
│       ├── common.js          # Shared utility functions, API wrapper, and DOM element builders
│       ├── create.js          # Client-side input validation, error summary management, and session storage
│       ├── landing.js         # Landing page preview card population from sample API data
│       └── plan.js            # WAI-ARIA tabbed dashboard rendering air plan, purifier specs, and Q&A stream
└── templates/
    ├── base.html              # Base HTML skeleton with CSP, responsive navbar, skip link, and footer
    ├── landing.html           # Landing page explaining features, process steps, and FAQs
    ├── create.html            # Household profile creation form with structured fieldsets and validation
    ├── plan.html              # Comprehensive air quality action plan dashboard with 5-tab interface
    └── about.html             # Methodology and scientific assumptions documentation page
```

## Assumptions and Limits

- PM2.5 bands follow our reading of the CPCB breakpoints and are applied to an hourly reading rather than the 24-hour average, so they are approximate.
- Open-Meteo values are model estimates, not ground sensor readings.
- Emission factors, the purifier rule (2.7 m ceiling, about 4 air changes per hour) and the activity time limits are planning assumptions.
- CO2 figures are a climate impact, not a measure of cleaner local air.
- General precautions only, not medical advice.
- English only.
- If a city name is ambiguous the first match is used and alternatives are listed.

## Data Sources and Attribution

- Open-Meteo (geocoding and air quality APIs).
- Check Open-Meteo's terms of use for attribution and usage limits before heavy or commercial use.

## Security

- API key read server-side only and sent in a header, never logged or returned.
- Input validation reports all errors at once without echoing input values.
- Per-IP rate limits (30 requests per minute general, 10 per minute AI) with tracking dictionaries pruned automatically.
- Security headers configured on all responses, including a strict Content Security Policy (CSP).
- User notes and questions passed to the model as delimited data blocks to contain injection attempts.
- AI output rendered with `textContent` only; zero usage of `innerHTML`.
- Request size limit enforced at 32 KB.
- No request bodies logged.
- Health details kept in browser `sessionStorage`, never `localStorage`.

## Efficiency

- Air lookups cached for 15 minutes and geocoding cached for 24 hours in thread-safe memory caches.
- AI responses cached for 15 minutes (failures are not cached).
- HTTP response gzip compression enabled via Flask-Compress.
- Static assets cached with 1-hour Cache-Control headers and cache-busting version query strings.
- Exactly one AI call per button press.
- Compact prompt context minimizing token usage.

## Accessibility

- Skip-to-content link for keyboard users.
- Labelled form controls with clear helper text.
- Accessible error summary that takes programmatic focus on validation failure.
- WAI-ARIA keyboard navigation pattern for tabs (arrow keys, Home, End).
- Status communicated in text words alongside color coding.
- Dynamic screen reader announcements via `aria-live` regions.
- High-contrast print stylesheet expanding actionable sections and suppressing interactive navigation.
- Minimum 44px interactive touch targets.

## Testing

Run the full automated test suite:
```bash
python -m pytest -v
```

The test suite covers:
- Deterministic advice generation, band boundaries, activity windows, and purifier calculations (`test_advisor.py`).
- Open-Meteo geocoding, air API response parsing, caching, and network error handling (`test_air_client.py`).
- AI prompt construction, multi-provider dispatch (Groq and Gemini), numeric grounding, and fallback handling (`test_ai_client.py`).
- Flask routing, validation error formatting, rate limiting, security headers, and view rendering (`test_app.py`).
- Utility functions for rate limiting and input sanitization (`test_utils.py`).
- Code quality gate (`test_quality.py`) enforcing docstrings, type annotations, secret leak prevention, and function length limits ($\le 25$ lines) across all core modules.

## Setup

1. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install application dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set your environment variables:
   ```bash
   # Groq is the default AI provider:
   export GROQ_API_KEY=your_groq_key  # On Windows: set GROQ_API_KEY=your_groq_key
   # Optionally select a custom Groq model (defaults to openai/gpt-oss-120b):
   # export GROQ_MODEL=openai/gpt-oss-120b

   # Or select Google Gemini as an alternative:
   # export AI_PROVIDER=gemini
   # export GEMINI_API_KEY=your_gemini_key
   # export GEMINI_MODEL=gemini-2.0-flash
   ```
4. Start the application:
   ```bash
   python app.py
   ```
5. Open `http://localhost:8080` in your browser. Note that without an API key the app still works with rule-based explanations.

## Deploy

To deploy to Railway:
1. Connect your GitHub repository to Railway.
2. In Railway project settings, add the environment variable `GROQ_API_KEY` (or `GEMINI_API_KEY` with `AI_PROVIDER=gemini`).
3. Generate a public domain under Networking.
4. The deployment runs using the command defined in the `Procfile`:
   ```
   web: gunicorn app:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT
   ```
   *Note on concurrency:* The server runs with one worker and four threads because rate-limit trackers and in-memory caches are maintained per process in thread-safe dictionaries.
