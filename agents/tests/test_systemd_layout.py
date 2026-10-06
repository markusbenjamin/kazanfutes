from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIRECTORY = PROJECT_ROOT / "services"
UNIT_DIRECTORY = SERVICES_DIRECTORY / "systemd"
MANIFEST_PATH = UNIT_DIRECTORY / "services_and_timers.list"
SUPPORT_UNITS = {
    "kazanfutes-recover.service",
    "kazanfutes-recover.timer",
    "kazanfutes.target",
}


def manifest_units() -> list[str]:
    return [
        line.strip()
        for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class SystemdLayoutTests(unittest.TestCase):
    def test_manifest_entries_are_unique_and_have_source_files(self):
        units = manifest_units()
        self.assertEqual(len(units), len(set(units)))
        self.assertEqual([], [unit for unit in units if not (UNIT_DIRECTORY / unit).is_file()])

    def test_every_real_unit_is_classified(self):
        units = set(manifest_units())
        source_units = {
            path.name
            for path in UNIT_DIRECTORY.iterdir()
            if path.is_file() and path.suffix in {".service", ".timer", ".target"}
        }
        self.assertEqual(source_units, units | SUPPORT_UNITS)

    def test_templates_are_separate_and_not_managed(self):
        units = set(manifest_units())
        templates = UNIT_DIRECTORY / "templates"
        self.assertTrue((templates / "template.service").is_file())
        self.assertTrue((templates / "template.timer").is_file())
        self.assertNotIn("template.service", units)
        self.assertNotIn("template.timer", units)

    def test_service_root_contains_no_unit_definitions(self):
        leftovers = [
            path.name
            for path in SERVICES_DIRECTORY.iterdir()
            if path.is_file() and path.suffix in {".service", ".timer", ".target"}
        ]
        self.assertEqual([], leftovers)


if __name__ == "__main__":
    unittest.main()
