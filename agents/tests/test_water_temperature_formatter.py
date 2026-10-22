import math
import unittest
from utils.water_temperature_formatter import format_cycle_water_temperatures

DAY = '2026-10-19'
MAPPING = {'1': 1, '2': 2, '3': 3, '4': 4}

def row(stamp, **temperatures):
    return {'timestamp': stamp, 'states': {meter: {'flow_temperature_c': value} for meter, value in temperatures.items()}}

class WaterTemperatureFormatterTests(unittest.TestCase):
    def test_cycle_separation_and_precision(self):
        result = format_cycle_water_temperatures([row(DAY+'-12-00-00', **{'1': 58.25, '2': 61, '3': 33, '4': 40})], DAY, MAPPING)
        self.assertEqual([result[str(c)][0]['water_temp'] for c in range(1, 5)], [58.25, 61, 33, 40])

    def test_mapping_not_assumed(self):
        result = format_cycle_water_temperatures([row(DAY+'-12-00-00', **{'2': 51})], DAY, {'1': 2})
        self.assertEqual(result['1'][0]['water_temp'], 51)

    def test_invalid_readings_not_fabricated_as_zero(self):
        rows = [row(DAY+'-12-00-00', **{'1': None, '2': True, '3': math.nan, '4': math.inf}),
                row(DAY+'-12-01-00', **{'1': 0, '2': '50'})]
        result = format_cycle_water_temperatures(rows, DAY, MAPPING)
        self.assertEqual([r['water_temp'] for r in result['1']], [None, 0])
        self.assertTrue(all(r['water_temp'] is None and r['return_temp'] is None for c in ['2', '3', '4'] for r in result[c]))

    def test_return_temperature_is_independent_and_per_cycle(self):
        rows = [{'timestamp': DAY+'-12-00-00', 'states': {
            '2': {'flow_temperature_c': 60.25, 'return_temperature_c': 39.5},
            '3': {'flow_temperature_c': None, 'return_temperature_c': 0}}}]
        result = format_cycle_water_temperatures(rows, DAY, {'1': 2, '4': 3})
        self.assertEqual(result['1'][0], {'timestamp': DAY+'-12-00-00', 'water_temp': 60.25, 'return_temp': 39.5})
        self.assertEqual(result['4'][0]['return_temp'], 0)
        self.assertIsNone(result['4'][0]['water_temp'])

    def test_unknown_return_does_not_remove_supply_or_become_zero(self):
        for value in [None, True, '30', math.nan, math.inf]:
            rows = [{'timestamp': DAY+'-12-00-00', 'states': {'1': {'flow_temperature_c': 50, 'return_temperature_c': value}}}]
            result = format_cycle_water_temperatures(rows, DAY, MAPPING)['1'][0]
            self.assertEqual(result['water_temp'], 50)
            self.assertIsNone(result['return_temp'])

    def test_day_filter_sort_and_duplicate_timestamp(self):
        rows = [row(DAY+'-12-01-00', **{'1': 51}), row('2026-10-18-23-59-00', **{'1': 40}),
                row(DAY+'-12-00-00', **{'1': 50}), row(DAY+'-12-01-00', **{'1': 52}),
                {}, {'timestamp': 'invalid'}, None]
        result = format_cycle_water_temperatures(rows, DAY, MAPPING)['1']
        self.assertEqual([value['water_temp'] for value in result], [50, 52])

if __name__ == '__main__':
    unittest.main()
