import unittest

from utils.heat_delivery_formatter import heatmeter_live_snapshot
from utils.external_temperature_formatter import ws90_live_snapshot


class LiveSnapshotTests(unittest.TestCase):
    def test_heat_power_is_checked_and_return_temperature_is_published(self):
        sample = {'flow_temperature_c': 60, 'return_temperature_c': 40,
                  'volume_flow_m3h': .5, 'power_w': 11630}
        result = heatmeter_live_snapshot({1: sample}, '2026-11-03-12-00-00')
        self.assertEqual(result['1'], {'temp': 60, 'return_temp': 40, 'flow': .5, 'power': 11.63})
        self.assertEqual(result['last_updated'], '2026-11-03-12-00-00')
        bad = {**sample, 'power_w': 33391000}
        self.assertIsNone(heatmeter_live_snapshot({1: bad}, 'now')['1']['power'])
        self.assertEqual(heatmeter_live_snapshot({1: {'power_w': 0}}, 'now')['1']['power'], 0)
        self.assertIsNone(heatmeter_live_snapshot({1: None}, 'now')['1']['power'])

    def test_weather_timestamp_is_actual_observation_and_invalid_fields_are_not_zero(self):
        sample = {'timestamp': '2026-11-03-12-00-10', 'last_updated': '2026-11-03-12-00-00',
                  'state': {'temperature_c': -2, 'humidity_pct': 50, 'wind_speed_m_s': None}}
        result = ws90_live_snapshot(sample)
        self.assertEqual(result['timestamp'], sample['last_updated'])
        self.assertEqual(result['temperature_c'], -2)
        self.assertIsNone(result['wind_speed_m_s'])
        self.assertIsNone(ws90_live_snapshot({**sample, 'last_updated': '2026-11-03-11-00-00'}))
        self.assertIsNone(ws90_live_snapshot(None))


if __name__ == '__main__':
    unittest.main()
