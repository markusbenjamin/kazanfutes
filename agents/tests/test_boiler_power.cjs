const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const calls = [];
const styles = [];
const context = require('./dashboard_test_context.cjs')({
    Date, Number, Math,
    dateFromTimestamp: stamp => new Date(stamp.replace(/^(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})$/, '$1-$2-$3T$4:$5:$6')),
    dayStamp: () => '2026-10-19', dayDataNotAvailable: false, dataWaitTime: 10,
    d3: { select: selector => ({ empty: () => true, style(name, value) { styles.push([selector, name, value]); return this; } }), max: (rows, fn) => Math.max(...rows.map(fn)),
        selectAll: selector => ({ style(name, value) { styles.push([selector, name, value]); return this; } }),
        range: (start, end, step) => Array.from({ length: Math.ceil((end-start)/step) }, (_, i) => start+i*step) },
    getBBoxDrawingDimensions: () => { throw new Error('Missing SVG must not be accessed'); },
    drawPlot: (data, options) => calls.push({ data, options }),
});
vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../docs/boiler_power.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../docs/boiler_demand_bars.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../docs/plot_history.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../docs/cycle_heat_plots.js'), 'utf8'), context);
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code, context)));
assert.equal(evaluate("freshBoilerPower({reachable:true,power_w:0,timestamp:'2026-10-19-12-00-00'},new Date('2026-10-19T12:01:00'))"), 0);
for (const reading of ["{reachable:false,power_w:100}", "{reachable:true,power_w:100}",
    "{reachable:true,power_w:null,timestamp:'2026-10-19-12-00-00'}", "{reachable:true,power_w:100,timestamp:'2026-10-19-11-00-00'}"]) {
    assert.equal(evaluate(`freshBoilerPower(${reading},new Date('2026-10-19T12:01:00'))`), null);
}
vm.runInContext('initializeBoilerPowerMarkers(); updateBoilerPowerMarkers({});', context);
assert.deepEqual(styles, [['#boiler_cord, #boiler_cord *', 'stroke', '#00cc00'], ['#boiler_cord, #boiler_cord *', 'stroke-opacity', '1']]);
const mapping = evaluate('var mapping = {}; registerBoilerPowerPlots(mapping); mapping');
assert.deepEqual(mapping.boiler1_marker.types, ['boiler_1_plug_power', 'boiler_commands']);
assert.deepEqual(mapping.boiler2_marker.types, ['boiler_2_plug_power', 'boiler_commands']);
assert.deepEqual(evaluate(`splitBoilerPowerSegments([
    {h_of_day_frac:1,power_w:0},{h_of_day_frac:1.01,power_w:100},
    {h_of_day_frac:1.02,power_w:null},{h_of_day_frac:1.03,power_w:50},
    {h_of_day_frac:2,power_w:60}]).map(segment=>segment.map(row=>row.power_w))`), [[0,100],[50,60]]);
const periods = evaluate(`boilerCommandPeriods([{h_of_day_frac:0,command_on:1},{h_of_day_frac:2,command_on:0},{h_of_day_frac:3,command_on:1},{h_of_day_frac:4,command_on:1}],0,200)`);
assert.deepEqual(periods.map(row => [row.x1,row.x2]), [[0,2],[3,4]]);
vm.runInContext("drawBoilerPowerPlot({boiler_1_plug_power:[],boiler_commands:[]},mapping.boiler1_marker)", context);
assert.equal(calls.length, 1);
assert.equal(calls[0].options.plotLabel, '1. kazán mai villamos teljesítménye');
assert.equal(calls[0].data.length, 0);
calls.length = 0;
vm.runInContext(`drawBoilerPowerPlot({boiler_1_plug_power:[{h_of_day_frac:1,power_w:0}],boiler_2_plug_power:[{h_of_day_frac:1,power_w:999}],boiler_commands:[]},mapping.boiler1_marker)`, context);
assert.equal(calls.length, 2);
assert.equal(calls[1].data[0].power_w, 0);
calls.length=0;
vm.runInContext(`drawBoilerPowerPlot({boiler_1_plug_power:[{h_of_day_frac:1,power_w:0},
 {h_of_day_frac:2,power_w:150},{h_of_day_frac:3,power_w:0}],
 boiler_commands:[{h_of_day_frac:1,command_on:1},{h_of_day_frac:3,command_on:0}]},mapping.boiler1_marker)`,context);
const boiler=calls.slice();calls.length=0;
context.getFractionalHourOfDay=()=>24;
context.extractCyclePumpOnPeriods=()=>[{x1:1,x2:3}];
vm.runInContext(`drawCycleHeatPlot({pumps_power:[{h_of_day_frac:1,pump_1_power:0},
 {h_of_day_frac:2,pump_1_power:150},{h_of_day_frac:3,pump_1_power:0}],heating_state:[]},
 {cycleNum:1,metric:'pump',day:'2026-10-19',detailed:true})`,context);
for (const key of ['margins','domain','tickVals','plotStyle','segment'])
    assert.deepEqual(JSON.parse(JSON.stringify(boiler[0].options[key])),
        JSON.parse(JSON.stringify(key === 'plotStyle' ? {...calls[0].options[key],thickness:'.5'} : calls[0].options[key])),
        'Boiler shares pump styling, with its requested thinner curve: '+key);
assert.deepEqual(JSON.parse(JSON.stringify(boiler[0].options.rects)),JSON.parse(JSON.stringify(calls[0].options.rects)),
    'Command and circulation shading match');
assert.deepEqual(boiler[1].options.curveEndText,calls[1].options.curveEndText,'Endpoint text styling matches');
assert.equal(boiler[1].options.plotStyle.col,'rgb(0, 0, 0)');
assert.equal(boiler[1].options.plotStyle.stepAfter,true,'Power changes stay rectangular');
console.log('Boiler power hooks passed: absent SVG, stale/missing readings, real zero, per-plug selection, gap handling, command overlay.');
