"""Regression coverage for MAC-scoped refresh and guarded paired deployment."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from services.test_fp300_ddf_patch import fixture
from utils.fp300_ddf_patch import patch_document
from utils.fp300_refresh_pilot import (
    CLUSTERS, COMMON_MATCH, INTERVAL_SECONDS, PILOT_MAC, PILOT_MATCH,
    PILOT_UUID, atomic_write, build_documents, install, prepare,
)


def common_fixture():
    result = patch_document(fixture())
    result["uuid"] = "original-definition"
    for name, cluster in CLUSTERS.items():
        result["subdevices"].append({"fingerprint": {"endpoint": "0x01", "in": [cluster]},
                                    "items": [{"name": name, "awake": True}]})
    return result


class DocumentTests(unittest.TestCase):
    def test_only_mac_selection_and_two_pilot_readers_change(self):
        original = common_fixture(); snapshot = copy.deepcopy(original)
        ordinary, pilot = build_documents(original)
        self.assertEqual(original, snapshot)
        self.assertEqual(ordinary.pop("matchexpr"), COMMON_MATCH)
        self.assertEqual(ordinary, original)
        self.assertEqual(pilot.pop("matchexpr"), PILOT_MATCH)
        self.assertEqual(pilot["uuid"], PILOT_UUID)
        pilot["uuid"] = original["uuid"]
        for sub in pilot["subdevices"]:
            for item in sub["items"]:
                if item.get("name") in CLUSTERS:
                    self.assertEqual(item.pop("refresh.interval"), INTERVAL_SECONDS)
                    self.assertEqual(item.pop("read"), {"fn": "zcl:attr", "ep": 1,
                                     "cl": CLUSTERS[item["name"]], "at": "0x0000"})
        # Includes unchanged presence parser/reader, timestamps and all unrelated settings.
        self.assertEqual(pilot, original)

    def test_repeat_build_is_stable(self):
        ordinary, pilot = build_documents(common_fixture())
        self.assertEqual(build_documents(ordinary), (ordinary, pilot))

    def test_wrong_model_and_old_presence_parser_rejected(self):
        value = common_fixture(); value["modelid"] = "other"
        with self.assertRaises(ValueError): build_documents(value)
        with self.assertRaises(ValueError): build_documents(fixture())

    def test_unknown_match_and_custom_refresh_rejected(self):
        for key, value in (("read", {"fn": "none"}), ("refresh.interval", 123)):
            original = common_fixture(); original["subdevices"][-1]["items"][0][key] = value
            with self.assertRaises(ValueError): build_documents(original)
        original = common_fixture(); original["matchexpr"] = "custom"
        with self.assertRaises(ValueError): build_documents(original)

    def test_missing_duplicate_and_changed_endpoint_rejected(self):
        for kind in ("missing", "duplicate", "endpoint", "cluster", "awake"):
            value = common_fixture()
            if kind == "missing": value["subdevices"].pop()
            elif kind == "duplicate": value["subdevices"].append(copy.deepcopy(value["subdevices"][-1]))
            elif kind == "endpoint": value["subdevices"][-1]["fingerprint"]["endpoint"] = "0x02"
            elif kind == "cluster": value["subdevices"][-1]["fingerprint"]["in"] = []
            else: value["subdevices"][-1]["items"][0]["awake"] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError): build_documents(value)

    @unittest.skipUnless(shutil.which("node"), "Node.js needed for actual match-expression evaluation")
    def test_matches_are_exclusive_for_pilot_and_other_devices(self):
        code = "const R={item:()=>({val:process.argv[1]})};process.stdout.write(JSON.stringify([eval(process.argv[2]),eval(process.argv[3])]));"
        for mac, expected in ((PILOT_MAC, [False, True]), ("54:ef:44:10:01:59:00:00", [True, False])):
            result = subprocess.run([shutil.which("node"), "-e", code, mac, COMMON_MATCH, PILOT_MATCH],
                                    text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout), expected)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.common = Path(self.directory.name)/"common.json"
        self.pilot = self.common.with_name("pilot.json")
        self.common.write_text(json.dumps(common_fixture()), encoding="utf-8")

    def test_preview_has_no_writes(self):
        before = self.common.read_bytes()
        prepare(self.common, self.pilot)
        self.assertEqual(self.common.read_bytes(), before)
        self.assertEqual(list(self.common.parent.iterdir()), [self.common])

    def test_backups_idempotence_and_original_customizations(self):
        before = self.common.read_bytes()
        changed, backups = install(self.common, self.pilot)
        self.assertTrue(changed); self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(json.loads(self.pilot.read_text())["unchanged"], {"value": 7})
        self.assertEqual(install(self.common, self.pilot), (False, []))

    def test_unknown_existing_pilot_leaves_everything_untouched(self):
        self.pilot.write_text('{"custom":true}', encoding="utf-8")
        before = {p: p.read_bytes() for p in self.common.parent.iterdir()}
        with self.assertRaises(ValueError): install(self.common, self.pilot)
        self.assertEqual({p: p.read_bytes() for p in self.common.parent.iterdir()}, before)

    def test_partial_failure_removes_new_pilot_preserves_common(self):
        before = self.common.read_bytes()
        def fail_common(path, content):
            if path == self.common: raise OSError("simulated replace failure")
            atomic_write(path, content)
        with patch("utils.fp300_refresh_pilot.atomic_write", side_effect=fail_common):
            with self.assertRaises(OSError): install(self.common, self.pilot)
        self.assertFalse(self.pilot.exists())
        self.assertEqual(self.common.read_bytes(), before)

    def test_helper_content_embedded_without_changing_original(self):
        helper = self.common.with_name("battery.js"); helper.write_text("Item.val = Attr.val;", encoding="utf-8")
        value = common_fixture(); value["subdevices"][0]["items"][0]["parse"] = {"script": "battery.js"}
        self.common.write_text(json.dumps(value), encoding="utf-8")
        before = self.common.read_bytes()
        _, backups = install(self.common, self.pilot)
        self.assertEqual(backups[0].read_bytes(), before)
        for path in (self.common, self.pilot):
            self.assertEqual(json.loads(path.read_text())["subdevices"][0]["items"][0]["parse"],
                             {"eval": "Item.val = Attr.val;"})

    def test_missing_helper_and_bad_paths_rejected_before_write(self):
        with self.assertRaises(ValueError): prepare(self.common, self.common)
        with self.assertRaises(ValueError): prepare(self.common, self.common.parent/"other"/"pilot.json")
        with self.assertRaises(ValueError): prepare(self.common, self.common.with_suffix(".bak"))
        value = common_fixture(); value["subdevices"][0]["items"][0]["parse"] = {"script": "missing.js"}
        self.common.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(FileNotFoundError): install(self.common, self.pilot)
        self.assertFalse(self.pilot.exists())

    def test_no_temporary_files_after_failed_atomic_write(self):
        with patch("utils.fp300_refresh_pilot.os.replace", side_effect=OSError("failure")):
            with self.assertRaises(OSError): atomic_write(self.pilot, b"{}")
        self.assertEqual(list(self.common.parent.iterdir()), [self.common])


if __name__ == "__main__":
    unittest.main()
