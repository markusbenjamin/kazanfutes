import unittest
from utils.radiator_formatter import format_radiator_temperatures, format_radiator_valves, radiator_probe_snapshot


class RadiatorFormatterTests(unittest.TestCase):
    mapping = {'rooms': [{'probes': [{'device': 'shelly', 'probe': 'temperature:100'},
                                   {'device': 'shelly', 'probe': 'temperature:101'}]}]}

    def test_sources_are_separate_and_missing_is_unknown(self):
        rows = format_radiator_temperatures([
            {'timestamp': '2026-10-22-10-00-00', 'shelly': {'temperature:100': 0, 'temperature:101': 42.3}},
            {'timestamp': '2026-10-22-10-01-00', 'shelly': {'temperature:100': True}},
            {'timestamp': '2026-10-21-10-00-00', 'shelly': {'temperature:100': 80}}], '2026-10-22', self.mapping)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['probes'], {'shelly/temperature:100': 0, 'shelly/temperature:101': 42.3})
        self.assertEqual(rows[1]['probes'], {'shelly/temperature:100': None, 'shelly/temperature:101': None})

    def test_invalid_and_duplicate_observations(self):
        rows = format_radiator_temperatures([
            None, {}, {'timestamp': 'bad'},
            {'timestamp': '2026-10-22-10-00-00', 'shelly': {'temperature:100': float('nan')}},
            {'timestamp': '2026-10-22-10-00-00', 'shelly': {'temperature:100': 30}}], '2026-10-22', self.mapping)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['probes']['shelly/temperature:100'], 30)

    def test_valves_are_actual_individual_percentages(self):
        rows = format_radiator_valves([{'timestamp': '2026-10-22-10-00-00', 'states': {
            '71': {'valve': 0, 'lastseen': '2026-10-22-09-59-00'},
            '75': {'valve': 60, 'lastseen': '2026-10-22-09-59-00'},
            '77': {'valve': 40, 'lastseen': '2026-10-22-08-00-00'},
            '79': {'valve': 101, 'lastseen': '2026-10-22-09-59-00'}}}], '2026-10-22')
        self.assertEqual(rows[0]['valves'], {'71': 0, '75': 60, '77': None, '79': None})

    def test_live_snapshot_does_not_publish_error_values(self):
        snapshot = radiator_probe_snapshot({'shelly': {'peripherals': {
            'temperature:100': {'temp': 0, 'errors': []},
            'temperature:101': {'temp': 85, 'errors': ['read_failed']}}}}, '2026-10-22-10-00-00')
        self.assertEqual(snapshot['devices']['shelly'], {'temperature:100': 0, 'temperature:101': None})


if __name__ == '__main__':
    unittest.main()
