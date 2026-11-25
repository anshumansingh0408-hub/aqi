"""Unit tests for the Saans smog advisor engine.

Covers band classifications, health sensitivity, activity guidance, forecast windows,
commute footprint calculations, purifier sizing, and indoor checklists.
"""

import datetime
import unittest
from advisor import (
    CLIMATE_NOTE,
    MEDICAL_NOTE,
    TIERS,
    activity_guidance,
    advice_tier,
    compare_commute,
    compare_usual_vs_best,
    commute_emissions,
    find_best_window,
    generate_advice,
    household_sensitivity,
    indoor_checklist,
    pm25_band,
    purifier_sizing,
)


class TestAdvisorBandsAndTiers(unittest.TestCase):
    """Tests for PM2.5 band categorization and advisory tier mapping."""

    def test_pm25_band_boundaries(self) -> None:
        """Verify boundary transitions between consecutive AQI breakpoints."""
        self.assertEqual(pm25_band(0)["key"], "good")
        self.assertEqual(pm25_band(30)["key"], "good")
        self.assertEqual(pm25_band(31)["key"], "satisfactory")
        self.assertEqual(pm25_band(60)["key"], "satisfactory")
        self.assertEqual(pm25_band(61)["key"], "moderate")
        self.assertEqual(pm25_band(90)["key"], "moderate")
        self.assertEqual(pm25_band(91)["key"], "poor")
        self.assertEqual(pm25_band(120)["key"], "poor")
        self.assertEqual(pm25_band(121)["key"], "very_poor")
        self.assertEqual(pm25_band(250)["key"], "very_poor")
        self.assertEqual(pm25_band(251)["key"], "severe")
        self.assertEqual(pm25_band(500)["key"], "severe")

    def test_pm25_band_invalid(self) -> None:
        """Verify negative values and non-numeric inputs raise ValueError."""
        with self.assertRaises(ValueError):
            pm25_band(-1.0)
        with self.assertRaises(ValueError):
            pm25_band(-0.01)
        with self.assertRaises(ValueError):
            pm25_band(float("nan"))
        with self.assertRaises(ValueError):
            pm25_band(True)  # type: ignore[arg-type]

    def test_advice_tier_all_bands(self) -> None:
        """Verify action tiers for all six bands in general and sensitive modes."""
        expected = {
            "good": ("normal", "normal"),
            "satisfactory": ("normal", "caution"),
            "moderate": ("caution", "restrict"),
            "poor": ("restrict", "avoid"),
            "very_poor": ("avoid", "avoid"),
            "severe": ("avoid", "avoid"),
        }
        for band_key, (gen_tier, sens_tier) in expected.items():
            self.assertEqual(advice_tier(band_key, sensitive=False), gen_tier)
            self.assertEqual(advice_tier(band_key, sensitive=True), sens_tier)

    def test_advice_tier_unknown_band(self) -> None:
        """Verify unknown band keys raise ValueError."""
        with self.assertRaises(ValueError):
            advice_tier("hazardous", sensitive=False)


class TestHouseholdAndGuidance(unittest.TestCase):
    """Tests for household sensitivity scoring and activity precautionary guidance."""

    def test_household_sensitivity_one_child(self) -> None:
        """Verify a single child flags the household as sensitive."""
        res = household_sensitivity({"children": 1, "elderly": 0})
        self.assertTrue(res["sensitive"])
        self.assertIn("Children", res["groups"])

    def test_household_sensitivity_empty(self) -> None:
        """Verify an empty profile is not flagged as sensitive."""
        res = household_sensitivity({})
        self.assertFalse(res["sensitive"])
        self.assertEqual(res["groups"], [])

    def test_household_sensitivity_all_groups(self) -> None:
        """Verify all demographic risk factors generate readable group names."""
        hh = {
            "children": 2, "elderly": 1, "respiratory": True, "heart": True, "pregnant": True,
        }
        res = household_sensitivity(hh)
        self.assertTrue(res["sensitive"])
        self.assertIn("Children", res["groups"])
        self.assertIn("Elderly", res["groups"])
        self.assertIn("Respiratory conditions", res["groups"])
        self.assertIn("Heart conditions", res["groups"])
        self.assertIn("Pregnant individuals", res["groups"])

    def test_activity_guidance_outdoor_exercise_restricted(self) -> None:
        """Verify outdoor exercise is prohibited in restrict and avoid tiers."""
        for tier in ("restrict", "avoid"):
            g = activity_guidance(tier)
            self.assertFalse(g["outdoor_exercise"]["allowed"])

    def test_activity_guidance_window_ventilation(self) -> None:
        """Verify window ventilation in restrict advises daytime airing."""
        g = activity_guidance("restrict")
        self.assertIn("daytime window", g["window_ventilation"]["advice"].lower())

    def test_activity_guidance_prohibited_terms(self) -> None:
        """Verify advice texts never contain 'guarantee', 'safe from', or 'cure'."""
        forbidden = ["guarantee", "safe from", "cure"]
        for tier in TIERS:
            guidance = activity_guidance(tier)
            for act_info in guidance.values():
                adv_lower = act_info["advice"].lower()
                for word in forbidden:
                    self.assertNotIn(word, adv_lower)


class TestForecastWindows(unittest.TestCase):
    """Tests for finding clean air windows and baseline comparisons."""

    def test_find_best_window_picks_lowest_average(self) -> None:
        """Verify the window with minimum average PM2.5 is selected."""
        hourly = [
            {"time": "2026-11-18T06:00:00", "pm25": 180.0},
            {"time": "2026-11-18T07:00:00", "pm25": 140.0},
            {"time": "2026-11-18T08:00:00", "pm25": 90.0},
            {"time": "2026-11-18T09:00:00", "pm25": 60.0},
            {"time": "2026-11-18T10:00:00", "pm25": 110.0},
        ]
        best = find_best_window(hourly, earliest=6, latest=10, hours=1)
        self.assertIsNotNone(best)
        self.assertEqual(best["hour"], 9)
        self.assertEqual(best["avg_pm25"], 60.0)

    def test_find_best_window_respects_hour_limits(self) -> None:
        """Verify candidate windows outside allowed hour ranges are excluded."""
        hourly = [
            {"time": "2026-11-18T04:00:00", "pm25": 20.0},
            {"time": "2026-11-18T08:00:00", "pm25": 120.0},
        ]
        best = find_best_window(hourly, earliest=6, latest=10, hours=1)
        self.assertIsNotNone(best)
        self.assertEqual(best["hour"], 8)

    def test_find_best_window_skips_none_and_averages_multi_hour(self) -> None:
        """Verify consecutive multi-hour window averaging and skipping None entries."""
        hourly = [
            {"time": "2026-11-18T08:00:00", "pm25": 100.0},
            {"time": "2026-11-18T09:00:00", "pm25": None},
            {"time": "2026-11-18T10:00:00", "pm25": 40.0},
            {"time": "2026-11-18T11:00:00", "pm25": 60.0},
        ]
        best = find_best_window(hourly, earliest=8, latest=11, hours=2)
        self.assertIsNotNone(best)
        self.assertEqual(best["hour"], 10)
        self.assertEqual(best["avg_pm25"], 50.0)

    def test_find_best_window_empty(self) -> None:
        """Verify empty input returns None."""
        self.assertIsNone(find_best_window([], 6, 20))

    def test_compare_usual_vs_best_arithmetic(self) -> None:
        """Verify reduction percentage calculation against hand-crafted 24-hour forecast."""
        hourly = [
            {"time": f"2026-11-18T{h:02d}:00:00", "pm25": 200.0 if h == 8 else 50.0}
            for h in range(24)
        ]
        comp = compare_usual_vs_best(hourly, usual_hour=8, earliest=6, latest=20)
        self.assertIsNotNone(comp)
        self.assertEqual(comp["usual_hour"], 8)
        self.assertEqual(comp["usual_pm25"], 200.0)
        self.assertEqual(comp["reduction_pct"], 75)
        self.assertTrue(comp["is_forecast"])
        self.assertIn("forecast values", comp["note"].lower())
        self.assertIn("next time you are due to go out at that hour", comp["note"].lower())

    def test_compare_usual_vs_best_zero_when_usual_is_best(self) -> None:
        """Verify reduction percentage is zero when usual hour already has lowest PM2.5."""
        hourly = [
            {"time": f"2026-11-18T{h:02d}:00:00", "pm25": 40.0 if h == 7 else 150.0}
            for h in range(24)
        ]
        comp = compare_usual_vs_best(hourly, usual_hour=7, earliest=6, latest=20)
        self.assertIsNotNone(comp)
        self.assertEqual(comp["reduction_pct"], 0)

    def test_compare_usual_vs_best_missing_usual_hour(self) -> None:
        """Verify None is returned when the specified usual hour has no data."""
        hourly = [{"time": "2026-11-18T06:00:00", "pm25": 100.0}]
        self.assertIsNone(compare_usual_vs_best(hourly, usual_hour=9, earliest=6, latest=20))

    def test_compare_usual_vs_best_next_occurrence_tomorrow(self) -> None:
        """Verify list starting at 21:00 for 24 entries finds usual_hour 8 tomorrow."""
        start = datetime.datetime(2026, 11, 18, 21, 0)
        hourly = []
        for i in range(24):
            dt = start + datetime.timedelta(hours=i)
            pm = 180.0 if dt.hour == 8 else 40.0
            hourly.append({"time": dt.isoformat(), "pm25": pm})
        comp = compare_usual_vs_best(hourly, usual_hour=8, earliest=6, latest=20)
        self.assertIsNotNone(comp)
        self.assertEqual(comp["usual_hour"], 8)
        self.assertEqual(comp["usual_pm25"], 180.0)
        self.assertEqual(comp["reduction_pct"], round((180.0 - 40.0) / 180.0 * 100))
        self.assertIn("next time you are due to go out at that hour", comp["note"].lower())


class TestCommuteAndPurifier(unittest.TestCase):
    """Tests for commute emissions comparison and air purifier CADR sizing."""

    def test_commute_emissions_formula(self) -> None:
        """Verify exact monthly emissions calculation for standard parameters."""
        expected = round(0.192 * 10 * 2 * 5 * 4.33, 1)
        self.assertEqual(commute_emissions("car_petrol", 10.0, 5), expected)
        self.assertEqual(commute_emissions("walk_cycle", 5.0, 5), 0.0)
        carpool_expected = round((0.192 / 2) * 10 * 2 * 5 * 4.33, 1)
        self.assertEqual(commute_emissions("carpool", 10.0, 5, occupants=2), carpool_expected)

    def test_commute_emissions_invalid_inputs(self) -> None:
        """Verify negative values and unknown transit modes raise ValueError."""
        with self.assertRaises(ValueError):
            commute_emissions("car_petrol", -5.0, 5)
        with self.assertRaises(ValueError):
            commute_emissions("rocket", 10.0, 5)

    def test_compare_commute_filtering_and_sorting(self) -> None:
        """Verify mode exclusions, 5km walk limit, and descending savings sort."""
        comps = compare_commute("car_petrol", km_one_way=10.0, days_per_week=5)
        modes = [item["mode"] for item in comps]
        self.assertNotIn("car_petrol", modes)
        self.assertNotIn("walk_cycle", modes)
        savings = [item["saving_kg"] for item in comps]
        self.assertEqual(savings, sorted(savings, reverse=True))
        for item in comps:
            self.assertIn("Assumes", item["assumption"])
            self.assertGreater(item["saving_kg"], 0.5)

        short_comps = compare_commute("car_petrol", km_one_way=3.0, days_per_week=5)
        short_modes = [item["mode"] for item in short_comps]
        self.assertIn("walk_cycle", short_modes)

    def test_purifier_sizing_calculation(self) -> None:
        """Verify 20 sqm room yields 54 m3 volume and 216 m3/h min CADR."""
        sizing = purifier_sizing(20.0)
        self.assertEqual(sizing["volume_m3"], 54.0)
        self.assertEqual(sizing["min_cadr_m3h"], 216)
        self.assertIn("Assumes a 2.7 m ceiling", sizing["assumption"])

    def test_purifier_sizing_out_of_range(self) -> None:
        """Verify rooms below 5 sqm or above 200 sqm raise ValueError."""
        with self.assertRaises(ValueError):
            purifier_sizing(4.9)
        with self.assertRaises(ValueError):
            purifier_sizing(201.0)


class TestIndoorChecklistAndAdvice(unittest.TestCase):
    """Tests for checklist generation rules and comprehensive advice synthesis."""

    def test_indoor_checklist_biomass_and_purifier(self) -> None:
        """Verify biomass triggers fuel switch and purifier presence toggles suggestions."""
        hh = {"children": 0}
        ls1 = {"cooking": "biomass", "has_purifier": False, "smokers": False}
        checklist1 = indoor_checklist("restrict", hh, ls1)
        actions1 = [item["action"].lower() for item in checklist1]
        self.assertTrue(any("biomass" in a or "switch" in a for a in actions1))
        self.assertTrue(any("purifier" in a for a in actions1))

        ls2 = {"cooking": "induction", "has_purifier": True, "smokers": False}
        checklist2 = indoor_checklist("restrict", hh, ls2)
        actions2 = [item["action"].lower() for item in checklist2]
        self.assertFalse(any("suggest a purifier" in a for a in actions2))

    def test_indoor_checklist_plants_truth(self) -> None:
        """Verify plants item is always included with an honest limitation statement."""
        checklist = indoor_checklist("normal", {}, {"has_purifier": False})
        plant_item = next(item for item in checklist if item["action"] == "Indoor plants")
        self.assertIn("very little", plant_item["why"].lower())

    def test_generate_advice_empty_hourly(self) -> None:
        """Verify generate_advice handles missing forecast gracefully with limits."""
        inputs = {
            "city": "Delhi",
            "household": {"children": 1},
            "lifestyle": {"room_area_sqm": 25.0, "commute_km_one_way": 10.0},
        }
        air = {"pm25": 180.0, "hourly": [], "source": "live", "observed_at": "2026-11-18T10:00:00"}
        advice = generate_advice(inputs, air)
        self.assertEqual(advice["tier"], "avoid")
        self.assertIsNone(advice["usual_vs_best"])
        self.assertIsNone(advice["windows"]["outdoor_exercise"])
        self.assertTrue(len(advice["limits"]) > 0)
        self.assertIn(CLIMATE_NOTE, advice["commute"]["note"])
        self.assertIn(MEDICAL_NOTE, advice["medical_note"])


if __name__ == "__main__":
    unittest.main()
