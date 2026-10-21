import unittest
from datetime import datetime, timedelta
from utils.room_control_kpi_formatter import format_room_control_kpis


class RoomControlKPIsTest(unittest.TestCase):
    start = datetime(2026, 10, 21)
    rooms = {'1': {'controlled': True, 'cycle': '2'}, '11': {'controlled': False, 'cycle': '2'}}

    def snapshot(self, minutes=0, temp=20, target=21, command=1, sensor_age=0):
        stamp = self.start + timedelta(minutes=minutes)
        return {'timestamp': stamp.strftime('%Y-%m-%d-%H-%M-%S'), 'measured_temps': {'1': temp},
                'sensor_last_updated': {'1': (stamp - timedelta(seconds=sensor_age)).strftime('%Y-%m-%d-%H-%M-%S')},
                'set_temps': {'1': target}, 'pump_votes': {'2': command}}

    def calculate(self, entries, minutes=2, **options):
        return format_room_control_kpis(entries, '2026-10-21', self.rooms,
                                       end_time=self.start + timedelta(minutes=minutes), **options)['rooms']['1']

    def test_absolute_error_does_not_cancel_and_is_time_weighted(self):
        result = self.calculate([self.snapshot(), self.snapshot(minutes=1, temp=22)])
        self.assertAlmostEqual(result['mae_on_c'], 1)
        self.assertAlmostEqual(result['bias_on_c'], 0)
        self.assertEqual(result['quadrant_seconds']['below_on'], 60)
        self.assertEqual(result['quadrant_seconds']['above_on'], 60)
        self.assertEqual(result['coverage_pct'], 100)

    def test_step_commands_and_targets_not_interpolated(self):
        result = self.calculate([self.snapshot(command=0), self.snapshot(minutes=1, target=20, command=1)])
        self.assertEqual(result['heating_seconds'], 60)
        self.assertEqual(result['quadrant_seconds']['below_off'], 60)
        self.assertEqual(result['mae_on_c'], 0)
        self.assertEqual(result['comfort_pct'], 50)

    def test_all_four_quadrants(self):
        rows = [self.snapshot(i, temp=22 if i % 2 else 20, command=1 if i < 2 else 0) for i in range(4)]
        result = self.calculate(rows, minutes=4)
        self.assertEqual(list(result['quadrant_seconds'].values()), [60, 60, 60, 60])

    def test_tolerance_boundary_and_zero_temperature(self):
        result = self.calculate([self.snapshot(temp=0, target=.5)])
        self.assertEqual(result['comfort_pct'], 100)
        self.assertEqual(result['mae_on_c'], .5)

    def test_no_heating_is_unknown_not_zero_error(self):
        result = self.calculate([self.snapshot(temp=22, command=0)])
        self.assertIsNone(result['mae_on_c'])
        self.assertIsNone(result['bias_on_c'])
        self.assertEqual(result['quadrant_seconds']['above_off'], 120)

    def test_gap_hold_is_bounded(self):
        result = self.calculate([self.snapshot()], minutes=60)
        self.assertEqual(result['valid_seconds'], 180)
        self.assertEqual(result['coverage_pct'], 5)

    def test_unknown_reading_breaks_the_interval(self):
        result = self.calculate([self.snapshot(), self.snapshot(minutes=1, temp=None)])
        self.assertEqual(result['valid_seconds'], 60)

    def test_stale_and_future_sensor_readings_are_excluded(self):
        for age in [7200, -60]:
            result = self.calculate([self.snapshot(sensor_age=age)])
            self.assertEqual(result['valid_seconds'], 0)
            self.assertIsNone(result['mae_on_c'])

    def test_separate_records_at_same_time_are_merged(self):
        snapshot = self.snapshot()
        command = {'timestamp': snapshot['timestamp'], 'pump_votes': snapshot.pop('pump_votes')}
        result = self.calculate([command, snapshot])
        self.assertEqual(result['heating_seconds'], 120)

    def test_missing_command_and_invalid_values_do_not_look_good(self):
        for changes in [{'pump_votes': {}}, {'measured_temps': {'1': True}}, {'set_temps': {'1': -1}}]:
            snapshot = {**self.snapshot(), **changes}
            self.assertEqual(self.calculate([snapshot])['valid_seconds'], 0)

    def test_future_events_are_ignored_and_uncontrolled_rooms_excluded(self):
        result = format_room_control_kpis([self.snapshot(), self.snapshot(minutes=3)], '2026-10-21', self.rooms,
                                         end_time=self.start + timedelta(minutes=1))
        self.assertEqual(result['rooms']['1']['heating_seconds'], 60)
        self.assertNotIn('11', result['rooms'])


if __name__ == '__main__':
    unittest.main()
