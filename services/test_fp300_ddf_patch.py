"""Regression tests for FP300 combined presence and safe DDF deployment."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from utils.fp300_ddf_patch import MODEL, OLD_EVAL, PRESENCE_EVAL, PRESENCE_READ, inline_scripts, install, patch_document


def fixture():
    return {"modelid": MODEL, "unchanged": {"value": 7}, "subdevices": [{"items": [
        {"name": "config/delay", "default": 30},
        {"name": "state/presenceevent", "public": False, "parse": {"at": "0x014D"}},
        {"name": "state/presence", "refresh.interval": 3600, "parse": {
            "at": ["0x0142", "0x014D"], "cl": "0xFCC0", "ep": 1,
            "mf": "0x115F", "fn": "zcl:attr", "eval": OLD_EVAL,
        }, "read": {"fn": "none"}},
    ]}]}


class PatchTests(unittest.TestCase):
    def test_only_presence_parser_and_reader_change(self):
        original = fixture(); before = copy.deepcopy(original)
        actual = patch_document(original)
        expected = copy.deepcopy(original)
        item = expected["subdevices"][0]["items"][2]
        item["parse"]["eval"] = PRESENCE_EVAL; item["read"] = PRESENCE_READ
        self.assertEqual(actual, expected)
        self.assertEqual(original, before)

    def test_idempotent(self):
        once = patch_document(fixture())
        self.assertEqual(patch_document(once), once)

    def test_wrong_model_rejected(self):
        value = fixture(); value["modelid"] = "MS01"
        with self.assertRaises(ValueError): patch_document(value)

    def test_unknown_parser_rejected(self):
        value = fixture(); value["subdevices"][0]["items"][2]["parse"]["eval"] = "custom"
        with self.assertRaises(ValueError): patch_document(value)

    def test_custom_reader_rejected(self):
        value = fixture(); value["subdevices"][0]["items"][2]["read"] = {"fn": "custom"}
        with self.assertRaises(ValueError): patch_document(value)

    def test_duplicate_presence_item_rejected(self):
        value = fixture(); value["subdevices"][0]["items"].append(copy.deepcopy(value["subdevices"][0]["items"][2]))
        with self.assertRaises(ValueError): patch_document(value)

    def test_changed_cluster_rejected(self):
        value = fixture(); value["subdevices"][0]["items"][2]["parse"]["cl"] = "0x0406"
        with self.assertRaises(ValueError): patch_document(value)

    def test_install_preserves_system_source_and_backs_up_exact_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/"system.json"; destination = Path(folder)/"user"/"override.json"
            source.write_text(json.dumps(fixture()), encoding="utf-8"); before = source.read_bytes()
            changed, backup = install(source, destination)
            self.assertTrue(changed); self.assertEqual(backup.read_bytes(), before)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(json.loads(destination.read_text()), patch_document(fixture()))
            self.assertEqual(install(source, destination), (False, None))

    def test_existing_customizations_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/"system.json"; destination = Path(folder)/"override.json"
            source.write_text(json.dumps(fixture()), encoding="utf-8")
            custom = fixture(); custom["unchanged"]["value"] = 99
            destination.write_text(json.dumps(custom), encoding="utf-8"); before = destination.read_bytes()
            _, backup = install(source, destination)
            self.assertEqual(backup.read_bytes(), before)
            self.assertEqual(json.loads(destination.read_text())["unchanged"]["value"], 99)

    def test_no_files_written_for_unknown_override(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/"system.json"; destination = Path(folder)/"override.json"
            source.write_text(json.dumps(fixture()), encoding="utf-8")
            custom = fixture(); custom["modelid"] = "other"
            destination.write_text(json.dumps(custom), encoding="utf-8"); before = destination.read_bytes()
            with self.assertRaises(ValueError): install(source, destination)
            self.assertEqual(destination.read_bytes(), before)
            self.assertEqual(len(list(Path(folder).iterdir())), 2)

    def test_source_cannot_be_destination(self):
        with self.assertRaises(ValueError): install(Path("same.json"), Path("same.json"))

    def test_helpers_embedded_unchanged_without_mutating_input(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)/"xiaomi"; directory.mkdir()
            text = "Item.val = Attr.val / 100;\n"
            (directory/"battery.js").write_text(text, encoding="utf-8")
            value = fixture(); value["subdevices"][0]["items"][0]["parse"] = {"script": "battery.js", "at": "0x00F7"}
            original = copy.deepcopy(value)
            result = inline_scripts(value, directory)
            self.assertEqual(result["subdevices"][0]["items"][0]["parse"], {"eval": text, "at": "0x00F7"})
            self.assertEqual(value, original)

    def test_missing_helper_does_not_create_override_or_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/"system.json"; destination = Path(folder)/"user"/"override.json"
            value = fixture(); value["subdevices"][0]["items"][0]["parse"] = {"script": "missing.js"}
            source.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(FileNotFoundError): install(source, destination)
            self.assertFalse(destination.parent.exists())

    def test_relative_generic_helper_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)/"xiaomi"; directory.mkdir()
            generic = Path(folder)/"generic"; generic.mkdir()
            (generic/"lux.js").write_text("Item.val = 12;", encoding="utf-8")
            value = fixture(); value["subdevices"][0]["items"][0]["parse"] = {"script": "../generic/lux.js"}
            result = inline_scripts(value, directory)
            self.assertEqual(result["subdevices"][0]["items"][0]["parse"], {"eval": "Item.val = 12;"})


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to execute the actual deCONZ JavaScript parser")
class ParserTests(unittest.TestCase):
    def evaluate(self, mode, events, initial=False, expression=PRESENCE_EVAL):
        payload = {"mode": mode, "events": events, "initial": initial, "expression": expression}
        code = """
const p = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const run = new Function('Item', 'Attr', 'R', p.expression);
const Item = {val:p.initial}; let pir = p.initial ? 1 : 0; const states = [];
const R = {item:name=>({val:name==='config/devicemode' ? p.mode : String(pir)})};
for (const [attribute,value] of p.events) {
 if (attribute==='0x014D') pir=value;
 run(Item, {id:attribute,val:value}, R); states.push(Boolean(Item.val));
}
process.stdout.write(JSON.stringify(states));
"""
        result = subprocess.run([shutil.which("node"), "-e", code], input=json.dumps(payload),
                                text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_reproduces_original_clear_order_bug(self):
        events = [["0x0142", 0], ["0x014D", 0]]
        self.assertEqual(self.evaluate("combined", events, True, OLD_EVAL), [True, True])
        self.assertEqual(self.evaluate("combined", events, True), [False, False])

    def test_combined_both_clear_orders_finish_vacant(self):
        for events in ([["0x0142", 0], ["0x014D", 0]], [["0x014D", 0], ["0x0142", 0]]):
            self.assertFalse(self.evaluate("combined", events, True)[-1])

    def test_pir_cannot_override_authoritative_combined_presence(self):
        self.assertEqual(self.evaluate("combined", [["0x0142", 1], ["0x014D", 0],
                                                    ["0x0142", 0], ["0x014D", 1]]),
                         [True, True, False, False])

    def test_mmwave_ignores_pir_events(self):
        self.assertEqual(self.evaluate("mmwave", [["0x014D", 1], ["0x0142", 1],
                                                  ["0x014D", 0], ["0x0142", 0]]),
                         [False, True, True, False])

    def test_pir_only_mode_still_tracks_pir(self):
        self.assertEqual(self.evaluate("pir", [["0x014D", 1], ["0x0142", 0], ["0x014D", 0]]),
                         [True, True, False])

    def test_invalid_presence_value_does_not_invent_absence(self):
        self.assertEqual(self.evaluate("combined", [["0x0142", 255]], True), [True])

    def test_refresh_reads_correct_attribute_for_each_mode(self):
        code = "const R={item:()=>({val:process.argv[1]})};process.stdout.write(eval(process.argv[2]));"
        for mode, expected in (("combined", "4201"), ("mmwave", "4201"), ("pir", "4D01")):
            result = subprocess.run([shutil.which("node"), "-e", code, mode, PRESENCE_READ["eval"]],
                                    text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, expected)


if __name__ == "__main__":
    unittest.main()
