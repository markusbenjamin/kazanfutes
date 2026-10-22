const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'docs/data.js'), 'utf8');
const calls = [], requests = [];
const ordinary = { title: 'room_plot', roomNumToPlot: 1, day: '2026-10-21', types: ['old_room_data'] };
const context = vm.createContext({
    Number, Math, Date, Object, mainGraphSetting: {}, mainGraphContentLocked: false,
    elementToMainGraphSettingMapping: { Oktopusz: ordinary, cycle1: { title: 'cycle_water_temp' } },
    roomsDataAndState: { 1: { name: 'Oktopusz szita' }, 2: { name: 'Gólyafészek' } },
    dayStamp: () => '2026-10-21', getFractionalHourOfDay: () => 12,
    drawPlot: (data, options) => calls.push({data, options}),
    drawMainGraph: data => requests.push(data)
});
vm.runInContext(fs.readFileSync(path.join(root, 'docs/room_metric_plots.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(root, 'docs/cycle_heat_plots.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(root, 'docs/radiator_plots.js'), 'utf8'), context);
vm.runInContext(source.slice(source.indexOf('const ROOM_TEMPERATURE_DISPLAY_STEP_HOURS'), source.indexOf('function drawPlot(')), context);
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code, context)));
context.prevented = 0;
context.event = { ctrlKey: false, preventDefault: () => context.prevented++ };
assert.equal(evaluate("openRoomMetricPlot(event, 'Oktopusz')"), false);
assert.equal(requests.length, 0);
assert.equal(context.mainGraphContentLocked, false);
context.event.ctrlKey = true;
assert.equal(evaluate("openRoomMetricPlot(event, 'cycle1')"), false);
assert.equal(evaluate("openRoomMetricPlot(event, 'Oktopusz')"), true);
assert.equal(context.mainGraphSetting.title, 'room_metrics');
assert.equal(context.mainGraphContentLocked, true);
assert.equal(context.prevented, 1);
assert.deepEqual(evaluate('mainGraphSetting.types'), ['room_1_measurements']);
assert.equal(context.elementToMainGraphSettingMapping.Oktopusz, ordinary);
const initial = context.mainGraphSetting;
vm.runInContext("selectRoomMetricPlot('co2')", context);
assert.notEqual(context.mainGraphSetting, initial);
assert.equal(initial.metric, 'temperature');
assert.deepEqual(evaluate('mainGraphSetting.types'), ['room_1_environment']);
assert.equal(context.mainGraphSetting.metric, 'co2');
assert.equal(context.mainGraphContentLocked, true);
assert.equal(context.elementToMainGraphSettingMapping.Oktopusz, ordinary);
context.mainGraphSetting = ordinary;
assert.equal(evaluate("openRoomMetricPlot(event, 'Oktopusz')"), true);
assert.equal(context.mainGraphSetting.metric, 'co2');
assert.equal(evaluate("createRoomMetricPlotSetting({roomNumToPlot: 2, day: '2026-10-21'}, 'Gólyafészek').metric"), 'temperature');
const originalRequests = requests.length;
vm.runInContext("selectRoomMetricPlot('invalid')", context);
assert.equal(requests.length, originalRequests);
context.rows = [{h_of_day_frac: 1, co2: 500}, {h_of_day_frac: 1.01, occupancy: 0},
    {h_of_day_frac: 1.02, co2: null}, {h_of_day_frac: 1.03, co2: 600}, {h_of_day_frac: 2, co2: 700}];
assert.deepEqual(evaluate("splitRoomMetricReadings(rows, 'co2', .25).map(s => s.map(r => r.co2))"), [[500],[600],[700]]);
for (const [metric, key, value, unit] of [
    ['temperature','temp',21.3,'°C'], ['humidity','hum',55,'%'],
    ['co2','co2',650,'ppm'], ['lux','lux',0,'lux'], ['occupancy','occupancy_average',0,'%']
]) {
    calls.length = 0;
    context.setting = {roomNumToPlot: 1, metric, day: '2026-10-21'};
    const type = 'room_1_' + (metric === 'temperature' || metric === 'humidity' ? 'measurements' : 'environment');
    context.data = {[type]: [{h_of_day_frac: 1, [key]: value}]};
    vm.runInContext('drawRoomMetricPlot(data, setting)', context);
    assert.equal(calls.length, 2);
    assert.equal(calls[0].options.dataKeys.left, key);
    assert.equal(calls[0].options.plotLabelTabs.choices.length, 6);
    assert.equal(calls[0].options.margins.top, .1); // No empty row reserved for the old date line.
    assert.equal(calls[0].options.now.show, metric === 'occupancy');
    if (metric === 'occupancy') {
        assert.equal(calls[0].options.now.pos, 12);
        assert.equal(calls[0].options.now.color, 'rgba(230,130,160,0.45)');
    }
    assert.equal(calls[1].options.showLockLabel, false);
    assert.equal(calls[1].data[0][key], value);
    assert.equal(calls[1].options.plotStyle.monotone, metric !== 'temperature');
    assert.equal(calls[1].options.plotStyle.smoothCurve, metric === 'temperature');
    assert.equal(calls[1].options.smoothing.left, metric === 'temperature' ? 10 : 0);
    assert.equal(calls[1].options.plotStyle.thickness, '2');
    assert.equal(calls[1].options.curveEndText.text, value+' '+unit);
    assert.deepEqual(JSON.parse(JSON.stringify(calls[0].options.plotLabelTabs.choices.map(c => c.label))), ['hőm.', 'páratart.', 'CO₂', 'lux', 'jelenl.', 'radiátor hőm.']);
}
assert.equal(evaluate('ROOM_PLOT_METRICS.temperature.color'), 'rgba(255,0,0,1)');
assert.equal(evaluate('ROOM_PLOT_METRICS.humidity.color'), 'rgb(100, 180, 255)');
assert.equal(evaluate('ROOM_PLOT_METRICS.co2.color'), 'rgb(80, 170, 0)');
assert.equal(evaluate('ROOM_PLOT_METRICS.lux.color'), 'rgb(190, 155, 0)');
assert.equal(evaluate('ROOM_PLOT_METRICS.occupancy.color'), 'rgb(0, 0, 0)');
context.observations = [{h_of_day_frac: 0, occupancy: 1}, {h_of_day_frac: .1, occupancy: 0},
    {h_of_day_frac: 2, occupancy: 1}, {h_of_day_frac: 2.1, occupancy: null},
    {h_of_day_frac: 3, occupancy: 1}, {h_of_day_frac: 4, occupancy: 1}, {h_of_day_frac: 5, occupancy: 1}];
assert.deepEqual(evaluate('extractRoomOccupancyPeriods(observations, 4.1)'),
    [{x1: 0, x2: .1}, {x1: 2, x2: 2.1}, {x1: 3, x2: 3.25}, {x1: 4, x2: 4.1}]);
assert.deepEqual(evaluate('extractRoomOccupancyPeriods([], 12)'), []);
context.setting.metric = 'occupancy';
context.data = {room_1_environment: [{h_of_day_frac: 0, occupancy_average: .25},
    {h_of_day_frac: .5, occupancy_average: .5}, ...context.observations]};
calls.length = 0;
vm.runInContext('drawRoomMetricPlot(data, setting)', context);
assert.deepEqual(JSON.parse(JSON.stringify(calls[1].data.map(r => r.occupancy_average))), [25,50]);
assert.deepEqual(JSON.parse(JSON.stringify(calls[0].options.domain.left)), [0,100]);
assert.equal(calls[0].options.rects.list[0].fill, 'rgba(180,180,180,0.3)');
assert.equal(calls[0].options.rects.list[0].y2, 100);
assert.equal(calls[1].options.plotStyle.col, 'rgb(0, 0, 0)');
assert.equal(calls[1].options.curveEndText.show, false);
assert.equal(calls[0].options.axesLabel.left, 'átlagos szerdai jelenlét (%)');
assert.equal(calls[0].options.plotLabelTabs.day, '2026-10-21');
calls.length = 0;
context.data = {};
vm.runInContext('drawRoomMetricPlot(data, setting)', context);
assert.equal(calls.length, 1); // Empty/missing streams still offer the selector.
assert.equal(calls[0].options.curveEndText.show, false);
assert.equal(calls[0].options.emptyMessage, 'Átlagos jelenlét nem elérhető.');
context.setting.metric = 'temperature';
context.data = {room_1_environment: [{h_of_day_frac: 1, temp: 99}],
    room_1_measurements: [{h_of_day_frac: 1, temp: 21.5}, {h_of_day_frac: 2, temp: 20.5}]};
calls.length = 0;
vm.runInContext('drawRoomMetricPlot(data, setting)', context);
assert.deepEqual(JSON.parse(JSON.stringify(calls[1].data)), evaluate('prepareRoomTemperatureForDisplay(data.room_1_measurements)'));
assert.equal(calls[1].data[0].temp, 21.5); // Only the existing room-temperature series is used.
assert.equal(calls[1].options.smoothing.left, 10);
assert.equal(calls[1].options.plotStyle.smoothCurve, true);
assert.equal(calls[1].options.plotStyle.monotone, false);
assert.equal(calls[1].options.curveTooltip, 'mért hőmérséklet');
context.probeMapping=JSON.parse(fs.readFileSync(path.join(root,'system/radiator_mapping.json'),'utf8'));
vm.runInContext('radiatorUnitMapping=probeMapping',context);
assert.equal(evaluate('roomRadiatorSources(2)').length,4);
assert.deepEqual(evaluate('roomRadiatorSources(5)'),['merce_radiatorok_2_shelly/temperature:101','merce_radiatorok_2_shelly/temperature:102']);
assert.deepEqual(evaluate('roomRadiatorSources(12)'),['merce_radiatorok_2_shelly/temperature:100']);
assert.deepEqual(evaluate('roomRadiatorSources(8)'),[]);
assert.equal(evaluate('roomRadiatorSources(18)').length,1); // Unit ownership includes its legacy area aliases.
context.mainGraphSetting={title:'room_metrics',roomNumToPlot:2,sourceElementId:'Gólyafészek',day:'2026-10-20',metric:'temperature'};
vm.runInContext("selectRoomMetricPlot('radiators')",context);
assert.deepEqual(evaluate('mainGraphSetting.types'),['radiator_temps']);
assert.equal(context.mainGraphSetting.day,'2026-10-20');
assert.equal(context.mainGraphContentLocked,true);
context.setting=context.mainGraphSetting;
context.data={radiator_temps:[{h_of_day_frac:1,probes:{
    'ovi_radiatorok_shelly/temperature:100':20,'ovi_radiatorok_shelly/temperature:101':30,
    'ovi_radiatorok_shelly/temperature:102':40,'ovi_radiatorok_shelly/temperature:103':50,
    'merce_radiatorok_2_shelly/temperature:101':99}}]};
calls.length=0;
vm.runInContext('drawRoomMetricPlot(data,setting)',context);
assert.equal(calls.length,5);
assert.equal(calls[0].options.axesLabel.left,'°C');
assert.equal(calls[0].options.plotLabelTabs.selected,'radiators');
assert.equal(calls[0].options.plotLabelTabs.day,'2026-10-20');
assert.equal(calls[0].options.plotLabelTabs.prefix,'Gólyafészek — ');
assert.equal(calls[0].options.plotLabelTabs.choices.length,6);
assert.deepEqual(calls.slice(1).map(call=>call.data[0].value),[20,30,40,50]);
assert.equal(new Set(calls.slice(1).map(call=>call.options.plotStyle.col)).size,4);
assert.deepEqual(calls.slice(1).map(call=>call.options.curveTooltip),[100,101,102,103].map(probe=>'ovi_radiatorok_shelly/temperature:'+probe));
assert.ok(calls.slice(1).every(call=>call.options.plotStyle.endCap));
calls.length=0;
context.data={};
vm.runInContext('drawRoomMetricPlot(data,setting)',context);
assert.equal(calls.length,1);
assert.equal(calls[0].options.emptyMessage,'Az adott napra nincs adat.');
context.roomsDataAndState[8]={name:'Kisterem'};
context.setting={...context.setting,roomNumToPlot:8};
calls.length=0;
vm.runInContext('drawRoomMetricPlot(data,setting)',context);
assert.equal(calls.length,1);
assert.equal(calls[0].options.emptyMessage,'A szobához nincs radiátor-hőmérő rendelve.');
assert.equal(calls[0].options.plotLabelTabs.choices.length,6);
const tooltip = {
    attrs: {}, styles: {}, label: '', interrupt() { return this; },
    attr(name, value) { if (arguments.length === 1) return this.attrs[name]; this.attrs[name] = value; return this; },
    style(name, value) { this.styles[name] = value; return this; },
    text(value) { this.label = value; return this; },
    node() { return {getBoundingClientRect: () => ({width: 180, height: 24})}; }
};
const curveEvents = {};
context.curve = {attr() { return this; }, style() { return this; }, clone() { return this; },
    node() { return {getScreenCTM: () => ({a: 2, b: 0})}; },
    on(event, handler) { curveEvents[event] = handler; return this; }};
context.d3 = {select: () => tooltip};
context.window = {scrollX: 0, scrollY: 0, innerWidth: 706, innerHeight: 715};
vm.runInContext("bindPlotCurveTooltip(curve, 'radiátor nyitási százalék')", context);
curveEvents['mouseover.curve-tooltip']({pageX: 700, pageY: 710});
assert.equal(tooltip.label, 'radiátor nyitási százalék');
assert.equal(tooltip.styles.visibility, 'visible');
assert.equal(tooltip.styles['font-size'], '14px'); // Same seven SVG units as the plot label, at its actual zoom.
assert.equal(tooltip.styles.left, '522px'); // Tooltip stays inside the viewport.
assert.equal(tooltip.styles.top, '687px');
curveEvents['mousemove.curve-tooltip']({pageX: 100, pageY: 100});
assert.equal(tooltip.styles.left, '110px');
curveEvents['mouseout.curve-tooltip']();
assert.equal(tooltip.styles.visibility, 'hidden');
assert.equal(tooltip.attrs['data-curve-tooltip'], null);
assert.equal(tooltip.styles['font-size'], null); // Ordinary room-info tooltips retain their existing CSS size.
curveEvents['mouseover.curve-tooltip']({pageX: 100, pageY: 100});
vm.runInContext('hidePlotCurveTooltip()', context);
assert.equal(tooltip.styles.visibility, 'hidden');
const ordinaryRoomSource = source.slice(source.indexOf('case "room_plot":'), source.indexOf('case "all_rooms":'));
assert.match(ordinaryRoomSource, /curveTooltip: "mért hőmérséklet"/);
assert.match(ordinaryRoomSource, /curveTooltip: "kért hőmérséklet"/);
assert.match(ordinaryRoomSource, /curveTooltip: "radiátor nyitási százalék"/);
assert.match(source, /if \(ops.curveTooltip\) bindPlotCurveTooltip\(curve, ops.curveTooltip, isMobile \? 7 \* mobileViewScaler : 7\)/);
assert.match(source, /function clearMainGraphs\(\) \{\s*hidePlotCurveTooltip\(\)/);
const click = source.slice(source.indexOf('.on("click.maingraph"'), source.indexOf('d3.select("body")', source.indexOf('.on("click.maingraph"')));
assert.match(click, /event.stopPropagation\(\);\s*if \(openRoomControlPlot\(event, this.id\)\) return;\s*if \(openWeatherMetricPlot\(event, this.id\)\) return;\s*if \(openCycleHeatPlot\(event, this.id\)\) return;\s*if \(openRoomMetricPlot\(event, this.id\)\) return;/);
const hover = source.slice(source.indexOf('function joinMainGrapDataSourceToElements'), source.indexOf('.on("click.maingraph"'));
assert.match(hover, /mainGraphSetting = elementToMainGraphSettingMapping\[this.id\]/);
assert.doesNotMatch(hover, /room_metrics|roomMetricSelections/);
assert.match(source, /case "room_metrics":\s*drawRoomMetricPlot\(graphData, mainGraphSetting\)/);
assert.match(source, /ops.plotStyle.stepAfter \? d3.curveStepAfter/);
assert.match(source, /ops.plotStyle.monotone \? d3.curveMonotoneX/);
assert.match(source, /period.fill = "rgba\(255,0,0,0\.08\)";/); // Room heating periods remain visible without borders.
assert.match(source, /Keringetett körök: /);
assert.doesNotMatch(source, /Bekapcsolt körök:/);
console.log('Room metric plots passed: unchanged hover, same temperature series and smoothing as main plot, labels/colors, selector/pinning, learned occupancy and gray actual periods.');
