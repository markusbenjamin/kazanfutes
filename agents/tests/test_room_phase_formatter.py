import ast
from datetime import datetime, timedelta
from pathlib import Path
import math
import unittest

from utils.room_phase_formatter import format_room_phase_points, _Fit, _step


DAY = '2026-10-26'
START = datetime(2026, 10, 26, 12)
ROOMS = {'1': {'controlled': True, 'cycle': '1', 'thermostats': 'a;b'},
         '2': {'controlled': True, 'cycle': '1', 'thermostats': True},
         '3': {'controlled': False, 'cycle': '1'}}
MAPPING = {'rooms': [{'legacy_room_numbers': [1], 'probes': [
    {'device': 'rad', 'probe': 'p1'}, {'device': 'rad', 'probe': 'p2'}]}]}


def stamp(time):
    return time.strftime('%Y-%m-%d-%H-%M-%S')


def control(time=START, **changes):
    return {'timestamp': stamp(time), 'measured_temps': {'1': 20, '2': 20},
            'sensor_last_updated': {'1': stamp(time), '2': stamp(time)},
            'set_temps': {'1': 28}, 'set_temps_interp': {'1': 22, '2': 21},
            'valve_states': {'1': [50, 50]}, 'pump_states': {'1': 1},
            'room_states': {'1': 0}, **changes}


def probe(time=START, p1=40, p2=50):
    return {'timestamp': stamp(time), 'devices': {'rad': {'p1': p1, 'p2': p2}}}


def water(time=START, supply=60, returned=40):
    return {'timestamp': stamp(time), 'states': {'a': {'flow_temperature_c': supply, 'return_temperature_c': returned}}}


def run(controls=None, probes=None, waters=None, **kwargs):
    return format_room_phase_points(controls or [control()], probes or [], waters or [], DAY,
                                    ROOMS, MAPPING, {'1': 'a'}, **kwargs)


class RoomPhaseFormatterTest(unittest.TestCase):
    def test_logged_target_and_error_ungated_by_demand(self):
        row = run(probes=[probe()])['rooms']['1']['points'][0]
        self.assertEqual(row['error_k'], 2)
        self.assertEqual(row['radiator_temp_c'], 45)
        self.assertEqual(row['intensity_k'], 5)
        self.assertEqual(row['source'], 'measured')

    def test_no_uncontrolled_rooms_or_nominal_fallback(self):
        output = run([control(set_temps_interp={})], [probe()])
        self.assertNotIn('3', output['rooms'])
        row = output['rooms']['1']['points'][0]
        self.assertIsNone(row['error_k'])
        self.assertEqual(row['reason'], 'no_temperature_target')

    def test_freshness_future_and_unknowns(self):
        old = stamp(START - timedelta(hours=2))
        row = run([control(sensor_last_updated={'1': old})], [probe()])['rooms']['1']['points'][0]
        self.assertEqual(row['source'], 'unavailable')
        self.assertIsNone(row['intensity_k'])
        future = run(probes=[probe(START + timedelta(seconds=1))])['rooms']['1']['points'][0]
        self.assertIsNone(future['radiator_temp_c'])
        missing = run(probes=[probe(p2=None)])['rooms']['1']['points'][0]
        self.assertIsNone(missing['radiator_temp_c'], 'do not average only the hotter surviving probe')

    def test_cooling_persists_after_pump_off_and_uses_last_probe_seed(self):
        after = START + timedelta(minutes=1)
        output = run([control(), control(after, pump_states={'1': 0})],
                     [probe(), probe(after, p1=None, p2=None)], [water()])
        rows = output['rooms']['1']['points']
        self.assertEqual(rows[1]['source'], 'estimated')
        self.assertGreater(rows[1]['radiator_temp_c'], 40)
        self.assertLess(rows[1]['radiator_temp_c'], 45)
        self.assertGreater(rows[1]['intensity_k'], -20)

    def test_warmup_and_midnight_continuity_no_trv_uses_full_opening(self):
        start = datetime(2026, 10, 25, 21)
        controls = [control(start + timedelta(minutes=i), pump_states={'1': 0}) for i in range(185)]
        output = run(controls)
        rows = output['rooms']['2']['points']
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]['valve_fraction'], 1)
        self.assertEqual(rows[0]['source'], 'estimated')
        self.assertEqual(rows[0]['intensity_k'], -20)

    def test_model_gap_resets_and_missing_opening_not_100_percent(self):
        after = START + timedelta(minutes=10)
        output = run([control(), control(after)], [probe()], [water(), water(after)])
        self.assertEqual(output['rooms']['1']['points'][-1]['reason'], 'model_warmup')
        row = run([control(valve_states={})], waters=[water()])['rooms']['1']['points'][0]
        self.assertIsNone(row['valve_fraction'])
        self.assertEqual(row['reason'], 'missing_model_input')

    def test_parameters_require_excitation_and_are_causal(self):
        fit = _Fit()
        for index in range(150):
            fit.observe(START + timedelta(minutes=index), 40, 20, 50, .5, 1)
        self.assertEqual(fit.parameters()[1], [])
        result = run([control(), control(START + timedelta(minutes=1))], [probe()], [water()])
        extended = run([control(), control(START + timedelta(minutes=1)), control(START + timedelta(hours=1))],
                       [probe(), probe(START + timedelta(hours=1), 80, 80)], [water()])
        self.assertEqual(result['rooms']['1']['points'][0], extended['rooms']['1']['points'][0])

    def test_valve_log_freshness_is_not_renewed_by_control_snapshots(self):
        row = run(waters=[water()], valve_entries=[])['rooms']['1']['points'][0]
        self.assertIsNone(row['valve_fraction'])
        valves = [{'timestamp': stamp(START), 'states': {
            'a': {'valve': 20, 'lastseen': stamp(START)},
            'b': {'valve': 60, 'lastseen': stamp(START)}}}]
        row = run(waters=[water()], valve_entries=valves)['rooms']['1']['points'][0]
        self.assertEqual(row['valve_fraction'], .4)
        valves[0]['states']['a']['lastseen'] = stamp(START - timedelta(hours=2))
        row = run(waters=[water()], valve_entries=valves)['rooms']['1']['points'][0]
        self.assertIsNone(row['valve_fraction'])

    def test_dynamic_fit_recovers_cooling_with_movement(self):
        fit = _Fit()
        temperature = 70
        for index in range(90):
            fit.observe(START + timedelta(minutes=index), temperature, 20, None, 1, 0)
            temperature = _step(temperature, 20, 60, 900)
        model, fitted = fit.parameters()
        self.assertIn('cooling', fitted)
        self.assertEqual(model['cool_tau_s'], 900)

    def test_invalid_numeric_inputs_and_end_of_day(self):
        row = run(probes=[probe(p1=float('nan'))])['rooms']['1']['points'][0]
        self.assertEqual(row['source'], 'unavailable')
        output = run([control(), control(START + timedelta(days=1))], [probe()])
        self.assertEqual(len(output['rooms']['1']['points']), 1)
        with self.assertRaises(ValueError):
            run(offset_k=float('nan'))

    def test_regular_and_scoped_service_wiring(self):
        source = Path('services/data_formatter.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn("'room_phase'", source)
        self.assertIn("--room-phase-days", source)
        self.assertIn("data_types_to_digest = ['room_phase']", source)
        self.assertIn('room_phase_points.json', source)


if __name__ == '__main__':
    unittest.main()
