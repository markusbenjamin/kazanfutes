import unittest
from datetime import datetime, timedelta
from utils.room_control_kpi_formatter import format_room_control_kpis


class RoomControlKPIsTest(unittest.TestCase):
    start = datetime(2026, 10, 21)
    rooms = {'1': {'controlled': True, 'cycle': '2'}, '11': {'controlled': False, 'cycle': '2'}}

    def snapshot(self, minutes=0, temp=20, target=21, command=1, sensor_age=0, occupied=True):
        stamp = self.start + timedelta(minutes=minutes)
        return {'timestamp': stamp.strftime('%Y-%m-%d-%H-%M-%S'), 'measured_temps': {'1': temp},
                'sensor_last_updated': {'1': (stamp - timedelta(seconds=sensor_age)).strftime('%Y-%m-%d-%H-%M-%S')},
                'set_temps': {'1': target}, 'pump_votes': {'2': command}, 'occupancy': {'1': occupied}}

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

    def test_valves_weight_heating_and_split_quadrants(self):
        rooms = {'1': {'controlled': True, 'cycle': '2', 'thermostats': 'a;b'}}
        snapshot = {**self.snapshot(), 'valve_states': {'1': [0, 50]}}
        result = format_room_control_kpis([snapshot], '2026-10-21', rooms,
                                         end_time=self.start + timedelta(minutes=2))
        row = result['rooms']['1']
        self.assertEqual(row['heating_seconds'], 30)
        self.assertEqual(row['quadrant_seconds']['below_on'], 30)
        self.assertEqual(row['quadrant_seconds']['below_off'], 90)
        self.assertEqual(row['mae_on_c'], 1)
        self.assertEqual(result['schema_version'], 3)

    def test_comfort_only_counts_confirmed_occupied_time(self):
        rows = [self.snapshot(temp=21, occupied=False), self.snapshot(1, temp=21, occupied=True),
                self.snapshot(2, temp=23, occupied=True), self.snapshot(3, temp=21, occupied=None)]
        result = self.calculate(rows, minutes=4)
        self.assertEqual(result['valid_seconds'], 240)
        self.assertEqual(result['occupied_seconds'], 120)
        self.assertEqual(result['comfort_seconds'], 60)
        self.assertEqual(result['comfort_pct'], 50)

    def test_unknown_or_unoccupied_is_not_false_zero_comfort(self):
        for occupancy in [False, None, 1, 'true']:
            row = self.calculate([self.snapshot(temp=21, occupied=occupancy)])
            self.assertEqual(row['occupied_seconds'], 0)
            self.assertIsNone(row['comfort_pct'])

    def test_comfort_does_not_depend_on_known_heating_or_valves(self):
        snapshot = self.snapshot(temp=21)
        snapshot['pump_votes'] = {}
        row = self.calculate([snapshot])
        self.assertEqual(row['valid_seconds'], 0)
        self.assertEqual(row['occupied_seconds'], 120)
        self.assertEqual(row['comfort_pct'], 100)

    def test_presence_hold_is_bounded_independently(self):
        first = self.snapshot(temp=21)
        later = self.snapshot(minutes=3, temp=21)
        later.pop('occupancy')
        row = self.calculate([first, later], minutes=5)
        self.assertEqual(row['valid_seconds'], 300)
        self.assertEqual(row['occupied_seconds'], 180)
        self.assertEqual(row['comfort_seconds'], 180)

    def test_closed_valves_prevent_false_heating(self):
        rooms = {'1': {'controlled': True, 'cycle': '2', 'thermostats': 'a'}}
        snapshot = {**self.snapshot(), 'valve_states': {'1': [0]}}
        row = format_room_control_kpis([snapshot], '2026-10-21', rooms,
                                      end_time=self.start + timedelta(minutes=2))['rooms']['1']
        self.assertEqual(row['heating_seconds'], 0)
        self.assertEqual(row['quadrant_seconds']['below_off'], 120)
        self.assertIsNone(row['mae_on_c'])

    def test_missing_invalid_valves_are_unknown_only_when_circulating(self):
        rooms = {'1': {'controlled': True, 'cycle': '2', 'thermostats': 'a;b'}}
        for values in [None, [], [50], [None, 50], [True, 50], [-1, 50], [101, 50]]:
            snapshot = {**self.snapshot(), 'valve_states': {'1': values}}
            row = format_room_control_kpis([snapshot], '2026-10-21', rooms,
                                          end_time=self.start + timedelta(minutes=2))['rooms']['1']
            self.assertEqual(row['valid_seconds'], 0)
            snapshot['pump_votes']['2'] = 0
            row = format_room_control_kpis([snapshot], '2026-10-21', rooms,
                                          end_time=self.start + timedelta(minutes=2))['rooms']['1']
            self.assertEqual(row['valid_seconds'], 120)

    def test_no_smart_valves_mean_full_opening(self):
        rooms = {'1': {'controlled': True, 'cycle': '2', 'thermostats': True}}
        row = format_room_control_kpis([self.snapshot()], '2026-10-21', rooms,
                                      end_time=self.start + timedelta(minutes=2))['rooms']['1']
        self.assertEqual(row['heating_seconds'], 120)


if __name__ == '__main__':
    unittest.main()
