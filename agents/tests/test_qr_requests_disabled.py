"""Exercise QR retirement without importing hardware or reading project data."""
import ast
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 6, 12)


class QRRetirementTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = ast.parse(Path('services/schedule_and_config_updater.py').read_text(encoding='utf-8'))
        self.form = ['06/11/2026 10:00:00', 'DiósEdit', '06/11/2026', '10', '8', '21']
        self.reads = []

        def read(path):
            self.reads.append(path)
            self.assertNotIn('qr', path, 'retired request sources must never be read')
            return [['Timestamp', 'Room'], self.form]

        self.namespace = {
            'datetime': Clock, 'timedelta': timedelta, 'math': __import__('math'),
            'export_path_prefix': '', 'local_scheduling_files_relative_path': 'config/scheduling/local_scheduling_files',
            'load_csv_to_2D_array': read, 'report': Mock(), 'log': Mock(), 'ModuleException': RuntimeError,
            'ServiceException': Mock(), 'get_rooms_info': lambda: {'12': {'name': 'DiósEdit'}},
            'warming_params': {'12': {'t_min': 16, 't_max': 21}}, 'schedule_node': Mock(),
            'settings': {'timestamp_format': '%Y-%m-%d-%H-%M-%S'},
        }

    def execute(self, nodes):
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<production QR retirement>', 'exec'), self.namespace)

    def function(self, name):
        return next(node for node in self.scheduler.body if isinstance(node, ast.FunctionDef) and node.name == name)

    def test_no_qr_download_or_expiry_configuration(self):
        names = {'update_needed', 'last_update', 'update_ids', 'update_sheet_names', 'export_paths'}
        self.namespace['heating_config'] = {'override_rooms_id': 'form-sheet', 'override_cycles_id': 'cycle-sheet'}
        assignments = [node for node in self.scheduler.body if isinstance(node, ast.Assign)
                       and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names]
        self.execute(assignments)
        for name in names:
            self.assertNotIn('override_rooms_qr', self.namespace[name])
        self.assertEqual(self.namespace['update_ids']['override_rooms'], 'form-sheet')

    def setup_callback(self):
        self.namespace['update_needed'] = {'weekly_cycle': {}, 'override_rooms': False, 'override_cycles': False}
        self.namespace['heating_config_update_info'] = {'update_needed': False}
        self.namespace['room_name_to_num'] = Mock(return_value='12')

        def update_nested(mapping, path, value):
            keys = path.split('/')
            for key in keys[:-1]:
                mapping = mapping.setdefault(key, {})
            mapping[keys[-1]] = value

        self.namespace['update_nested_dict'] = update_nested
        self.execute([self.function('update_detected')])
        return self.namespace['update_detected']

    def test_qr_webhook_notifications_have_no_effect(self):
        callback = self.setup_callback()
        for path in ['override_rooms_qr', 'override_rooms_qr/room_name', '/override_rooms_qr']:
            callback('update', [{'path': path, 'data': {'room_name': 'DiósEdit'}}])
        callback('update', [{'path': '', 'data': {'override_rooms_qr': {'room_name': 'DiósEdit'}}}])
        self.assertEqual(self.namespace['update_needed'],
                         {'weekly_cycle': {}, 'override_rooms': False, 'override_cycles': False})
        self.assertFalse(self.namespace['heating_config_update_info']['update_needed'])
        self.namespace['room_name_to_num'].assert_not_called()
        self.namespace['report'].assert_not_called()

    def test_mixed_notifications_preserve_normal_requests_and_config(self):
        callback = self.setup_callback()
        callback('update', [{'path': path, 'data': {}} for path in
                           ['override_rooms_qr', 'override_rooms', 'weekly_cycle/DiósEdit',
                            'override_cycles', 'heating_control_config']])
        self.assertEqual(self.namespace['update_needed'],
                         {'weekly_cycle': {'12': True}, 'override_rooms': True, 'override_cycles': True})
        self.assertTrue(self.namespace['heating_config_update_info']['update_needed'])

    def test_schedule_only_loads_normal_form_requests(self):
        function = self.function('generate_schedule')
        assignment = next(node for node in ast.walk(function) if isinstance(node, ast.Assign)
                          and isinstance(node.targets[0], ast.Name)
                          and node.targets[0].id == 'override_commands_for_rooms')
        command = dict(zip(['google_timestamp', 'room_name', 'date', 'hour_of_day', 'duration', 'on'], self.form))
        self.namespace.update(select_subtable_from_table=lambda rows, **kw: rows,
                              response_table_to_dict_list=lambda rows, columns: [command])
        self.execute([assignment])
        self.assertEqual(self.namespace['override_commands_for_rooms'], [command])
        self.assertEqual(len(self.reads), 1)
        self.assertTrue(self.reads[0].endswith('/override_rooms.csv'))

    def test_firebase_request_list_only_contains_normal_forms(self):
        self.execute([self.function('update_valid_requests_on_firebase')])
        self.namespace['update_valid_requests_on_firebase']()
        self.namespace['ServiceException'].assert_not_called()
        self.namespace['schedule_node'].write.assert_called_once_with({'12': [{
            'timestamp': '2026-11-06-10-00-00', 'time': '2026-11-06-10-00-00',
            'duration': '8', 'set_temp': 21,
        }]}, 'request_lists')
        self.assertEqual(len(self.reads), 1)

    def test_formatted_request_markers_ignore_qr_archive(self):
        formatter = ast.parse(Path('services/data_formatter.py').read_text(encoding='utf-8'))
        block = next(node for node in ast.walk(formatter) if isinstance(node, ast.If)
                     and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Constant)
                     and node.test.left.value == 'room_overrides')
        exported = Mock()
        self.namespace.update(digestion_daystamp='2026-11-06', digestion_day=Clock.now(),
                              export_json_list_to_json_file=exported)
        self.execute(block.body)
        self.namespace['ServiceException'].assert_not_called()
        exported.assert_called_once_with({'12': [{
            'timestamp': '2026-11-06-10-00-00', 'time': '2026-11-06-10-00-00',
            'duration': '8', 'set_temp': '21',
        }]}, 'data/formatted/2026-11-06/override_requests.json')
        self.assertEqual(len(self.reads), 1)


if __name__ == '__main__':
    unittest.main()
