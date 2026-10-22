import unittest
from utils.room_control_kpi_formatter import format_room_control_errors


class RoomControlErrorsTest(unittest.TestCase):
    rooms = {'1': {'controlled': True, 'cycle': '1'}, '2': {'controlled': False, 'cycle': '1'}}

    def snapshot(self, demand=1, measured=20, target=21, stamp='2026-10-22-12-00-00', **extra):
        return {'timestamp': stamp, 'room_states': {'1': demand}, 'measured_temps': {'1': measured},
                'set_temps': {'1': target}, 'sensor_last_updated': {'1': stamp}, **extra}

    def value(self, entry):
        return format_room_control_errors([entry], '2026-10-22', self.rooms)[0]['errors']['1']

    def test_signed_error_only_while_room_demands(self):
        self.assertEqual(self.value(self.snapshot()), 1)
        self.assertEqual(self.value(self.snapshot(measured=22)), -1)
        self.assertEqual(self.value(self.snapshot(demand=0, measured=22)), 0)
        self.assertEqual(self.value(self.snapshot(demand=0, measured=None, target=None)), 0)
        self.assertEqual(self.value(self.snapshot(measured=0)), 21)

    def test_unknown_demand_and_stale_temperature(self):
        for demand in (None, 2, '1', 1.0):
            self.assertIsNone(self.value(self.snapshot(demand=demand)))
        for seen in ('2026-10-22-10-00-00', '2026-10-22-12-01-00', None):
            self.assertIsNone(self.value(self.snapshot(sensor_last_updated={'1': seen})))
        for value in (None, True, float('nan')):
            self.assertIsNone(self.value(self.snapshot(measured=value)))

    def test_complete_snapshots_only_day_filter_and_no_uncontrolled_room(self):
        rows = [self.snapshot(stamp='2026-10-21-23-59-59'), self.snapshot(),
                {'timestamp': '2026-10-22-12-00-00', 'room_votes': {'1': 0}},
                self.snapshot(measured=22)]
        result = format_room_control_errors(rows, '2026-10-22', self.rooms)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['errors'], {'1': -1})
        self.assertEqual(result[0]['demands'], {'1': 1})


if __name__ == '__main__':
    unittest.main()
