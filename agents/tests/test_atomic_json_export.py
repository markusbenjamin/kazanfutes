"""Exercise the production exporter without importing hardware integrations."""
import ast
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


class ExportError(Exception):
    pass


class AtomicJsonExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='kazanfutes-json-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.target = self.root / 'exports' / 'room_3_set_temps.json'
        module = ast.parse(Path('utils/project.py').read_text(encoding='utf-8'))
        function = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'export_json_list_to_json_file')
        namespace = {'os': os, 'tempfile': tempfile, 'json': json,
                     'get_project_root': lambda: str(self.root), 'ModuleException': ExportError}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'utils/project.py', 'exec'), namespace)
        self.export = namespace[function.name]

    def publish(self, rows):
        self.export(rows, 'exports/room_3_set_temps.json')

    def test_format_and_new_directory_are_preserved(self):
        rows = [{'timestamp': '2026-11-04-10-39-21', 'set_temp': 21.0, 'label': 'fűtés'}]
        self.publish(rows)
        self.assertEqual(self.target.read_text(), json.dumps(rows, indent=2))
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])
        self.publish([])
        self.assertEqual(json.loads(self.target.read_text()), [])

    def test_reader_sees_old_complete_file_until_replace(self):
        old, new = [{'set_temp': 14}], [{'set_temp': 21}] * 1000
        self.publish(old)
        writing, release = threading.Event(), threading.Event()
        original_dump = json.dump
        errors = []

        def paused_dump(rows, file, **options):
            file.write('[')
            file.flush()
            writing.set()
            if not release.wait(5):
                raise RuntimeError('test writer timed out')
            file.seek(0)
            file.truncate()
            original_dump(rows, file, **options)

        def write():
            try:
                self.publish(new)
            except Exception as error:
                errors.append(error)

        with patch.object(json, 'dump', side_effect=paused_dump):
            worker = threading.Thread(target=write)
            worker.start()
            try:
                self.assertTrue(writing.wait(5))
                self.assertEqual(json.loads(self.target.read_text()), old)
                staging_files = list(self.target.parent.glob('.*.lock'))
                self.assertEqual(len(staging_files), 1)
                self.assertIn('*.lock', Path('.gitignore').read_text().splitlines())
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(json.loads(self.target.read_text()), new)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_failed_serialization_preserves_last_good_file(self):
        self.publish([{'set_temp': 21}])
        old_bytes = self.target.read_bytes()
        with self.assertRaises(ExportError):
            self.publish([{'unsupported': object()}])
        self.assertEqual(self.target.read_bytes(), old_bytes)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_failed_replace_preserves_last_good_file_and_cleans_temp(self):
        self.publish([{'set_temp': 21}])
        with patch.object(os, 'replace', side_effect=OSError('simulated failed rename')):
            with self.assertRaises(ExportError):
                self.publish([{'set_temp': 22}])
        self.assertEqual(json.loads(self.target.read_text()), [{'set_temp': 21}])
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_failed_first_export_does_not_publish_partial_file(self):
        with self.assertRaises(ExportError):
            self.publish([object()])
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.target.parent.iterdir()), [])

    @unittest.skipIf(os.name == 'nt', 'POSIX permission bits')
    def test_existing_file_permissions_are_preserved(self):
        self.publish([])
        self.target.chmod(0o640)
        self.publish([1])
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o640)


if __name__ == '__main__':
    unittest.main()
