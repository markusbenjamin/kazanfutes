const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const context = vm.createContext({console, Date, Number, Math, Map, Object, structuredClone});
vm.runInContext(fs.readFileSync('docs/live_plot_data.js','utf8'), context);
vm.runInContext(fs.readFileSync('docs/replay_temperatures.js','utf8'), context);
vm.runInContext(fs.readFileSync('docs/dashboard_replay.js','utf8'), context);
const run = code => vm.runInContext(code, context);
run(`
const day = '2026-11-10';
const state = (stamp,temp,pump) => ({timestamp:stamp,state:{last_updated:stamp,
 measured_temps:{1:temp},sensor_last_updated:{1:stamp},room_states:{1:pump},pump_states:{1:pump,2:0,3:0,4:0}}});
const history = {seed:[state('2026-11-09-23-59-50',19,0)],control:[
 state(day+'-09-00-00',20,1), state(day+'-10-00-00',21,0)], schedule:[]};
const plots = {weather_station:[{timestamp:day+'-09-00-00',temperature_c:5}],
 radiator_temps:[{timestamp:day+'-09-00-00',probes:{'probe/temperature:100':55}}],
 radiator_valves:[{timestamp:day+'-09-00-00',valves:{42:25}}],
 cycle_1_water_temps:[{timestamp:day+'-09-00-00',water_temp:60,return_temp:40}],
 gas_usage:[{timestamp:day+'-09-00-00',burnt_volume:1,burn_rate_in_m3_per_h:2}],
 room_1_measurements:[{timestamp:day+'-09-00-00',temp:20},{timestamp:day+'-10-00-00',temp:21}]};
const model = new DashboardReplayDay(day,history,plots);
const midnight = model.snapshot(new Date(2026,10,10));
const nine = model.snapshot(new Date(2026,10,10,9));
const late = model.snapshot(new Date(2026,10,10,10));
`);
assert.equal(run('midnight.system.state.measured_temps[1]'),19,'Seed midnight with the preceding day, never the first future reading');
assert.equal(run('midnight.system.state.external_temp'),null,'Future weather does not leak into midnight');
assert.equal(run('nine.system.state.measured_temps[1]'),20);
assert.equal(run('nine.system.state.radiator_probes.devices.probe["temperature:100"]'),55);
assert.equal(run('nine.system.state.radiator_valves.valves[42]'),25);
assert.equal(run('nine.system.state.heatmeters[1].temp'),60);
assert.equal(run('late.system.state.heatmeters[1].temp'),null,'Old water temperatures expire at playback time');
assert.equal(run('late.system.state.external_temp'),null,'Old weather expires at playback time');
assert.equal(run('late.system.state.measured_temps[1]'),21);
assert.equal(run('model.snapshot(new Date(2026,10,10,9)).system.state.measured_temps[1]'),20,'Backward seeking is independent of the previously rendered state');
assert.equal(run('midnight.system.switch.system'),1,'Enablement follows the agreed whole-day pump-on convention');
assert.equal(run('midnight.system.switch.cycles[4]'),-1);
assert.equal(run('new DashboardReplayDay(day,{seed:[],control:[history.seed[0]],schedule:[]},{}).snapshot(new Date(2026,10,10)).system.switch.system'),0);
run('nine.system.state.measured_temps[1] = 99;');
assert.equal(run('model.snapshot(new Date(2026,10,10,9)).system.state.measured_temps[1]'),20,'Rendering cannot mutate archived snapshots');
run(`dashboardReplayTime = new Date(2026,10,10,9).getTime();`);
assert.equal(run('replayPlotPayload({[day]:plots})[day].room_1_measurements.length'),1,'Clip before chart smoothing, aggregation and live endpoint injection');
assert.equal(run('replayPlotPayload({"2026-11-11":plots})["2026-11-11"].room_1_measurements'),undefined);
assert.equal(run('replayPlotPayload({[day]:{phase:{points:plots.room_1_measurements}}})[day].phase.points.length'),1);
run('dashboardReplayTime = null;');
assert.equal(run('replayPlotPayload({[day]:plots})[day].room_1_measurements.length'),2,'Returning live removes the cutoff');
assert.equal(run('replayAsOf(replayIndex([{timestamp:"b",value:1},{timestamp:"a",value:0},{timestamp:"b",value:2}]),"b").value'),2,'Sort once and let the latest duplicate win');
assert.equal(run('replayAsOf([],"x")'),null);
const pickerNodes = {
    'replay-day': {value:'2026-11-04'},
    'replay-date-display': {dataset:{},textContent:''},
    'replay-next-day': {disabled:false}
};
context.document = {getElementById:id=>pickerNodes[id]};
context.dayStamp = ()=>'2026-11-11';
context.dashboardPageOptions = ()=>({language:'hu'});
context.dashboardText = text=>text;
const cycleSource = fs.readFileSync('docs/cycle_heat_plots.js','utf8');
vm.runInContext(cycleSource.slice(cycleSource.indexOf('function selectorWeekday('),cycleSource.indexOf('function navigateSelectorPlotDay(')),context);
let loads = 0;
context.loadReplayDay = ()=>{loads++;};
run(`dashboardReplayTime = new Date(2026,10,4,12).getTime(); selectReplayDay(-1);`);
assert.equal(pickerNodes['replay-day'].value,'2026-11-03');
assert.equal(run('dashboardNow().getDate()'),4,'Selecting another day must not change the running replay');
assert.equal(loads,0,'Date arrows must never start loading');
run('selectReplayDay(1)');
assert.equal(pickerNodes['replay-day'].value,'2026-11-04');
pickerNodes['replay-day'].value='2026-11-11';
run('updateReplayWeekday(); selectReplayDay(1);');
assert.equal(pickerNodes['replay-next-day'].disabled,true,'Future dates are unavailable');
assert.equal(pickerNodes['replay-day'].value,'2026-11-11');
assert.equal(loads,0);
console.log('Replay: midnight seeding, as-of lookup, backward seek, day enablement, freshness, immutability, future clipping and live reset passed.');
