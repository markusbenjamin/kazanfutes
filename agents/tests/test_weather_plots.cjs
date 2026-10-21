const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const calls = [], requests = [];
const context = vm.createContext({Number, Math, Date, Object,
    dayStamp: () => '2026-10-21', mainGraphSetting: {}, mainGraphContentLocked: false,
    elementToMainGraphSettingMapping: {external_thermometer: {title: 'external_temp', day: '2026-10-21'}},
    drawMainGraph: data => requests.push(data),
    drawPlot: (data, options) => { calls.push({data, options}); return {plotElement: 'plot', plotDims: {w: 200, h: 100}}; }
});
for (const file of ['cycle_heat_plots.js', 'room_metric_plots.js', 'weather_plots.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, 'docs', file), 'utf8'), context);
}
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code, context)));
assert.equal(evaluate("selectorWeekday('2026-10-21', true)"), 'szerdai');
assert.equal(evaluate("selectorWeekday('2026-10-22', true)"), 'csütörtöki');
assert.equal(evaluate("shiftedSelectorDay('2026-10-25', 1)"), '2026-10-26');
assert.equal(evaluate("shiftedSelectorDay('2026-01-01', -1)"), '2025-12-31');
assert.equal(evaluate("shiftedSelectorDay('2024-02-28', 1)"), '2024-02-29');
context.event = {ctrlKey: false, preventDefault() {}};
assert.equal(evaluate("openWeatherMetricPlot(event, 'external_thermometer')"), false);
context.event.ctrlKey = true;
assert.equal(evaluate("openWeatherMetricPlot(event, 'cycle1')"), false);
assert.equal(evaluate("openWeatherMetricPlot(event, 'external_thermometer')"), true);
assert.equal(context.mainGraphSetting.title, 'weather_metrics');
assert.equal(context.mainGraphContentLocked, true);
assert.equal(context.elementToMainGraphSettingMapping.external_thermometer.title, 'external_temp');
const initial = context.mainGraphSetting;
vm.runInContext("selectWeatherMetricPlot('humidity')", context);
assert.notEqual(context.mainGraphSetting, initial);
assert.equal(context.mainGraphSetting.metric, 'humidity');
vm.runInContext('navigateSelectorPlotDay(-1)', context);
assert.equal(context.mainGraphSetting.day, '2026-10-20');
assert.equal(context.mainGraphSetting.metric, 'humidity');
vm.runInContext('navigateSelectorPlotDay(1)', context);
const today = context.mainGraphSetting, count = requests.length;
vm.runInContext('navigateSelectorPlotDay(1)', context);
assert.equal(context.mainGraphSetting, today);
assert.equal(requests.length, count);
context.mainGraphSetting = {title: 'room_metrics', day: '2026-10-21', roomNumToPlot: 7, metric: 'co2'};
vm.runInContext('navigateSelectorPlotDay(-1)', context);
assert.equal(context.mainGraphSetting.roomNumToPlot, 7);
assert.equal(context.mainGraphSetting.metric, 'co2');
assert.equal(context.mainGraphSetting.day, '2026-10-20');
context.mainGraphSetting = {title: 'cycle_water_temp', day: '2026-10-21', cycleNum: 2, detailed: true, metric: 'pump'};
vm.runInContext('navigateSelectorPlotDay(-1)', context);
assert.equal(context.mainGraphSetting.metric, 'pump');
assert.equal(context.mainGraphSetting.cycleNum, 2);
context.mainGraphSetting.detailed = false;
const ordinary = context.mainGraphSetting;
vm.runInContext('navigateSelectorPlotDay(-1)', context);
assert.equal(context.mainGraphSetting, ordinary);
context.wind = [{wind_direction_deg: 355, wind_speed_m_s: 1}, {wind_direction_deg: 5, wind_speed_m_s: 2},
    {wind_direction_deg: 90, wind_speed_m_s: 3}, {wind_direction_deg: 270, wind_speed_m_s: 0},
    {wind_direction_deg: null, wind_speed_m_s: 1}];
const bins = evaluate('windDirectionHistogram(wind)');
assert.equal(bins.length, 16);
assert.equal(bins[0].count, 2);
assert.equal(bins[4].count, 1);
assert.equal(bins.reduce((sum, bin) => sum+bin.count, 0), 3);
assert.equal(evaluate('Object.keys(WEATHER_PLOT_METRICS).some(key => key.includes("battery"))'), false);
context.setting = {title: 'weather_metrics', day: '2026-10-20', metric: 'temperature'};
context.data = {weather_station: [{h_of_day_frac: 1, temperature_c: -2}, {h_of_day_frac: 1.01, temperature_c: 0}]};
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.equal(calls[0].options.plotLabelTabs.day, '2026-10-20');
assert.equal(calls[0].options.plotLabelTabs.choices.length, 11);
assert.equal(calls[1].data[0].temperature_c, -2);
assert.equal(calls[1].options.curveEndText.text, '0 °C');
let histogram;
context.drawWindDirectionHistogram = (element, dims, readings) => { histogram = {element, dims, readings}; };
context.setting.metric = 'direction';
calls.length = 0;
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.equal(calls.length, 1);
assert.equal(calls[0].options.axes.left, false);
assert.equal(histogram.element, 'plot');
assert.equal(histogram.dims.w, 200);
const weatherSource = fs.readFileSync(path.join(root, 'docs/weather_plots.js'), 'utf8');
assert.match(weatherSource, /translate\(\$\{plotDims.w \/ 2\},\$\{plotDims.h \/ 2\}\)/);
console.log('Weather/selectors passed: unchanged outdoor hover, Ctrl selector, metric/date preservation, future-day guard, calendar/DST dates, weekday labels, weather values/units, centered wind histogram, no batteries.');
