"""Synthetic tests for hourly alignment and independent array references."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "utils"))
from pv_array_weather import hourly_points, replay


def observations(first, last, power=15.):
    samples, weather = [], {}
    for day in range(first, last):
        for hour in range(9, 15):
            start = int(datetime(2026, 6, day, hour, tzinfo=timezone.utc).timestamp())
            weather[start + 3600] = {"ghi": 600., "diffuse": 100., "temperature": 20.}
            samples.extend(SimpleNamespace(epoch=start + minute * 60, day=f"2026-06-{day:02d}",
                                           ac_kw=power, usable=True) for minute in range(0, 60, 5))
    return samples, weather


class ArrayWeatherTests(unittest.TestCase):
    def test_weather_mean_hour_ends_after_pv_samples(self):
        samples, weather = observations(1, 2)
        first_hour = samples[:12]
        end = first_hour[0].epoch + 3600
        points, _ = hourly_points(first_hour, {end: weather[end]})
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["epoch"], end - 1800)
        self.assertFalse(hourly_points(first_hour, {end - 3600: weather[end]})[0])

    def test_missing_hours_are_not_fabricated_but_zero_output_is_retained(self):
        samples, weather = observations(1, 2, power=0.)
        self.assertFalse(hourly_points(samples[:9], weather)[0])
        points, _ = hourly_points(samples[:12], weather)
        self.assertEqual(points[0]["actual_kw"], 0.)

    def test_shared_array_loss_is_visible_with_independent_weather(self):
        reference, weather = observations(1, 15)
        evaluation, later = observations(15, 20, power=9.)
        weather.update(later)
        before = deepcopy(weather)
        result = replay(reference, evaluation, weather, "2026-06-01", "2026-06-15",
                        "2026-06-15", "2026-06-20")
        self.assertTrue(result["candidate_episodes"])
        self.assertEqual(result["candidate_episodes"][0]["opened"], "2026-06-17")
        self.assertEqual(weather, before)
        self.assertTrue(all(s.ac_kw == 15 for s in reference))

    def test_unchanged_output_has_no_candidate_and_no_future_reference(self):
        reference, weather = observations(1, 15)
        evaluation, later = observations(15, 20)
        weather.update(later)
        result = replay(reference, evaluation, weather, "2026-06-01", "2026-06-15",
                        "2026-06-15", "2026-06-20")
        self.assertFalse(result["candidate_episodes"])
        self.assertGreater(sum(r["qualified"] for r in result["daily"]), 0)
        with self.assertRaises(ValueError):
            replay(reference, evaluation, weather, "2026-06-01", "2026-06-16",
                   "2026-06-15", "2026-06-20")


if __name__ == "__main__":
    unittest.main()
