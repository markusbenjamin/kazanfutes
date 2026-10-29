const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const calls = [], requests = [], rainNodes = [], rainTooltips = [];
let niceCalls = 0;
function plotSelection() {
    return {attrs:{},styles:{},append(tag){const node=plotSelection();node.tag=tag;rainNodes.push(node);return node;},
        attr(key,value){this.attrs[key]=value;return this;},style(key,value){this.styles[key]=value;return this;},
        text(value){this.value=value;return this;}};
}
function scaleLinear() {
    let domain=[0,1],range=[0,1];
    const scale=value=>range[0]+(value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
    scale.domain=value=>(domain=value,scale);scale.range=value=>(range=value,scale);
    scale.nice=()=>{niceCalls++;return scale;};return scale;
}
const context = vm.createContext({Number, Math, Date, Object,
    dashboardFont:'Consolas',d3:{scaleLinear},
    dayStamp: () => '2026-10-21', mainGraphSetting: {}, mainGraphContentLocked: false,
    elementToMainGraphSettingMapping: {external_thermometer: {title: 'external_temp', day: '2026-10-21'}},
    drawMainGraph: data => requests.push(data),
    drawPlot: (data, options) => { const area={plotElement:plotSelection(),plotDims:{w:200,h:100}}; calls.push({data,options,area}); return area; }
});
for (const file of ['cycle_heat_plots.js', 'room_metric_plots.js', 'weather_plots.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, 'docs', file), 'utf8'), context);
}
context.bindPlotCurveTooltip=(node,label)=>rainTooltips.push(label);
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
assert.equal(evaluate('windDirectionDisplayAngle(265)'), 0); // Building azimuth points straight up.
for (const [bearing, displayDegrees] of [[270,5], [0,95], [90,185], [180,275], [-95,0], [625,0]]) {
    assert.ok(Math.abs(evaluate(`windDirectionDisplayAngle(${bearing})`) - displayDegrees * Math.PI / 180) < 1e-12);
}
assert.deepEqual(evaluate('windDirectionLabelPosition(265, 40)'), {x:0,y:-46});
const westLabel = evaluate('windDirectionLabelPosition(270, 40)');
assert.ok(westLabel.x > 0 && westLabel.y < 0); // West is slightly clockwise of up, not falsely at the top.
assert.ok(Math.abs(westLabel.x - Math.sin(5 * Math.PI / 180) * 46) < 1e-12);
assert.equal(evaluate('Object.keys(WEATHER_PLOT_METRICS).some(key => key.includes("battery"))'), false);
context.setting = {title: 'weather_metrics', day: '2026-10-20', metric: 'temperature'};
context.data = {weather_station: [{h_of_day_frac: 1, temperature_c: -2}, {h_of_day_frac: 1.01, temperature_c: 0}]};
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.equal(calls[0].options.plotLabelTabs.day, '2026-10-20');
assert.equal(calls[0].options.plotLabelTabs.choices.length, 9);
assert.equal(calls[0].options.plotLabelTabs.columns, 3);
assert.equal(calls[0].options.plotLabelTabs.choices.some(choice => choice.key === 'dewpoint'), false);
assert.equal(calls[0].options.plotLabelTabs.choices.some(choice => choice.key === 'rainStatus'), false);
assert.equal(calls[0].options.margins.top, .24); // Three selector rows, without an extra date row.
assert.equal(calls[0].options.margins.left,.1);
assert.equal(calls[0].options.margins.right,.03);
assert.equal(calls[1].data[0].temperature_c, -2);
assert.equal(calls[1].options.curveEndText.text, '0 °C');
context.data = {weather_station: [{h_of_day_frac:1,temperature_c:5,dewpoint_c:-10},
    {h_of_day_frac:1.01,temperature_c:6,dewpoint_c:null},
    {h_of_day_frac:1.02,temperature_c:7,dewpoint_c:0}]};
calls.length = 0;
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.deepEqual(Array.from(calls[0].options.domain.left), [-11.7,8.7]); // Both curves share the complete range.
assert.equal(calls.length, 4); // Foundation, temperature, two independently split dew-point segments.
assert.equal(calls[1].options.curveTooltip, 'hőmérséklet');
assert.equal(calls[1].options.plotStyle.col, 'rgb(28, 3, 252)');
assert.equal(calls[2].options.curveTooltip, 'harmatpont');
assert.equal(calls[2].options.plotStyle.col, 'rgb(0, 130, 150)');
assert.equal(calls[2].options.dataKeys.left, 'dewpoint_c');
assert.equal(calls[3].options.curveEndText.text, '0 °C');
context.data = {weather_station: [{h_of_day_frac:1,temperature_c:null,dewpoint_c:-3}]};
calls.length = 0;
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.equal(calls.length, 2); // A missing temperature does not hide a valid dew point.
assert.equal(calls[1].options.dataKeys.left, 'dewpoint_c');
context.setting.metric = 'light';
context.data = {weather_station: [{h_of_day_frac: 1, illuminance_lux: 50000}, {h_of_day_frac: 1.01, illuminance_lux: 1250}]};
calls.length = 0;
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.equal(calls[0].options.axesLabel.left, 'klux');
assert.equal(calls[1].data[0].illuminance_lux, 50);
assert.equal(calls[1].options.curveEndText.text, '1.3 klux');
assert.equal(context.data.weather_station[0].illuminance_lux, 50000); // Conversion does not mutate cached lux observations.
context.setting.metric = 'rain';
context.data = {weather_station: [{h_of_day_frac: 0, precipitation_mm: null},
    {h_of_day_frac: 1.1, precipitation_mm: 125.5}, {h_of_day_frac: 1, precipitation_mm: 123},
    {h_of_day_frac: 1.2, precipitation_mm: null}, {h_of_day_frac: 1.3, precipitation_mm: 127}]};
const originalRain = JSON.stringify(context.data);
assert.deepEqual(evaluate('weatherDailyPrecipitation(data.weather_station).map(row => row.precipitation_mm)'), [null, 2.5, 0, null, 4]);
calls.length = 0;
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.equal(calls[0].options.axesLabel.left, 'mm/h');
assert.ok(Math.abs(calls[0].options.domain.left[1] - 27.5) < 1e-10);
assert.equal(calls.length,1,'rain draws one foundation and bars, not an overlaid curve');
const initialBars=rainNodes.filter(node=>node.attrs.class==='weather-rain-bar');
assert.equal(initialBars.length,2);
assert.equal(niceCalls,1,'bar heights use the same rounded scale domain as the shared plot axis');
assert.ok(initialBars.every(node=>Math.abs(node.attrs['data-rate']-25)<1e-10));
assert.ok(initialBars.every(node=>node.attrs.width>0&&node.attrs.height>0&&node.attrs.fill==='rgb(40, 80, 180)'));
assert.ok(initialBars.every(node=>node.attrs.stroke==='none'));
assert.equal(rainNodes.find(node=>node.attrs.class==='weather-rain-end-label').value,'25 mm/h');
assert.ok(rainTooltips.some(text=>text==='01:00–01:05\n25 mm/h'));
assert.equal(calls[0].options.plotLabelTabs.choices.find(choice => choice.key === 'rain').label, 'csapadék');
assert.equal(JSON.stringify(context.data), originalRain); // Cached cumulative observations stay untouched.
context.data = {weather_station: [{h_of_day_frac: 0, precipitation_mm: 200}, {h_of_day_frac: .1, precipitation_mm: 201}]};
assert.deepEqual(evaluate('weatherDailyPrecipitation(data.weather_station).map(row => row.precipitation_mm)'), [0, 1]); // Each selected day gets its own baseline.
assert.deepEqual(evaluate('weatherDailyPrecipitation([{h_of_day_frac:0,precipitation_mm:0},{h_of_day_frac:.1,precipitation_mm:2}]).map(row => row.precipitation_mm)'), [0, 2]);
assert.deepEqual(evaluate('weatherDailyPrecipitation([])'), []);
context.rateSamples = [{h_of_day_frac: .25, precipitation_mm: 11}, {h_of_day_frac: 0, precipitation_mm: 10},
    {h_of_day_frac: .5, precipitation_mm: 11}, {h_of_day_frac: .75, precipitation_mm: null},
    {h_of_day_frac: 1, precipitation_mm: 12}, {h_of_day_frac: 2, precipitation_mm: 15},
    {h_of_day_frac: 2.25, precipitation_mm: 0}, {h_of_day_frac: 2.5, precipitation_mm: .5}];
const rateSamples = evaluate('weatherPrecipitationRate(rateSamples)');
assert.deepEqual(rateSamples.map(row => row.h_of_day_frac), [0,.25,.5,.75,1,2,2.25,2.5]);
assert.deepEqual(rateSamples.filter(row => row.precipitation_rate_mm_h === null).map(row => row.h_of_day_frac), [0,.75,1,2,2.25]);
assert.ok(Math.abs(rateSamples[1].precipitation_rate_mm_h - 2) < 1e-10);
assert.equal(rateSamples[2].precipitation_rate_mm_h, 0);
assert.equal(rateSamples.at(-1).precipitation_rate_mm_h, 2); // A reset starts an independent segment.
context.barRates=[{h_of_day_frac:0,precipitation_rate_mm_h:null},{h_of_day_frac:.1,precipitation_rate_mm_h:6},
    {h_of_day_frac:.2,precipitation_rate_mm_h:12},{h_of_day_frac:.3,precipitation_rate_mm_h:null},
    {h_of_day_frac:1,precipitation_rate_mm_h:null},{h_of_day_frac:1.1,precipitation_rate_mm_h:0}];
const bars=evaluate('weatherPrecipitationBars(barRates)');
assert.equal(bars.length,5,'missing periods are absent while real zero rainfall remains a bar');
assert.ok(Math.abs(bars[1].value-10.8)<1e-10,'irregular observations are averaged by duration, not sample count');
assert.ok(Math.abs(bars[2].x2-.2)<1e-10,'last partial five-minute interval keeps its actual edge');
assert.ok(bars.filter(bar=>bar.x1>=1).every(bar=>bar.value===0));
assert.ok(bars.every(bar=>bar.x2<=.2||bar.x1>=1),'unknown and long gaps are not filled in');
assert.deepEqual(evaluate('weatherPrecipitationBars([])'),[]);
assert.deepEqual(evaluate('weatherPrecipitationBars([{h_of_day_frac:0,precipitation_rate_mm_h:null},{h_of_day_frac:1,precipitation_rate_mm_h:3}])'),[]);
assert.deepEqual(evaluate('weatherPrecipitationRate([])'), []);
assert.deepEqual(evaluate('weatherPrecipitationRate([{h_of_day_frac:0,precipitation_mm:0},{h_of_day_frac:0,precipitation_mm:1}]).map(row => row.precipitation_rate_mm_h)'), [null,null]);
// Gaussian smoothing gives a symmetric, nonnegative bell around an isolated rain interval.
context.gaussianRain = Array.from({length:81}, (_, index) => ({h_of_day_frac:index/60,
    precipitation_mm:index >= 40 ? 1 : 0}));
const gaussianRates = evaluate('weatherPrecipitationRate(gaussianRain)');
assert.ok(gaussianRates[39].precipitation_rate_mm_h > gaussianRates[35].precipitation_rate_mm_h);
assert.ok(gaussianRates[35].precipitation_rate_mm_h > gaussianRates[30].precipitation_rate_mm_h);
assert.ok(gaussianRates[39].precipitation_rate_mm_h < 10); // Raw one-minute spike is 60 mm/h.
for (let offset = 0; offset < 15; offset++) assert.ok(Math.abs(gaussianRates[39-offset].precipitation_rate_mm_h
    - gaussianRates[40+offset].precipitation_rate_mm_h) < 1e-10);
assert.ok(gaussianRates.every(row => row.precipitation_rate_mm_h === null || row.precipitation_rate_mm_h >= 0));
assert.equal(gaussianRates[20].precipitation_rate_mm_h, 0);
// Integrating over intervals gives the same result when an interval is subdivided.
context.coarseRain = [{h_of_day_frac:0,precipitation_mm:0},{h_of_day_frac:.1,precipitation_mm:1},
    {h_of_day_frac:.25,precipitation_mm:1},{h_of_day_frac:.3,precipitation_mm:1}];
context.fineRain = [context.coarseRain[0],{h_of_day_frac:.05,precipitation_mm:.5},...context.coarseRain.slice(1)];
assert.ok(Math.abs(evaluate('weatherPrecipitationRate(coarseRain).at(-1).precipitation_rate_mm_h')
    - evaluate('weatherPrecipitationRate(fineRain).at(-1).precipitation_rate_mm_h')) < 1e-10);
context.data = {weather_station: [{h_of_day_frac: 0, precipitation_mm: null}, {h_of_day_frac: .1}]};
calls.length = 0;
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.equal(calls.length, 1); // An unknown day does not manufacture a zero-rain curve.
for (const metric of ['wind', 'gust']) {
    context.setting.metric = metric;
    context.data = {weather_station: [{h_of_day_frac: 1, wind_speed_m_s: 1, gust_speed_m_s: 2},
        {h_of_day_frac: 1.01, wind_speed_m_s: 3, gust_speed_m_s: 4}]};
    calls.length = 0;
    vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
    assert.equal(calls[1].options.smoothing.left, 5);
    assert.equal(calls[1].options.plotStyle.smoothCurve, true);
    assert.equal(calls[1].options.plotStyle.monotone, false);
}
let histogram;
context.drawWindDirectionHistogram = (element, dims, readings) => { histogram = {element, dims, readings}; };
context.setting.metric = 'direction';
calls.length = 0;
vm.runInContext('drawWeatherMetricPlot(data, setting)', context);
assert.equal(calls.length, 1);
assert.equal(calls[0].options.axes.left, false);
const dialMargins=calls[0].options.margins;
assert.equal(dialMargins.left,dialMargins.right);
assert.equal(dialMargins.left+(1-dialMargins.left-dialMargins.right)/2,.5,'dial centre must match the entire frame centre');
assert.equal(dialMargins.left+dialMargins.right,.13,'preserve the dial width and radius');
assert.equal(dialMargins.top,.24);
assert.equal(dialMargins.bottom,.15);
assert.equal(histogram.element,calls[0].area.plotElement);
assert.equal(histogram.dims.w, 200);
const weatherSource = fs.readFileSync(path.join(root, 'docs/weather_plots.js'), 'utf8');
assert.match(weatherSource, /translate\(\$\{plotDims.w \/ 2\},\$\{plotDims.h \* \.62\}\)/);
assert.doesNotMatch(weatherSource, /megfigyelés/); // No sample-count footer on the wind dial.
context.rain=[{h_of_day_frac:1,rain_status:1},{h_of_day_frac:1.1,rain_status:1},
    {h_of_day_frac:1.2,rain_status:0},{h_of_day_frac:2,rain_status:1},{h_of_day_frac:2.1,rain_status:null},
    {h_of_day_frac:3,rain_status:1},{h_of_day_frac:4,rain_status:1}];
assert.deepEqual(evaluate('weatherRainPeriods(rain,4.1)'),[{x1:1,x2:1.2},{x1:2,x2:2.1},{x1:3,x2:3.25},{x1:4,x2:4.1}]);
const directionTabs=calls[0].options.plotLabelTabs;
context.setting.metric='rain';
context.data={weather_station:context.rain};
calls.length=0;
vm.runInContext('drawWeatherMetricPlot(data,setting)',context);
assert.equal(calls.length,1); // Rain signal can still shade a day without cumulative readings.
assert.equal(calls[0].options.axes.left,true);
assert.equal(calls[0].options.axes.bottom,true);
assert.equal(calls[0].options.rects.list.length,4);
assert.equal(calls[0].options.rects.list[0].stroke,'none');
assert.equal(calls[0].options.rects.list[0].fill,'rgba(60,100,180,0.05)');
assert.equal(calls[0].options.rects.list[0].y2,calls[0].options.domain.left[1]);
// Dates use fixed frame corners, independently of metric rows and weekday widths.
const headerNodes = [];
function headerSelection(tag = 'g') {
    const element = {tag, attrs: {}, append(child) { const next = headerSelection(child); headerNodes.push(next); return next; },
        attr(name, value) { this.attrs[name] = value; return this; }, style() { return this; },
        text() { return this; }, on() { return this; }, node() { return {getComputedTextLength: () => 20}; }};
    return element;
}
context.dashboardFont = 'Consolas';
context.headerRoot = headerSelection();
context.headerOptions = directionTabs;
vm.runInContext('drawPlotTitleSelector(headerRoot, {w:200,h:100}, headerOptions, 7)', context);
const metricHeaders = headerNodes.filter(node => node.attrs.class === 'cycle-heat-selector');
assert.equal(metricHeaders.length, 3);
assert.equal(headerNodes.some(node => node.attrs.class === 'selector-date-label'), false);
vm.runInContext('drawPlotDateNavigation(headerRoot, {w:200,h:100}, headerOptions, 7, true)', context);
const dateHeader = headerNodes.find(node => node.attrs.class === 'selector-date-label');
assert.equal(dateHeader.attrs.y, -7 * .7);
assert.equal(dateHeader.attrs.x, 7 * .75 + 20 + 7);
const arrowCoordinates = headerNodes.filter(node => node.attrs.role === 'button').map(node => node.attrs.x);
assert.deepEqual(arrowCoordinates, [5.25, 194.75]);
headerNodes.length = 0;
context.headerOptions = {...context.headerOptions, day: '2026-10-21'};
vm.runInContext('drawPlotDateNavigation(headerRoot, {w:200,h:100}, headerOptions, 7, true)', context);
assert.deepEqual(headerNodes.filter(node => node.attrs.role === 'button').map(node => node.attrs.x), arrowCoordinates);
assert.equal(headerNodes.some(node => node.attrs.class === 'selector-date-label'), false);
assert.equal(headerNodes.find(node => node.attrs['aria-label'] === 'Következő nap').attrs['aria-disabled'], 'true');
console.log('Weather/selectors passed: unchanged outdoor hover, Ctrl selector, metric/date preservation, future-day guard, calendar/DST dates, weekday labels, weather values/units, centered wind histogram, no batteries.');
