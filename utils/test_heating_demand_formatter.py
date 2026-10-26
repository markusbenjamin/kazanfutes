"""Demand inference and formatter wiring, without device or filesystem writes."""
import ast
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock

from utils.heating_demand_formatter import format_heating_demand

DAY = '2026-10-26'
START = datetime(2026, 10, 26)
MAPPING = {'1': 1, '2': 2}


def row(minute, supply=70, returned=40, flow=.5, second=None):
    return {'timestamp': (START + timedelta(minutes=minute)).strftime('%Y-%m-%d-%H-%M-%S'),
            'states': {'1': {'volume_flow_m3h': flow, 'flow_temperature_c': supply,
                             'return_temperature_c': returned},
                       '2': second if second is not None else {'volume_flow_m3h': 0}}}


def calculate(rows, **options):
    return format_heating_demand(rows, DAY, MAPPING, **options)


class HeatingDemandTests(unittest.TestCase):
    def test_known_flow_and_return_give_physical_kw_at_target(self):
        result = calculate([row(0, supply=59, returned=44, flow=.429)], target_temperature_c=70)[0]
        self.assertAlmostEqual(result['demand_kw'], 12.972102)
        self.assertEqual(result['active_cycles'], ['1'])
        self.assertEqual(result['cycle_demand_kw']['2'], 0)

    def test_target_needs_sustained_past_plateau_and_never_backfills(self):
        rows = [row(i) for i in range(8)]
        result = calculate(rows)
        self.assertTrue(all(r['demand_kw'] is None for r in result[:5]))
        self.assertEqual(result[5]['target_temperature_c'], 70)
        self.assertEqual(result[5]['demand_kw'], 17.445)
        self.assertEqual(result[:7], calculate(rows[:7]))
        self.assertEqual(result[0]['status'], 'waiting_for_plateau')

    def test_idle_hot_or_missing_temperatures_never_influence_target(self):
        baseline = calculate([row(i) for i in range(8)])
        for temperature in [99, 15, None, math.nan]:
            rows = [row(i, second={'volume_flow_m3h': 0, 'flow_temperature_c': temperature,
                                   'return_temperature_c': temperature}) for i in range(8)]
            self.assertEqual(calculate(rows), baseline)

    def test_all_idle_means_zero_without_a_target_or_temperatures(self):
        result = calculate([row(0, supply=None, returned=None, flow=0)])[0]
        self.assertEqual(result['demand_kw'], 0)
        self.assertEqual(result['status'], 'inactive')
        self.assertIsNone(result['target_temperature_c'])

    def test_missing_or_invalid_flow_is_unknown_not_zero(self):
        for value in [None, True, '0', -1, math.nan, math.inf]:
            result = calculate([row(0, flow=value)], target_temperature_c=70)[0]
            self.assertIsNone(result['demand_kw'])
            self.assertEqual(result['unknown_cycles'], ['1'])
            self.assertEqual(result['status'], 'missing_data')

    def test_missing_active_return_makes_total_unknown_but_keeps_other_cycle(self):
        result = calculate([row(0, second={'volume_flow_m3h': .2})], target_temperature_c=70)[0]
        self.assertIsNone(result['demand_kw'])
        self.assertEqual(result['cycle_demand_kw']['1'], 17.445)
        self.assertIsNone(result['cycle_demand_kw']['2'])
        self.assertEqual(result['active_cycles'], ['1', '2'])

    def test_supply_is_not_needed_to_compute_demand_at_an_existing_target(self):
        result = calculate([row(0, supply=None)], target_temperature_c=70)[0]
        self.assertEqual(result['demand_kw'], 17.445)

    def test_flow_thresholds_and_meter_mapping_are_explicit(self):
        rows = [row(i, supply=90, flow=.004, second={'volume_flow_m3h': .4,
                 'flow_temperature_c': 65, 'return_temperature_c': 35}) for i in range(7)]
        result = format_heating_demand(rows, DAY, {'a': 2, 'b': 1},
                                     min_flow_m3h={'a': .01, 'b': .005})[-1]
        self.assertEqual(result['target_temperature_c'], 65)
        self.assertEqual(result['active_cycles'], ['a'])
        self.assertEqual(result['cycle_demand_kw']['b'], 0)

    def test_cold_recirculation_and_hot_returns_cannot_teach_target(self):
        for supply, returned in [(18, 17), (70, 69), (70, 75)]:
            result = calculate([row(i, supply=supply, returned=returned) for i in range(20)])
            self.assertTrue(all(r['target_temperature_c'] is None for r in result))

    def test_short_repeated_samples_spikes_and_ramps_are_not_plateaus(self):
        cases = [[row(i / 10) for i in range(20)],
                 [row(i, supply=40 + 3 * i, returned=20) for i in range(15)],
                 [row(i, supply=90 if i == 4 else 50 + i, returned=20) for i in range(15)]]
        for rows in cases:
            self.assertTrue(all(r['target_temperature_c'] is None for r in calculate(rows)))

    def test_gaps_and_off_periods_break_plateau_duration(self):
        for rows in [[row(i) for i in [0, 1, 2, 8, 9, 10]],
                     [row(i, flow=0 if i == 3 else .5) for i in range(8)]]:
            self.assertTrue(all(r['target_temperature_c'] is None for r in calculate(rows)))

    def test_upper_plateaus_resist_troughs_and_expire_for_lower_regime(self):
        rows = [row(i) for i in range(10)] + [row(i, supply=60) for i in range(10, 50)]
        result = calculate(rows, target_window_seconds=900)
        self.assertEqual(result[17]['target_temperature_c'], 70)
        self.assertEqual(result[-1]['target_temperature_c'], 60)
        self.assertEqual(result[:20], calculate(rows[:20], target_window_seconds=900))

    def test_stale_target_expires_instead_of_becoming_a_permanent_default(self):
        rows = [row(i) for i in range(10)] + [row(131, supply=50)]
        result = calculate(rows)[-1]
        self.assertIsNone(result['target_temperature_c'])
        self.assertIsNone(result['demand_kw'])

    def test_previous_day_history_preserves_target_without_emitting_previous_day(self):
        rows = [row(i) for i in range(-10, 3)]
        result = calculate(rows)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['target_temperature_c'], 70)
        self.assertEqual(result[0]['status'], 'estimated')

    def test_duplicate_unsorted_and_malformed_rows(self):
        duplicate = row(1, returned=50)
        result = calculate([row(1), row(0), duplicate, None, {},
                            {'timestamp': 'bad'}, row(1440)], target_temperature_c=70)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]['demand_kw'], 11.63)
        missing = calculate([{'timestamp': DAY+'-00-00-00', 'states': None}])[0]
        self.assertIsNone(missing['demand_kw'])
        json.dumps(missing, allow_nan=False)

    def test_net_return_heat_offsets_other_circuit_before_aggregate_clamp(self):
        second = {'volume_flow_m3h': .5, 'return_temperature_c': 80}
        result = calculate([row(0, returned=60, second=second)], target_temperature_c=70)[0]
        self.assertEqual(result['demand_kw'], 0)
        self.assertLess(result['cycle_demand_kw']['2'], 0)

    def test_ambiguous_energy_counter_does_not_affect_demand(self):
        rows = [row(i) for i in range(8)]
        baseline = calculate(rows)
        for r in rows:
            r['states']['1'].update(energy_kwh=58461000)
        self.assertEqual(calculate(rows), baseline)

    def test_contradictory_flow_and_power_are_unknown_and_cannot_teach_target(self):
        rows = [row(i, supply=74, returned=34, flow=2.42) for i in range(10)]
        for r in rows:
            r['states']['1']['power_w'] = 0
        inferred = calculate(rows)
        self.assertTrue(all(r['target_temperature_c'] is None for r in inferred))
        result = calculate(rows, target_temperature_c=70)[-1]
        self.assertIsNone(result['demand_kw'])
        self.assertEqual(result['status'], 'inconsistent_data')
        self.assertEqual(result['inconsistent_cycles'], ['1'])

    def test_power_crosscheck_allows_rounding_and_ignores_idle_readings(self):
        rows = [row(i) for i in range(8)]
        for r in rows:
            r['states']['1']['power_w'] = 17000
            r['states']['2'].update(power_w=58461000, flow_temperature_c=90, return_temperature_c=10)
        self.assertEqual(calculate(rows)[-1]['demand_kw'], 17.445)

    def test_high_demand_is_not_capped_at_boiler_rating(self):
        sample = row(0, supply=40, returned=20, flow=2)
        sample['states']['1']['power_w'] = 46520
        self.assertEqual(calculate([sample], target_temperature_c=70)[0]['demand_kw'], 116.3)

    def test_invalid_options_fail_explicitly(self):
        for options in [{'target_temperature_c': math.nan}, {'target_window_seconds': 0},
                        {'plateau_quantile': 2}, {'min_flow_m3h': {'1': .01}},
                        {'min_plateau_delta_c': 0}]:
            with self.assertRaises(ValueError):
                calculate([], **options)
        with self.assertRaises(ValueError):
            format_heating_demand([], DAY, {'1': 1, '2': 1})

    def test_formatter_writes_one_daily_metric_with_previous_day_history(self):
        tree = ast.parse(Path('services/data_formatter.py').read_text(encoding='utf-8'))
        loop = next(node for node in tree.body if isinstance(node, ast.For))
        section = next(node for node in loop.body if isinstance(node, ast.If)
                       and ast.unparse(node.test) == "'heating_demand' in data_types_to_digest")
        for exists in [True, False]:
            outputs = {}
            loader = Mock(side_effect=lambda path: [row(i) for i in range(-10, 0)]
                          if path.endswith('.2026-10-25') else [row(0)])
            namespace = {'data_types_to_digest': ['heating_demand'], 'digestion_daystamp': DAY,
                'digestion_day': START, 'timedelta': timedelta, 'log_file_suffix': '', 'export_path_prefix': '',
                'os': Mock(path=Mock(exists=Mock(return_value=exists), join=lambda *p: '/'.join(p))),
                'get_project_root': lambda: '/unused', 'load_ndjson_to_json_list': loader,
                'load_json_to_dict': Mock(return_value={'cycles': {str(c): {'meter': c, 'min_flow_m3h': .005}
                                                                  for c in range(1, 5)}}),
                'format_heating_demand': format_heating_demand, 'heating_demand_options': {},
                'export_json_list_to_json_file': lambda data, path: outputs.update({path: data}),
                'report': Mock(), 'log': Mock(), 'ModuleException': RuntimeError, 'ServiceException': Mock()}
            exec(compile(ast.Module(body=[section], type_ignores=[]), 'demand-section', 'exec'), namespace)
            self.assertEqual(list(outputs), ['data/formatted/'+DAY+'/heating_demand.json'])
            values = next(iter(outputs.values()))
            if exists:
                self.assertEqual(loader.call_count, 2)
                self.assertEqual(values[0]['target_temperature_c'], 70)
            else:
                loader.assert_not_called()
                self.assertEqual(values, [])
            namespace['ServiceException'].assert_not_called()

    def test_backfill_selects_ten_days_and_only_the_new_metric(self):
        tree = ast.parse(Path('services/data_formatter.py').read_text(encoding='utf-8'))
        selection = next(node for node in tree.body if isinstance(node, ast.If)
                         and ast.unparse(node.test) == 'heating_demand_backfill_days is not None')
        class FixedDateTime(datetime):
            @classmethod
            def now(cls):
                return cls(2026, 10, 27, 0, 15)
        namespace = {'heating_demand_backfill_days': 10, 'datetime': FixedDateTime, 'timedelta': timedelta}
        exec(compile(ast.Module(body=[selection], type_ignores=[]), 'backfill-days', 'exec'), namespace)
        self.assertEqual(namespace['data_types_to_digest'], ['heating_demand'])
        dates = namespace['digestion_days']
        self.assertEqual(len(dates), 10)
        self.assertEqual(dates[0].strftime('%Y-%m-%d'), '2026-10-18')
        self.assertEqual(dates[-1].strftime('%Y-%m-%d'), '2026-10-27')
        loop = next(node for node in tree.body if isinstance(node, ast.For))
        suffix = next(node for node in loop.body if isinstance(node, ast.If))
        for date in dates:
            namespace.update(parse_old_logs=False, digestion_day=date,
                             digestion_daystamp=date.strftime('%Y-%m-%d'))
            exec(compile(ast.Module(body=[suffix], type_ignores=[]), 'backfill-suffix', 'exec'), namespace)
            self.assertEqual(namespace['log_file_suffix'], '' if date == dates[-1]
                             else '.'+date.strftime('%Y-%m-%d'))


if __name__ == '__main__':
    unittest.main()
