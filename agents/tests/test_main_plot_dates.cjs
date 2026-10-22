const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../docs/data.js'), 'utf8').replace(/\r\n/g, '\n');
const context = vm.createContext({Number, Math, Date, structuredClone, mainGraphSetting: {day:'2026-10-20'},
    dayStamp: () => '2026-10-21', getFractionalHourOfDay: () => 10, getUnixDay: () => 123,
    getHourOfDay: () => 10, condensedSchedule: undefined, d3: {sum: values => values.reduce((a,b) => a+b, 0)}});
vm.runInContext(source.slice(source.indexOf('function extractHeatingPeriodsFromHeatingState('), source.indexOf('function convertTimestamps(')), context);
context.samples = [{h_of_day_frac: 8, cycle_states:{1:1}}, {h_of_day_frac: 9, cycle_states:{1:1}}];
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code, context)));
assert.deepEqual(evaluate('extractHeatingPeriodsFromHeatingState(1,samples)'), [{x1:8,x2:24}]);
assert.deepEqual(evaluate("extractHeatingPeriodsFromHeatingState(1,samples,'2026-10-21')"), [{x1:8,x2:10}]);
assert.deepEqual(evaluate('extractHeatingPeriodsFromHeatingState(1,undefined)'), []);
context.targets = [{h_of_day_frac:9,set_temp:20}, {h_of_day_frac:20,set_temp:22}];
assert.deepEqual(evaluate("extractRoomScheduleFromCondensedSchedule(1,targets,'2026-10-20').roomSchedule"), context.targets);
assert.deepEqual(evaluate("extractRoomScheduleFromCondensedSchedule(1,targets,'2026-10-20').roomScheduleRestOfDay"), []);
assert.deepEqual(evaluate('extractRoomScheduleFromCondensedSchedule(1,[])').roomSchedule, []);
assert.match(source, /primaryMainPlot \? \{day: mainGraphSetting.day, onDayChange: navigateMainPlotDay\}/);
assert.match(source, /if \(isToday\) roomValveStateData.push/);
assert.match(source, /elem.timestamp\?\.slice\(0, 10\) === mainGraphSetting.day/);
assert.match(source, /if \(isToday && requestLists\)/);
assert.match(source, /Az adott napra nincs adat\./);
console.log('Ordinary main plot dates: shared frame navigation, historical targets, midnight circulation, missing days and isolation from today\'s data passed.');
