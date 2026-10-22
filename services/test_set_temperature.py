"""Offline interpolation/display regression tests; no project or device imports."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('set_temperature', ROOT / 'utils/set_temperature.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


def schedule(values, day=100):
    return {str(day): {str(hour): value for hour, value in enumerate(values)}}


class InterpolationTests(unittest.TestCase):
    def test_consecutive_rises_meet_without_jumps(self):
        data = schedule([14] * 4 + [17, 19, 20] + [20] * 17)
        for hour in range(3, 7):
            self.assertAlmostEqual(target.interpolate_set_temperature(data, 100, hour, 1),
                                   target.interpolate_set_temperature(data, 100, hour + 1, 0))
        self.assertEqual(target.interpolate_set_temperature(data, 100, 4, .5), 18)
        self.assertEqual(target.interpolate_set_temperature(data, 100, 5, .5), 19.5)

    def test_long_plateau_keeps_three_hour_ramp(self):
        data = schedule([14] * 8 + [20] * 16)
        for hour, value in [(4, 14), (5, 14), (6, 16), (7, 18), (8, 20)]:
            self.assertEqual(target.interpolate_set_temperature(data, 100, hour, 0), value)

    def test_short_plateau_and_downward_step(self):
        data = schedule([20] * 4 + [14, 14, 20] + [20] * 17)
        self.assertEqual(target.interpolate_set_temperature(data, 100, 3, 1), 20)
        self.assertEqual(target.interpolate_set_temperature(data, 100, 4, 0), 14)
        self.assertEqual(target.interpolate_set_temperature(data, 100, 5, 0), 17)

    def test_midnight_ramp_and_daily_schedule_rollover(self):
        yesterday = schedule([14] * 24)
        today = schedule([14, 20] + [20] * 22, 101)
        complete = yesterday | today
        _, history = target.schedule_with_recent_history(complete, {}, 100, 23)
        combined, recent = target.schedule_with_recent_history(today, history, 101, 0)
        self.assertEqual(target.interpolate_set_temperature(complete, 100, 23, 1), 18)
        self.assertEqual(target.interpolate_set_temperature(combined, 101, 0, 0), 18)
        self.assertEqual(len(recent), 4)
        self.assertNotIn('100', today)  # Input is not mutated.

    def test_current_schedule_overrides_remembered_values(self):
        data = schedule([21] * 24)
        combined, _ = target.schedule_with_recent_history(data, {'2404': 14}, 100, 5)
        self.assertEqual(combined['100']['4'], 21)

    def test_missing_history_or_future_is_safe(self):
        data = schedule([17, 19])
        self.assertEqual(target.interpolate_set_temperature(data, 100, 0, 0), 17)
        self.assertEqual(target.interpolate_set_temperature(data, 100, 1, .5), 19)

    def test_recorded_target_matches_control_including_legacy_logs(self):
        for interpolated, expected in [(18, 18), (12, 14), (None, 14)]:
            state = {'set_temps': {'1': 14}, 'set_temps_interp': {'1': interpolated}}
            self.assertEqual(target.room_control_set_temperature(state, '1'), expected)
        self.assertEqual(target.room_control_set_temperature({'set_temps': {'1': 14}}, '1'), 14)

    def test_formatter_exports_control_signal(self):
        tree = ast.parse((ROOT / 'services/data_formatter.py').read_text(encoding='utf-8'))
        block = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and
                     ast.unparse(n.test) == "'room_set_temps' in data_types_to_digest")
        exported = {}
        env = dict(data_types_to_digest=['room_set_temps'], digestion_daystamp='2026-10-22',
                   log_file_suffix='', export_path_prefix='',
                   get_rooms_info=lambda: {'1': {}},
                   load_ndjson_to_json_list=lambda _: [
                       {'timestamp': 'a', 'set_temps': {'1': 14}, 'set_temps_interp': {'1': 16}},
                       {'timestamp': 'b', 'set_temps': {'1': 14}, 'set_temps_interp': {'1': 12}},
                       {'timestamp': 'c', 'set_temps': {'1': 14}}],
                   export_json_list_to_json_file=lambda rows, path: exported.update(rows=rows),
                   room_control_set_temperature=target.room_control_set_temperature,
                   report=lambda *a, **kw: None, log=lambda *a: None)
        exec(compile(ast.Module(body=[block], type_ignores=[]), '<formatter>', 'exec'), env)
        self.assertEqual([row['set_temp'] for row in exported['rows']], [16, 14, 14])

    def test_dashboard_matches_python_and_preserves_vertical_drops(self):
        data = schedule([14] * 4 + [17, 19, 20, 14, 14, 20] + [20] * 14)
        samples = [[100, hour, frac] for hour in range(24) for frac in [0, .25, .5, .75, 1]]
        js = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('docs/data.js', 'utf8');
const names = ['roomControlSetTemperature', 'interpolateRoomSetTemperature',
               'roomScheduleWithRecentHistory', 'projectedRoomControlSchedule',
               'extractRoomScheduleFromCondensedSchedule'];
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = {condensedSchedule: {'1': input.data}, systemNode: {},
             dayStamp: () => 'today', getUnixDay: () => 100,
             getFractionalHourOfDay: () => 4.5};
vm.createContext(ctx);
for (const name of names) {
    vm.runInContext(source.match(new RegExp('function ' + name + '\\([\\s\\S]*?\\n}'))[0], ctx);
}
const values = input.samples.map(args => ctx.interpolateRoomSetTemperature(input.data, ...args));
const points = ctx.projectedRoomControlSchedule(input.data, 100, 4.5);
assert.equal(points[0].set_temp, 18);
assert.deepEqual(Array.from(points.filter(p => p.h_of_day_frac === 7), p => p.set_temp), [20, 14]);
const arrayData = {'100': Array.from({length: 24}, (_, h) => input.data['100'][h])};
assert.equal(ctx.interpolateRoomSetTemperature(arrayData, 100, 4, .5), 18);
assert.equal(ctx.roomControlSetTemperature({set_temps: [null, 14], set_temps_interp: [null, 16]}, 1), 16);
assert.equal(ctx.roomControlSetTemperature({set_temps: {'1': 14}}, 1), 14);
const merged = ctx.roomScheduleWithRecentHistory({'101': {'0': 14, '1': 20}},
    {'2421': 14, '2422': 14, '2423': 14}, 101, 0);
assert.equal(ctx.interpolateRoomSetTemperature(merged, 101, 0, 0), 18);
const past = ctx.extractRoomScheduleFromCondensedSchedule(1, [{h_of_day_frac: 4, set_temp: 17}], 'yesterday');
assert.equal(past.roomScheduleRestOfDay.length, 0);
const today = ctx.extractRoomScheduleFromCondensedSchedule(1, [{h_of_day_frac: 4, set_temp: 17}], 'today');
assert.equal(today.roomScheduleRestOfDay[0].set_temp, 18);
process.stdout.write(JSON.stringify(values));
"""
        result = subprocess.run(['node', '-e', js], input=json.dumps(dict(data=data, samples=samples)),
                                cwd=ROOT, text=True, capture_output=True, check=True)
        actual = json.loads(result.stdout)
        expected = [target.interpolate_set_temperature(data, *args) for args in samples]
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
