"""Offline outage tests: no project imports, network, device I/O or log writes."""

import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).with_name('heating_control.py')
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))


class ModuleError(Exception):
    pass


def load_reporting():
    nodes = [node for node in TREE.body if
             (isinstance(node, ast.ClassDef) and node.name == 'HeatingStatusPublisher') or
             (isinstance(node, ast.FunctionDef) and node.name in
              {'export_system_state', 'acquire_heating_switch'})]
    env = {'settings': {'firebase_url': 'https://example.invalid/', 'dev': False, 'on_raspi': True},
           'requests': Mock(), 'report': Mock(), 'log': Mock(),
           'ServiceException': Mock(), 'ModuleException': ModuleError,
           'timestamp': lambda: '2026-11-05-21-00-00',
           'export_dict_as_json': Mock(), 'system_state': {'boiler_state': 1}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), env)
    env['system_node'] = env['HeatingStatusPublisher']()
    return env


class HeatingReportingTests(unittest.TestCase):
    def test_status_collection_never_connects_and_coalesces_error_updates(self):
        env = load_reporting()
        node = env['system_node']
        node.write({'error': False, 'where': None}, 'control/error')
        node.write({'error': True, 'where': 'temps'}, 'control/error')
        node.write({'boiler': 1, 'rooms': {'1': {'vote': 1}}}, 'control')
        node.write({'measured_temps': {'1': 20}, 'last_updated': 'now'}, 'state')
        self.assertEqual(node.pending, {
            'control/error/error': True, 'control/error/where': 'temps',
            'control/boiler': 1, 'control/rooms': {'1': {'vote': 1}},
            'state/measured_temps': {'1': 20}, 'state/last_updated': 'now',
        })
        self.assertEqual(env['requests'].mock_calls, [])

    def test_one_bounded_patch_preserves_other_publishers_fields(self):
        env = load_reporting()
        node = env['system_node']
        node.write({'measured_temps': {}, 'last_updated': 'now'}, 'state')
        self.assertTrue(node.publish())
        env['requests'].patch.assert_called_once_with(
            'https://example.invalid/system.json',
            json={'state/measured_temps': {}, 'state/last_updated': 'now'}, timeout=3)
        env['requests'].get.assert_not_called()
        env['log'].assert_called_once_with({'success_firebase_publish': True, 'firebase_error': None})
        env['ServiceException'].assert_not_called()

    def test_empty_report_needs_no_network(self):
        env = load_reporting()
        self.assertTrue(env['system_node'].publish())
        self.assertEqual(env['requests'].mock_calls, [])

    def test_server_error_is_recorded_without_escaping_or_retrying(self):
        env = load_reporting()
        response = Mock(status_code=500, text='{"error":"Internal error"}')
        response.raise_for_status.side_effect = RuntimeError('HTTP 500')
        env['requests'].patch.return_value = response
        env['system_node'].write({'error': False}, 'control/error')
        self.assertFalse(env['system_node'].publish())
        env['requests'].patch.assert_called_once()
        env['ServiceException'].assert_called_once()
        env['log'].assert_called_once_with({
            'success_firebase_publish': False,
            'firebase_error': 'HTTP 500: {"error":"Internal error"}',
        })

    def test_connection_failure_is_nonfatal(self):
        env = load_reporting()
        env['requests'].patch.side_effect = TimeoutError('network unavailable')
        env['system_node'].write({'boiler': 1}, 'control')
        self.assertFalse(env['system_node'].publish())
        env['requests'].patch.assert_called_once()
        self.assertEqual(env['log'].call_args.args[0]['firebase_error'], 'network unavailable')

    def test_initialization_does_not_require_firebase_read_or_write(self):
        env = load_reporting()
        env.update(get_rooms_info=Mock(return_value={}), get_cycles_info=Mock(return_value={}),
                   load_json_to_dict=Mock(return_value={}),
                   JSONNodeAtURL=Mock(side_effect=RuntimeError('Firebase unavailable')),
                   os=SimpleNamespace(path=SimpleNamespace(join=lambda *parts: '/'.join(parts))),
                   get_project_root=lambda: '/project')
        init = next(node for node in TREE.body if isinstance(node, ast.Try))
        exec(compile(ast.Module(body=[init], type_ignores=[]), str(SOURCE), 'exec'), env)
        self.assertTrue(env['success'])
        env['JSONNodeAtURL'].assert_not_called()
        self.assertEqual(env['requests'].mock_calls, [])
        env['ServiceException'].assert_not_called()

    def test_local_error_handler_does_not_attempt_a_second_cloud_request(self):
        env = load_reporting()
        env['load_json_to_dict'] = Mock(side_effect=OSError('missing heating switch'))
        self.assertIsNone(env['acquire_heating_switch']())
        self.assertEqual(env['system_node'].pending['control/error/where'], 'switch')
        self.assertTrue(env['system_node'].pending['control/error/error'])
        env['ServiceException'].assert_called_once()
        self.assertEqual(env['requests'].mock_calls, [])

    def test_local_state_is_fresh_even_if_cloud_publication_fails(self):
        env = load_reporting()
        saved = {}
        env['export_dict_as_json'] = lambda value, path: saved.update({path: copy.deepcopy(value)})
        env['requests'].patch.side_effect = TimeoutError('Firebase unavailable')
        env['export_system_state']()
        self.assertEqual(saved['system/state.json']['last_updated'], '2026-11-05-21-00-00')
        env['log'].assert_any_call({'success_export_system_state': True})
        self.assertEqual(env['requests'].mock_calls, [])
        self.assertFalse(env['system_node'].publish())
        self.assertEqual(saved['system/state.json']['boiler_state'], 1)

    def test_real_local_save_failure_is_still_reported(self):
        env = load_reporting()
        env['export_dict_as_json'].side_effect = OSError('disk full')
        env['export_system_state']()
        env['ServiceException'].assert_called_once()
        self.assertEqual(env['system_node'].pending['control/error/where'], 'system_state_export')
        env['log'].assert_any_call({'success_export_system_state': False})

    def test_main_actuates_and_saves_before_attempting_cloud_upload(self):
        self.run_main(heating_on=True)

    def test_heating_off_still_shuts_down_before_cloud_upload(self):
        self.run_main(heating_on=False)

    def run_main(self, *, heating_on):
        env = load_reporting()
        events = []
        env.update(__name__='__main__',
                   acquire_heating_switch=lambda: {'system': int(heating_on)},
                   get_system_state=lambda: {'boiler_state': int(heating_on)},
                   compare_and_command=lambda *args: events.append('compare'),
                   execute_commands=lambda: events.append('actuate'),
                   shutdown_heating=lambda: events.append('shutdown'))
        env['export_dict_as_json'] = lambda data, path: events.append('save:' + path)
        def fail_upload(*args, **kwargs):
            events.append('upload')
            raise TimeoutError('Firebase unavailable')
        def exit_main():
            raise SystemExit()
        env['requests'].patch.side_effect = fail_upload
        env['exit'] = exit_main
        main = next(node for node in TREE.body if isinstance(node, ast.If)
                    and ast.unparse(node.test) == "__name__ == '__main__'")
        code = compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), 'exec')
        if heating_on:
            exec(code, env)
            self.assertEqual(events, ['compare', 'actuate', 'save:system/state.json', 'upload'])
        else:
            with self.assertRaises(SystemExit):
                exec(code, env)
            self.assertEqual(events, ['shutdown', 'save:system/PID_state.json',
                                      'save:system/state.json', 'upload'])
        env['requests'].patch.assert_called_once()
        env['log'].assert_any_call({'success_export_system_state': True})
        self.assertFalse(env['log'].call_args.args[0]['success_firebase_publish'])


if __name__ == '__main__':
    unittest.main()
