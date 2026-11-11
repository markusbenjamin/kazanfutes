"""Exercise the actual learner with timestamp-keyed hourly observations."""
import ast
from collections import defaultdict
from datetime import datetime, timedelta
import os
from pathlib import Path
import runpy
import sys
import types
from typing import Any, Dict
import unittest
from unittest.mock import patch

from utils.occupancy import known_presence_fraction

ROOT = Path(__file__).resolve().parents[2]


class PresencePatternLearningTests(unittest.TestCase):
    def test_hourly_values_are_averaged_and_unknowns_remain_unknown(self):
        namespace = {"defaultdict": defaultdict, "Dict": Dict, "Any": Any}
        tree = ast.parse((ROOT / "utils/project.py").read_text(encoding="utf-8"))
        transpose = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "transpose_dict")
        exec(compile(ast.Module(body=[transpose], type_ignores=[]), "transpose_dict", "exec"), namespace)
        exported, errors = [], []
        samples = {
            "4": [True] * 7 + [False] * 5,
            "5": [True, None, False] * 4,
            "8": [None] * 12,
            "24": [False] * 12,
        }
        project = types.ModuleType("utils.project")
        project.__dict__.update(
            settings={}, datetime=datetime, timedelta=timedelta, os=os,
            get_rooms_info=lambda controlled: {room: {} for room in samples},
            load_ndjson_to_json_list=lambda path: [],
            generate_timepoint_info=lambda day: {"day_of_week": day.isoweekday()},
            get_rooms_occupancy=lambda *, log, threshold, timestamps: {
                stamp: {room: values[index] for room, values in samples.items()}
                for index, stamp in enumerate(timestamps)
            },
            transpose_dict=namespace["transpose_dict"],
            known_presence_fraction=known_presence_fraction,
            mean_without_none=lambda values, empty: (
                sum(known) / len(known) if (known := [v for v in values if v is not None]) else empty
            ),
            export_dict_as_json=lambda value, path: exported.append(value),
            report=lambda *args, **kwargs: None,
            ModuleException=RuntimeError,
            ServiceException=lambda *args, **kwargs: errors.append(args),
        )
        with patch.dict(sys.modules, {"utils.project": project}):
            runpy.run_path(str(ROOT / "services/presence_pattern_calculator.py"))
        self.assertFalse(errors)
        self.assertEqual(len(exported), 1)
        for room, expected in [("4", 7 / 12), ("5", .5), ("8", None), ("24", 0)]:
            profile = exported[0][room]
            self.assertEqual(len(profile), 7)
            for hours in profile.values():
                self.assertEqual(len(hours), 24)
                for value in hours.values():
                    if expected is None:
                        self.assertIsNone(value)
                    else:
                        self.assertAlmostEqual(value, expected)


if __name__ == "__main__":
    unittest.main()
