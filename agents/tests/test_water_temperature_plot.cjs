const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../docs/data.js'), 'utf8').replace(/\r\n/g, '\n');
const helper = source.slice(source.indexOf('function extractCyclePumpOnPeriods('), source.indexOf('function extractRoomScheduleFromCondensedSchedule('));
const mapping = source.slice(source.indexOf('for (let cycle = 1; cycle <= 4; cycle++) {\n    const waterTemperatureSetting'), source.indexOf('registerBoilerPowerPlots(elementToMainGraphSettingMapping);'));
const plotCase = source.match(/case "cycle_water_temp": \{([\s\S]*?)\n\s*break;\n\s*\}/)[1];
const calls = [];
const context = vm.createContext({
    Number, Math, Date, range: null, mainGraphSetting: {}, graphData: {},
    elementToMainGraphSettingMapping: {}, dayStamp: () => '2026-10-21',
    dayDataNotAvailable: false, dataWaitTime: 10, getFractionalHourOfDay: () => 12,
    drawPlot: (data, options) => calls.push({data, options}),
    d3: { extent: (rows, accessor) => {
        const values = rows.map(accessor); return [Math.min(...values), Math.max(...values)];
    }, range: (start, end, step) => Array.from({length: Math.ceil((end-start)/step)}, (_, i) => start+i*step) },
});
vm.runInContext(helper + mapping, context);
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code, context)));
for (let cycle = 1; cycle <= 4; cycle++) {
    assert.deepEqual(evaluate(`elementToMainGraphSettingMapping.cycle${cycle}.types`), [`cycle_${cycle}_water_temps`, 'heating_state']);
}
assert.equal(evaluate('elementToMainGraphSettingMapping.cycle1 === elementToMainGraphSettingMapping.cycle1_2'), true);
function intervals(cycle, samples, end=12) {
    context.samples = samples;
    return evaluate(`extractCyclePumpOnPeriods(${cycle}, samples, ${end})`);
}
const samples = [
    {h_of_day_frac: 0, cycle_states: {1: 1, 2: 0, 3: 0, 4: 0}},
    {h_of_day_frac: 2, cycle_states: {1: 0, 2: 1, 3: 0, 4: 0}},
    {h_of_day_frac: 4, cycle_states: {1: 0, 2: 0, 3: 1, 4: 0}},
    {h_of_day_frac: 6, cycle_states: {1: 1, 2: 0, 3: 0, 4: 1}},
];
assert.deepEqual(intervals(1, samples), [{x1: 0, x2: 2}, {x1: 6, x2: 12}]);
assert.deepEqual(intervals(2, samples), [{x1: 2, x2: 4}]);
assert.deepEqual(intervals(3, samples), [{x1: 4, x2: 6}]);
assert.deepEqual(intervals(4, samples), [{x1: 6, x2: 12}]);
assert.deepEqual(intervals(1, [...samples].reverse()), intervals(1, samples));
assert.deepEqual(intervals(1, [{h_of_day_frac: 3, cycle_states: {1: 1}}]), [{x1: 3, x2: 12}]);
assert.deepEqual(intervals(1, [{h_of_day_frac: 3, cycle_states: {1: 1}}], 24), [{x1: 3, x2: 24}]);
assert.deepEqual(intervals(1, undefined), []);
assert.deepEqual(intervals(1, []), []);
assert.deepEqual(intervals(1, [{h_of_day_frac: 3, cycle_states: {2: 1}}]), []);
assert.deepEqual(intervals(1, [{h_of_day_frac: 13, cycle_states: {1: 1}}]), []);
function plot(cycle, data, day='2026-10-21') {
    calls.length = 0;
    context.mainGraphSetting = {cycleNum: cycle, day};
    context.graphData = data;
    vm.runInContext('{'+plotCase+'}', context);
    return calls[0];
}
for (let cycle = 1; cycle <= 4; cycle++) {
    const result = plot(cycle, {heating_state: samples, [`cycle_${cycle}_water_temps`]: [{water_temp: 61.2, h_of_day_frac: 1}]});
    const options = result.options;
    assert.equal(options.plotStyle.thickness, '1');
    assert.equal(options.rects.when, 'before');
    assert.deepEqual(JSON.parse(JSON.stringify(options.rects.list.map(({x1,x2}) => ({x1,x2})))), intervals(cycle, samples));
    options.rects.list.forEach(period => {
        assert.equal(period.y1, options.domain.left[0]);
        assert.equal(period.y2, options.domain.left[1]);
        assert.equal(period.fill, 'rgba(255,0,0,0.025)');
        assert.equal(period.dashed, true);
    });
}
const empty = plot(1, {});
assert.equal(empty.data.length, 0);
assert.equal(empty.options.rects.list.length, 0);
assert.equal(empty.options.curveEndText.show, false);
const historical = plot(4, {heating_state: samples}, '2026-10-20');
assert.equal(historical.options.rects.list[0].x2, 24);
console.log('Heating-water plots passed: per-cycle pump shading, initial/ongoing ON, historical days, missing data, thinner lines.');
