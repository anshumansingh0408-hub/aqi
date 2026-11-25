"""CLI helper to query real Open-Meteo air quality and best activity window.

Usage:
    python scripts/try_air.py "Delhi"
    python scripts/try_air.py "Nowhereville12345"
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor import find_best_window, pm25_band  # noqa: E402
from air_client import AirDataError, get_air_reading  # noqa: E402


def main() -> None:
    """Run interactive air quality lookup for a given city argument."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/try_air.py <city_name>")
        sys.exit(1)

    city = sys.argv[1]
    try:
        data = get_air_reading(city)
        _ = data["location"]
        print("Location resolved successfully.")
        print(f"Observed at: {data['observed_at']}")
        print(f"Current PM2.5: {data['pm25']} µg/m³")
        band = pm25_band(data["pm25"])
        print(f"Air Quality Band: {band['label']} ({band['key']})")

        best = find_best_window(data["hourly"], earliest=8, latest=19, hours=1)
        if best:
            print(
                f"Best 1-hour window (08:00-19:00): {best['start']} "
                f"(avg PM2.5: {best['avg_pm25']} µg/m³)"
            )
        else:
            print("Best 1-hour window (08:00-19:00): None available in forecast")
    except AirDataError as exc:
        print(f"Error [{exc.code}]: {exc.message}")
        sys.exit(0)
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
