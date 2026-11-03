const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = require('./dashboard_test_context.cjs')({});
for (const name of ['cycle_heat_plots','room_metric_plots','boiler_power','boiler_metric_plots','radiator_plots'])
    vm.runInContext(fs.readFileSync('docs/' + name + '.js','utf8'),context);
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.rows = [{h_of_day_frac:1,value:40},{h_of_day_frac:1.01,value:42},
    {h_of_day_frac:2,value:44},{h_of_day_frac:2.01,value:45},
    {h_of_day_frac:3,value:48,live:true}];
const original=JSON.stringify(context.rows);
for (const splitter of ["splitCycleHeatReadings(rows,'value')", "splitRoomMetricReadings(rows,'value',.05)"]) {
    const segments=evaluate(splitter);
    assert.deepEqual(segments.map(segment=>segment.length),[2,3], 'join only the fresh endpoint, preserving earlier historical gaps');
    assert.equal(segments.at(-1).at(-1).live,true);
}
assert.equal(JSON.stringify(context.rows),original,'no cached/history array mutation');
context.rows.at(-1).live=false;
assert.equal(evaluate("splitCycleHeatReadings(rows,'value')").length,3,'unmarked historical gaps still split');
context.rows.at(-1).live=true;context.rows.at(-1).value=null;
assert.equal(evaluate("splitCycleHeatReadings(rows,'value')").length,2,'invalid live values are not connected');
context.rows=[{h_of_day_frac:1,power_w:10},{h_of_day_frac:2,power_w:20,live:true}];
assert.equal(evaluate('splitBoilerPowerSegments(rows)').length,1);
context.data = {
    cycle_1_water_temps:[{h_of_day_frac:1,water_temp:60,return_temp:40},{h_of_day_frac:2,water_temp:64,return_temp:44,live:true}],
    cycle_2_water_temps:[{h_of_day_frac:1,water_temp:50,return_temp:30},{h_of_day_frac:2,water_temp:54,return_temp:34,live:true}]
};
assert.equal(evaluate('boilerAverageWaterTemperatures(data,[1,2]).at(-1).live'),true,'averaging must preserve the live endpoint identity');
assert.equal(evaluate("splitCycleHeatReadings(boilerAverageWaterTemperatures(data,[1,2]),'water_temp').length"),1);
assert.equal(evaluate("splitCycleHeatReadings(boilerAverageWaterTemperatures(data,[1,2]),'return_temp').length"),1);
context.data.cycle_2_water_temps.at(-1).live=false;
assert.equal(evaluate('boilerAverageWaterTemperatures(data,[1,2]).at(-1).live ?? false'),false,'mixed archived/live averages do not get an unrestricted live bridge');
context.rows=[{h_of_day_frac:1,probes:{a:30,b:40}},{h_of_day_frac:2,probes:{a:40,b:50},live:true}];
assert.equal(evaluate("radiatorSeries(rows,'probes',['a','b']).at(-1).live"),true);
assert.equal(evaluate("splitRoomMetricReadings(radiatorSeries(rows,'probes',['a','b']),'value',.05).length"),1);
context.rows.at(-1).probes.b=null;
assert.equal(evaluate("radiatorSeries(rows,'probes',['a','b']).at(-1).live ?? false"),false,'missing probe cannot be certified live');
const source=fs.readFileSync('docs/data.js','utf8');
vm.runInContext(source.slice(source.indexOf('const ROOM_TEMPERATURE_DISPLAY_STEP_HOURS'),source.indexOf('function drawPlot(')),context);
context.rows=[{h_of_day_frac:1,temp:20},{h_of_day_frac:4,temp:21,live:true}];
assert.equal(evaluate('prepareRoomTemperatureForDisplay(rows).at(-1).live'),true,'room display resampling preserves the live identity');
assert.equal(evaluate("splitRoomMetricReadings(prepareRoomTemperatureForDisplay(rows),'temp',2).length"),1);
console.log('Live curve connections passed: long upload lag, archived gaps, invalid readings, immutable segments, boiler means, radiator means and plug curves.');
