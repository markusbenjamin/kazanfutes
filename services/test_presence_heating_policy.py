"""Heating presence opt-out keeps schedules and sensor observations independent."""
import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'services'))

from test_heating_targets import DAY, scheduler_environment, request
from utils.room_registry import validate_definitions, runtime_rooms
from utils.room_presence import room_presence_observations


class PresenceHeatingPolicyTests(unittest.TestCase):
    def generate(self, *, presence, baseline=0, requests=(), cycle_off=False, strong=1):
        env = scheduler_environment(presence=presence, baseline=baseline,
                                    requests=requests, cycle_off=cycle_off, strong=strong)
        env['rooms_info']['1']['presence_control'] = False
        result = env['generate_condensed_schedule'](for_how_many_days=2)
        env['ServiceException'].assert_not_called()
        return result

    def test_presence_cannot_change_unoccupied_or_occupied_weekly_targets(self):
        for baseline, expected in ((0, 14), (1, 21)):
            for presence in (True, False, None):
                with self.subTest(baseline=baseline, presence=presence):
                    result = self.generate(presence=presence, baseline=baseline)
                    self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], expected)

    def test_manual_temperature_has_neither_absence_setback_nor_presence_boost(self):
        for presence in (True, False, None):
            result = self.generate(presence=presence, requests=[request(23)])
            self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], 23)

    def test_presence_does_not_release_soft_or_strong_holiday_holds(self):
        for strong, expected in ((0, 14), (1, 10)):
            result = self.generate(presence=True, requests=[request(23)],
                                   cycle_off=True, strong=strong)
            self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], expected)

    def test_learned_occupancy_is_not_consulted_for_disabled_room(self):
        source = ROOT / 'services/schedule_and_config_updater.py'
        nodes = [node for node in ast.parse(source.read_text(encoding='utf-8')).body
                 if isinstance(node, ast.FunctionDef)
                 and node.name == 'get_presence_patterns_with_weekly_cycle_weighted_average']
        loader = Mock(side_effect=AssertionError('Presence history must be ignored'))
        env = dict(rooms_info={'8': {'presence_control': False}},
                   weekly_baseline=SimpleNamespace(config={}),
                   weekly_presence=lambda *args: .35,
                   load_json_to_dict=loader)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), env)
        self.assertEqual(env[nodes[0].name]('8', 3, 12), .35)
        loader.assert_not_called()

    def test_disabling_heating_presence_keeps_sensor_logging_and_runtime_policy(self):
        room = dict(included=True, controlled=True, cycle='3',
                    valve_mode='unrestricted', temperature_sensors=['Aqara8'],
                    presence_sensors=['Aqara8'], presence_control=False)
        definitions = validate_definitions({'schema_version': 2, 'rooms': {'8': room}})
        registry = {'schema_version': 1, 'rooms': {'8': {'display_name': 'Kisterem'}}}
        rooms = runtime_rooms(definitions, registry)
        observation = {'state': True, 'source_name': 'Aqara8', 'usable': True}
        self.assertEqual(room_presence_observations(rooms, {'Aqara8': observation})['8'],
                         observation)
        self.assertFalse(rooms['8']['presence_control'])

    def test_policy_requires_a_real_boolean(self):
        room = dict(included=True, controlled=True, cycle='3',
                    valve_mode='unrestricted', presence_control='false')
        with self.assertRaisesRegex(ValueError, 'presence_control'):
            validate_definitions({'schema_version': 2, 'rooms': {'8': room}})


if __name__ == '__main__':
    unittest.main()
