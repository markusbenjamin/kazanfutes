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
vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../docs/cycle_heat_plots.js'), 'utf8'), context);
vm.runInContext(helper + mapping, context);
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code, context)));
for (let cycle = 1; cycle <= 4; cycle++) {
    assert.deepEqual(evaluate(`elementToMainGraphSettingMapping.cycle${cycle}.types`), [`cycle_${cycle}_heat_delivery`, 'heating_state']);
    assert.equal(evaluate(`elementToMainGraphSettingMapping.cycle${cycle}.metric`), 'power');
    assert.equal(evaluate(`elementToMainGraphSettingMapping.cycle${cycle}_marker.metric`), 'power');
    assert.equal(evaluate(`elementToMainGraphSettingMapping.cycle${cycle}_marker.detailed`), false);
}
assert.equal(evaluate('elementToMainGraphSettingMapping.cycle1 === elementToMainGraphSettingMapping.cycle1_2'), false);
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
    context.mainGraphSetting = {cycleNum: cycle, day, metric: 'temperature', detailed: true};
    context.graphData = data;
    vm.runInContext('{'+plotCase+'}', context);
    return calls[0];
}
for (let cycle = 1; cycle <= 4; cycle++) {
    const result = plot(cycle, {heating_state: samples, [`cycle_${cycle}_water_temps`]: [{water_temp: 61.2, h_of_day_frac: 1}]});
    const options = result.options;
    assert.equal(options.plotStyle.thickness, '1');
    assert.equal(options.plotStyle.col, 'rgb(200, 0, 0)');
    assert.deepEqual(JSON.parse(JSON.stringify(options.plotLabelTabs.choices.map(choice => choice.label))),
        ['fűtővíz hőm.', 'fűtőtelj.', 'átfolyás', 'szivattyú telj.']);
    assert.equal(options.rects.when, 'before');
    assert.deepEqual(JSON.parse(JSON.stringify(options.rects.list.map(({x1,x2}) => ({x1,x2})))), intervals(cycle, samples));
    options.rects.list.forEach(period => {
        assert.equal(period.y1, options.domain.left[0]);
        assert.equal(period.y2, options.domain.left[1]);
        assert.equal(period.fill, 'rgba(255,0,0,0.025)');
        assert.equal(period.dashed, false);
        assert.equal(period.stroke, 'none');
        assert.equal(period.strokeWeight, 0);
    });
}
const empty = plot(1, {});
assert.equal(empty.data.length, 0);
assert.equal(empty.options.rects.list.length, 0);
assert.equal(empty.options.curveEndText.show, false);
const historical = plot(4, {heating_state: samples}, '2026-10-20');
assert.equal(historical.options.rects.list[0].x2, 24);
const drawRequests = [];
context.drawMainGraph = data => drawRequests.push(data);
context.mainGraphContentLocked = false;
context.mainGraphSetting = vm.runInContext('elementToMainGraphSettingMapping.cycle1', context);
context.event = {ctrlKey: false, preventDefault: () => {}};
assert.equal(evaluate("openCycleHeatPlot(event, 'cycle1_marker')"), false);
context.event.ctrlKey = true;
assert.equal(evaluate("openCycleHeatPlot(event, 'cycle1_marker')"), true);
assert.equal(context.mainGraphSetting.detailed, true);
const oldSetting = context.mainGraphSetting;
vm.runInContext("selectCycleHeatPlot('flow')", context);
assert.notEqual(context.mainGraphSetting, oldSetting);
assert.equal(context.mainGraphSetting.metric, 'flow');
assert.equal(context.mainGraphContentLocked, true);
assert.deepEqual(evaluate('mainGraphSetting.types'), ['cycle_1_heat_delivery', 'heating_state']);
assert.equal(evaluate('elementToMainGraphSettingMapping.cycle1.metric'), 'power');
assert.equal(evaluate('elementToMainGraphSettingMapping.cycle1_2.metric'), 'power');
assert.equal(evaluate('elementToMainGraphSettingMapping.cycle2.metric'), 'power');
assert.equal(drawRequests.length, 4);
assert.equal(oldSetting.metric, 'power');
assert.equal(evaluate("openCycleHeatPlot(event, 'cycle1')"), true);
assert.equal(context.mainGraphSetting.metric, 'flow');
assert.equal(context.mainGraphSetting.detailed, true);
assert.equal(evaluate('elementToMainGraphSettingMapping.cycle1.detailed'), false);
const flowData = {cycle_2_heat_delivery: [{h_of_day_frac: 1, flow_m3h: 0}, {h_of_day_frac: 1.02, flow_m3h: 0.8}], heating_state: samples};
context.mainGraphSetting = {cycleNum: 2, day: '2026-10-21', metric: 'flow'};
calls.length = 0;
context.graphData = flowData;
vm.runInContext('drawCycleHeatPlot(graphData, mainGraphSetting)', context);
assert.equal(calls[0].options.dataKeys.left, 'flow_m3h');
assert.equal(calls[1].data[0].flow_m3h, 0);
assert.equal(calls[1].options.curveEndText.text, '0.8 m³/h');
assert.equal(calls[1].options.plotStyle.col, 'rgb(28, 3, 252)');
assert.equal(calls[1].options.curveEndText.col, 'rgb(28, 3, 252)');
context.mainGraphSetting.metric = 'power';
context.graphData = {cycle_2_heat_delivery: [{h_of_day_frac: 1, power_kw: 16.672}]};
calls.length = 0;
vm.runInContext('drawCycleHeatPlot(graphData, mainGraphSetting)', context);
assert.equal(calls[0].options.dataKeys.left, 'power_kw');
assert.equal(calls[0].options.axesLabel.left, 'fűtőteljesítmény (kW)');
assert.equal(calls[0].options.plotLabelTabs, false);
assert.equal(calls[0].options.plotLabel, '2. kör — fűtőteljesítmény');
assert.equal(calls[1].options.plotLabel, '');
assert.equal(calls[1].options.curveEndText.text, '16.67 kW');
assert.equal(calls[1].options.plotStyle.col, 'rgb(230, 130, 0)');
assert.equal(calls[1].options.curveEndText.col, 'rgb(230, 130, 0)');
context.mainGraphSetting.metric = 'pump';
context.mainGraphSetting.detailed = true;
context.graphData = {pumps_power: [{h_of_day_frac: 1, pump_1_power: 90, pump_2_power: 0},
    {h_of_day_frac: 1.1, pump_1_power: 100, pump_2_power: 35},
    {h_of_day_frac: 8, pump_1_power: 100, pump_2_power: 0}]};
calls.length = 0;
vm.runInContext('drawCycleHeatPlot(graphData, mainGraphSetting)', context);
assert.equal(calls[0].options.dataKeys.left, 'pump_2_power');
assert.equal(calls[1].options.curveEndText.text, '0 W');
assert.equal(calls[1].options.plotStyle.col, 'rgb(0, 0, 0)');
assert.equal(calls[1].data.length, 3); // Logging time gaps must not split the pump curve.
assert.equal(calls.length, 2);
assert.deepEqual(evaluate("createCycleHeatPlotSetting(2, 'cycle2_marker', 'pump').types"), ['pumps_power','heating_state']);
assert.equal(evaluate('formatCycleEnergyDisplay([]).text'), '—');
assert.equal(evaluate('formatCycleEnergyDisplay([{energy_kwh: null}]).text'), '—');
assert.equal(evaluate('formatCycleEnergyDisplay([{energy_kwh: 0}]).text'), '≈0');
assert.equal(evaluate('formatCycleEnergyDisplay([{energy_kwh: 12.34}]).text'), '≈12.3');
assert.match(evaluate('formatCycleEnergyDisplay([{energy_kwh: 12, energy_partial: true}]).description'), /Hiányos/);
const markerTexts = [];
const selection = () => ({
    attr() { return this; }, style() { return this; }, remove() { return this; },
    text(value) { this.value = value; markerTexts.push(value); return this; },
    append() { return selection(); }, node() { return {getComputedTextLength: () => 20}; }
});
context.d3.select = selection;
context.d3.selectAll = selection;
context.dashboardFont = 'Consolas';
context.getBBoxDrawingDimensions = () => ({x: 0, y: 0, width: 20, height: 5});
context.energyData = {'2026-10-21': {cycle_1_heat_delivery: [{energy_kwh: 12.34}],
    cycle_2_heat_delivery: [], cycle_3_heat_delivery: [{energy_kwh: 0}], cycle_4_heat_delivery: [{energy_kwh: 3.5}]}};
vm.runInContext('writeCycleEnergyToMarkers(energyData)', context);
assert.equal(markerTexts.filter(text => text === 'kWh').length, 4);
assert.ok(markerTexts.includes('≈12.3'));
assert.ok(markerTexts.includes('≈0'));
assert.ok(markerTexts.includes('—'));
assert.equal(markerTexts.includes(' W'), false);
let dialRequests;
context.collectDataFromGitHub = requests => { dialRequests = JSON.parse(JSON.stringify(requests)); };
vm.runInContext('writeCycleEnergyToMarkers()', context);
assert.deepEqual(dialRequests.map(request => request.type), [1,2,3,4].map(c => `cycle_${c}_heat_delivery`));
assert.match(source, /runOnceThenSetInterval\(writeCycleEnergyToMarkers, 10 \* 1000\)/);
assert.doesNotMatch(source, /runOnceThenSetInterval\(writePumpPowerToCycleMarkers/);
assert.doesNotMatch(source, /period\.dashed = true/);
context.gaps = [{h_of_day_frac: 1, flow_m3h: 0}, {h_of_day_frac: 1.01, flow_m3h: null},
    {h_of_day_frac: 1.02, flow_m3h: 1}, {h_of_day_frac: 2, flow_m3h: 2}];
assert.deepEqual(evaluate("splitCycleHeatReadings(gaps, 'flow_m3h').map(rows => rows.map(row => row.flow_m3h))"), [[0],[1],[2]]);
console.log('Cycle plots/dials passed: simple heat-power hover, Ctrl selector, per-cycle memory, pump watts, daily kWh displays, shading/thin lines, missing data/gaps.');
