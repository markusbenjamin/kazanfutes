"""Offline regression tests for the deployed presence-pattern calculation.

The service body executes against mocked I/O. No service imports, files, devices,
or exported production profiles are changed by these tests.
"""
import ast
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import unittest

from utils.occupancy import (
    filter_training_log, known_presence_fraction, select_training_sources,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "services/presence_pattern_calculator.py"


def source(name, kind="motion", identity="current"):
    return {"schema_version": 2, "source_name": name, "source_id": identity,
            "signal_type": kind, "state": True, "reachable": True}


class TrainingSourceTests(unittest.TestCase):
    def test_legacy_motion_kept_and_old_radar_excluded(self):
        sources = {"1": {"source_name": "PIR", "source_id": "pir", "signal_type": "motion"},
                   "4": {"source_name": "Aqara2", "source_id": "radar", "signal_type": "presence"}}
        rows = [{"timestamp": "old", "states": {
            "1": {"state": True, "reachable": True},
            "4": {"state": True, "reachable": True}}},
            {"timestamp": "new", "states": {
                "1": source("PIR", identity="pir"),
                "4": source("Aqara2", "presence", "radar")}}]
        result = filter_training_log(rows, sources)
        self.assertEqual(set(result[0]["states"]), {"1"})
        self.assertEqual(set(result[1]["states"]), {"1", "4"})
        self.assertIn("4", rows[0]["states"])  # Input is never mutated.

    def test_current_physical_source_required_for_versioned_history(self):
        rooms = {"4": {"pres": "Aqara2"}, "6": {"pres": False}}
        rows = [{"states": {"4": source("Pres1", identity="old")}},
                {"states": {"4": source("Aqara2", "presence", "previous")}},
                {"states": {"4": source("Aqara2", "presence", "current")}}]
        sources = select_training_sources(rows, rooms)
        kept = filter_training_log(rows, sources)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["states"]["4"]["source_id"], "current")

    def test_unidentified_room_stays_unknown(self):
        self.assertEqual(filter_training_log([{"states": {"6": {"state": True}}}], {}), [])


class CalculatorRegressionTests(unittest.TestCase):
    def run_calculator(self, known=True, fraction=None):
        tree = ast.parse(SOURCE.read_text())
        tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
        exports, logs, errors = [], [], []
        class Clock(datetime):
            @classmethod
            def now(cls):
                return cls(2026, 10, 21, 12)
        class ModuleError(Exception):
            def __init__(self, message, severity=0):
                super().__init__(message)
                self.severity = severity
        rooms = {"1": {"pres": "PIR"}, "4": {"pres": "Aqara2"}, "6": {"pres": False}}
        recent = [{"states": {"1": source("PIR"), "4": source("Aqara2", "presence")}}]
        def transpose(mapping):
            result = defaultdict(dict)
            for outer, values in mapping.items():
                for inner, value in values.items():
                    result[inner][outer] = value
            return dict(result)
        def occupancy(**kw):
            return {ts: {"1": (True if i == 0 else None if i == 1 else False) if known else None,
                         "4": None, "6": None}
                    for i, ts in enumerate(kw["timestamps"])}
        env = {
            "settings": {"dev": False}, "datetime": Clock, "timedelta": timedelta, "os": os,
            "get_rooms_info": lambda: rooms, "load_recent_presence_log": lambda: recent,
            "select_training_sources": select_training_sources, "filter_training_log": filter_training_log,
            "load_ndjson_to_json_list": lambda path: recent,
            "generate_timepoint_info": lambda day: {"day_of_week": day.isoweekday()},
            "get_rooms_occupancy": occupancy, "transpose_dict": transpose,
            "known_presence_fraction": fraction or known_presence_fraction,
            "mean_without_none": lambda values, default: (
                sum(v for v in values if v is not None) / sum(v is not None for v in values)
                if any(v is not None for v in values) else default),
            "get_project_root": lambda: "/mock-project",
            "atomic_write_json": lambda path, value: exports.append(deepcopy(value)),
            "log": logs.append, "report": lambda *a, **kw: None,
            "ModuleException": ModuleError,
            "ServiceException": lambda *a, **kw: errors.append((a, kw)),
        }
        exit_code = 0
        try:
            exec(compile(tree, str(SOURCE), "exec"), env)
        except SystemExit as error:
            exit_code = error.code
        return exports, logs, errors, exit_code

    def test_real_dictionary_call_produces_probabilities_not_unknown(self):
        exports, logs, errors, code = self.run_calculator()
        self.assertEqual(code, 0)
        self.assertFalse(errors)
        self.assertEqual(len(exports), 1)
        values = [v for hours in exports[0]["1"].values() for v in hours.values()]
        self.assertEqual(len(values), 168)
        for value in values:
            self.assertAlmostEqual(value, 1 / 11)  # One occupied, ten vacant, one unknown.
        self.assertTrue(all(v is None for hours in exports[0]["6"].values() for v in hours.values()))
        coverage = next(row["occupancy_profile_coverage"] for row in logs if "occupancy_profile_coverage" in row)
        self.assertEqual(coverage["1"]["known_hours"], 168)
        self.assertEqual(coverage["6"]["unknown_hours"], 168)
        self.assertIn({"success": True}, logs)

    def test_all_unknown_data_is_reported_as_degraded_and_preserves_null(self):
        exports, logs, errors, code = self.run_calculator(known=False)
        self.assertEqual(code, 1)
        self.assertTrue(errors)
        self.assertTrue(all(v is None for room in exports[0].values()
                            for hours in room.values() for v in hours.values()))
        self.assertIn({"success": False}, logs)

    def test_bad_aggregation_cannot_publish_empty_profiles_from_known_samples(self):
        exports, logs, errors, code = self.run_calculator(fraction=lambda values: None)
        self.assertEqual(code, 1)
        self.assertFalse(exports)
        self.assertTrue(errors)
        self.assertIn({"success": False}, logs)

    def test_confirmed_absence_is_zero_and_unknown_is_not_zero(self):
        self.assertEqual(known_presence_fraction([False, False, None]), 0)
        self.assertIsNone(known_presence_fraction([None, None]))
        self.assertAlmostEqual(known_presence_fraction([True, False, None]), .5)


if __name__ == "__main__":
    unittest.main()
