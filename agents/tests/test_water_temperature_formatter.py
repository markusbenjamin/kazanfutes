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
        self.assertEqual(result['1'], [{'timestamp': DAY+'-12-01-00', 'water_temp': 0}])
        self.assertEqual([result[c] for c in ['2', '3', '4']], [[], [], []])

    def test_day_filter_sort_and_duplicate_timestamp(self):
        rows = [row(DAY+'-12-01-00', **{'1': 51}), row('2026-10-18-23-59-00', **{'1': 40}),
                row(DAY+'-12-00-00', **{'1': 50}), row(DAY+'-12-01-00', **{'1': 52}),
                {}, {'timestamp': 'invalid'}, None]
        result = format_cycle_water_temperatures(rows, DAY, MAPPING)['1']
        self.assertEqual([value['water_temp'] for value in result], [50, 52])

if __name__ == '__main__':
    unittest.main()
