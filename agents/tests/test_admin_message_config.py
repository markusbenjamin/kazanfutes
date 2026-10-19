"""Check the Sheet-to-dashboard handoff without importing the running service."""
import ast
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock


class AdminMessageConfigTests(unittest.TestCase):
    def setUp(self):
        source = Path('services/schedule_and_config_updater.py').read_text(encoding='utf-8')
        function = next(node for node in ast.parse(source).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'update_local_heating_control_config')
        self.config = {'heating_control_config_id': 'configured-sheet',
                       'no_presence_offset': '1.5', 'heating_window': '60'}
        self.state = {'update_needed': True, 'last_updated': None}
        self.system = Mock()
        self.update = Mock()
        self.download = Mock()
        self.namespace = {
            'heating_config': self.config, 'heating_config_update_info': self.state,
            'schedule_update_info': {'update_needed': False},
            'system_node': self.system, 'update_node': self.update,
            'download_google_sheet_to_2D_array': self.download,
            'export_dict_as_json': Mock(), 'export_path_prefix': '',
            'generate_and_export_heating_switch': Mock(),
            'datetime': datetime, 'timestamp': Mock(), 'report': Mock(),
            'log': Mock(), 'ModuleException': RuntimeError, 'ServiceException': Mock(),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'config-update', 'exec'), self.namespace)

    def refresh(self, config):
        self.download.return_value = [['key', 'value', 'description'],
                                      *[[key, value, ''] for key, value in config.items()]]
        return self.namespace['update_local_heating_control_config']()

    def test_message_published_from_existing_config_copy(self):
        message = '**Frissítés**\n\nA fűtési beállítások változtak.'
        config = {**self.config, 'admin_message': message}
        self.assertEqual(self.refresh(config), config)
        self.system.write.assert_called_once_with({'admin_message': message}, 'dashboard')
        self.download.assert_called_once_with('configured-sheet')
        self.assertFalse(self.state['update_needed'])

    def test_missing_or_empty_field_clears_previous_message(self):
        for extra in [{}, {'admin_message': ''}, {'admin_message': None}]:
            with self.subTest(extra=extra):
                self.state['update_needed'] = True
                self.system.reset_mock()
                self.refresh({**self.config, **extra})
                self.system.write.assert_called_once_with({'admin_message': ''}, 'dashboard')

    def test_failed_publication_is_retried_before_acknowledgement(self):
        self.system.write.side_effect = RuntimeError('Firebase unavailable')
        self.assertIsNone(self.refresh({**self.config, 'admin_message': 'Új üzenet'}))
        self.assertTrue(self.state['update_needed'])
        self.update.write.assert_not_called()
        self.namespace['ServiceException'].assert_called_once()

    def test_sheet_omits_empty_value_cell_without_losing_other_config(self):
        self.download.return_value = [
            ['key', 'value', 'description'],
            *[[key, value] for key, value in self.config.items()],
            [], ['admin_message'], ['', '', 'Notes'],
        ]
        result = self.namespace['update_local_heating_control_config']()
        self.assertEqual(result, {**self.config, 'admin_message': ''})
        self.system.write.assert_called_once_with({'admin_message': ''}, 'dashboard')


if __name__ == '__main__':
    unittest.main()
