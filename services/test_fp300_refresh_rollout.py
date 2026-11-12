"""Guarded rollout changes only the two non-pilot FP300 readers."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.test_fp300_refresh_pilot import common_fixture
from utils.fp300_refresh_pilot import CLUSTERS, COMMON_MATCH, PILOT_MATCH, build_documents
from utils.fp300_refresh_rollout import install, prepare, reader, rollout_document


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.common, self.pilot = build_documents(common_fixture())

    def test_only_two_common_readers_change_and_inputs_remain_unchanged(self):
        common_before = copy.deepcopy(self.common); pilot_before = copy.deepcopy(self.pilot)
        actual = rollout_document(self.common, self.pilot)
        self.assertEqual(self.common, common_before); self.assertEqual(self.pilot, pilot_before)
        for sub in actual["subdevices"]:
            for item in sub["items"]:
                if item.get("name") in CLUSTERS:
                    self.assertEqual(item.pop("read"), reader(CLUSTERS[item["name"]]))
                    self.assertEqual(item.pop("refresh.interval"), 900)
        # Includes the exact MAC filter, presence behavior, parsers and metadata.
        self.assertEqual(actual, self.common)
        self.assertEqual(actual["matchexpr"], COMMON_MATCH)
        self.assertEqual(self.pilot["matchexpr"], PILOT_MATCH)

    def test_idempotent(self):
        once = rollout_document(self.common, self.pilot)
        self.assertEqual(rollout_document(once, self.pilot), once)

    def test_other_model_and_missing_or_unknown_match_rejected(self):
        for key, value in (("modelid", "other"), ("matchexpr", None), ("matchexpr", "custom")):
            common = copy.deepcopy(self.common); common[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                rollout_document(common, self.pilot)

    def test_custom_reader_or_interval_is_not_overwritten(self):
        for fields in ({"read": {"fn": "none"}}, {"refresh.interval": 60},
                       {"read": reader("0x0405"), "refresh.interval": 600}):
            common = copy.deepcopy(self.common); common["subdevices"][-1]["items"][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                rollout_document(common, self.pilot)

    def test_missing_duplicate_and_changed_endpoint_rejected(self):
        for kind in ("missing", "duplicate", "endpoint", "awake"):
            common = copy.deepcopy(self.common)
            if kind == "missing": common["subdevices"].pop()
            elif kind == "duplicate": common["subdevices"].append(copy.deepcopy(common["subdevices"][-1]))
            elif kind == "endpoint": common["subdevices"][-1]["fingerprint"]["endpoint"] = "0x02"
            else: common["subdevices"][-1]["items"][0]["awake"] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                rollout_document(common, self.pilot)

    def test_presence_regression_rejected(self):
        common = copy.deepcopy(self.common)
        common["subdevices"][0]["items"][2]["parse"]["eval"] = "Item.val = true;"
        with self.assertRaises(ValueError): rollout_document(common, self.pilot)

    def test_drift_between_common_and_pilot_is_not_silently_reconciled(self):
        for name in ("common", "pilot"):
            common = copy.deepcopy(self.common); pilot = copy.deepcopy(self.pilot)
            (common if name == "common" else pilot)["unchanged"]["value"] = 99
            with self.subTest(name=name), self.assertRaises(ValueError): rollout_document(common, pilot)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.common = Path(self.directory.name)/"common.json"
        self.pilot = self.common.with_name("pilot.json")
        common, pilot = build_documents(common_fixture())
        self.common.write_text(json.dumps(common), encoding="utf-8")
        self.pilot.write_text(json.dumps(pilot), encoding="utf-8")

    def test_preview_does_not_write(self):
        before = {p: p.read_bytes() for p in self.common.parent.iterdir()}
        prepare(self.common, self.pilot)
        self.assertEqual(before, {p: p.read_bytes() for p in self.common.parent.iterdir()})

    def test_install_backs_up_exact_common_bytes_and_never_writes_pilot(self):
        before = self.common.read_bytes(); pilot_before = self.pilot.read_bytes()
        changed, backup = install(self.common, self.pilot)
        self.assertTrue(changed); self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(self.pilot.read_bytes(), pilot_before)
        self.assertEqual(install(self.common, self.pilot), (False, None))

    def test_unknown_pilot_does_not_create_backup_or_modify_files(self):
        self.pilot.write_text('{"custom":true}', encoding="utf-8")
        before = {p: p.read_bytes() for p in self.common.parent.iterdir()}
        with self.assertRaises(ValueError): install(self.common, self.pilot)
        self.assertEqual(before, {p: p.read_bytes() for p in self.common.parent.iterdir()})

    def test_bad_paths_and_symlinks_rejected(self):
        for path in (self.common, self.common.parent/"elsewhere"/"pilot.json", self.pilot.with_suffix(".bak")):
            with self.subTest(path=path), self.assertRaises(ValueError): prepare(self.common, path)
        with patch("pathlib.Path.is_symlink", return_value=True):
            with self.assertRaises(ValueError): prepare(self.common, self.pilot)

    def test_failed_atomic_replace_keeps_both_original_files(self):
        common_before = self.common.read_bytes(); pilot_before = self.pilot.read_bytes()
        with patch("utils.fp300_refresh_pilot.os.replace", side_effect=OSError("failure")):
            with self.assertRaises(OSError): install(self.common, self.pilot)
        self.assertEqual(self.common.read_bytes(), common_before)
        self.assertEqual(self.pilot.read_bytes(), pilot_before)
        self.assertFalse(list(self.common.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
