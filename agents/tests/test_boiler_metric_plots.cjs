const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname,'../../docs/data.js'),'utf8');
const draws = [], requests = [], barDraws = [];
const context = vm.createContext({Number, Math, Date, Object, Map,
    dayStamp: () => '2026-10-27', getFractionalHourOfDay: () => 12, mainGraphSetting: {}, mainGraphContentLocked: false,
    elementToMainGraphSettingMapping: {boiler_body: {title: 'heating_state', day: '2026-10-27'}},
    drawMainGraph: data => requests.push(data), drawPlot: (rows, options) => draws.push({rows, options}),
    navigateMainPlotDay() {}, d3: {range: (start,end,step) => Array.from({length: Math.ceil((end-start)/step)},(_,i) => start+i*step)}});
for (const file of ['cycle_heat_plots','boiler_metric_plots'])
    vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../docs/'+file+'.js'),'utf8'),context);
context.drawLoggedPowerBars = (area, rows, metric, range) => barDraws.push({rows,metric,range});
vm.runInContext(source.slice(source.indexOf('function extractHeatingPeriodsFromHeatingState('),
    source.indexOf('function convertTimestamps(')),context);
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.event = {ctrlKey: false, preventDefault() {}};
assert.equal(evaluate("openBoilerMetricPlot(event,'boiler_body')"),false);
context.event.ctrlKey = true;
assert.equal(evaluate("openBoilerMetricPlot(event,'Room')"),false);
assert.equal(evaluate("openBoilerMetricPlot(event,'boiler_body')"),true);
assert.equal(context.mainGraphSetting.title,'boiler_metrics');
assert.deepEqual(evaluate('mainGraphSetting.types'),['heating_state','heating_demand']);
context.mainGraphSetting.day = '2026-10-26';
vm.runInContext("selectBoilerMetricPlot('temperature')",context);
assert.equal(context.mainGraphSetting.day,'2026-10-26');
assert.ok(context.mainGraphSetting.types.includes('heating_state'));
assert.equal(context.mainGraphSetting.types.length,5);
context.event.altKey = true;
assert.equal(evaluate("openBoilerMetricPlot(event,'boiler_body')"),false,'Alt keeps the KPI binding');
assert.equal(evaluate('boilerEnabledCycles([])'),null);
context.states = [{h_of_day_frac:0,cycle_states: {1:0,2:0,3:0,4:0}}, {h_of_day_frac:1,cycle_states: {1:1,2:0,3:1,4:0}},
    {h_of_day_frac:2,cycle_states: {1:0,2:0,3:0,4:0}}];
assert.deepEqual(evaluate('boilerEnabledCycles(states)'),[1,3]);
assert.deepEqual(evaluate('boilerEnabledCycles(states.slice(0,1))'),[]);
context.data = {heating_state: context.states,
    cycle_1_water_temps: [{h_of_day_frac:1,water_temp:60,return_temp:40},{h_of_day_frac:1.02,water_temp:62,return_temp:null}],
    cycle_3_water_temps: [{h_of_day_frac:1,water_temp:50,return_temp:30},{h_of_day_frac:1.04,water_temp:54,return_temp:34}],
    cycle_2_water_temps: [{h_of_day_frac:1,water_temp:99,return_temp:99}]};
const average = evaluate('boilerAverageWaterTemperatures(data,boilerEnabledCycles(data.heating_state))');
assert.deepEqual(average[0],{h_of_day_frac:1,water_temp:55,return_temp:35});
assert.equal(average[1].water_temp,56);
assert.equal(average[1].return_temp,null,'missing return does not invalidate supply');
assert.equal(average[2].water_temp,58);
assert.equal(average[2].return_temp,null,'explicit missing return does not reuse an older valid reading');
assert.deepEqual(evaluate('boilerAverageWaterTemperatures(data,[])'),[]);
context.data.cycle_3_water_temps.push({h_of_day_frac:2,water_temp:55,return_temp:35});
assert.equal(evaluate('boilerAverageWaterTemperatures(data,[1,3]).at(-1).water_temp'),null,'stale active member cannot silently disappear from the mean');
assert.equal(evaluate('boilerAverageWaterTemperatures(data,[1,4])[0].water_temp'),null,'missing enabled circuit is not a partial average');
draws.length = 0;
vm.runInContext("drawBoilerMetricPlot(data,createBoilerMetricPlotSetting('2026-10-26','temperature'))",context);
assert.equal(draws[0].options.plotLabelTabs.choices.length,2);
assert.equal(draws[0].options.rects.when,'before');
assert.equal(draws[0].options.rects.list.length,2,'overlapping cycle-on backgrounds stack like on the gas plot');
assert.ok(draws[0].options.rects.list.every(rect => rect.x1===1 && rect.x2===2 &&
    rect.y1===draws[0].options.domain.left[0] && rect.y2===draws[0].options.domain.left[1] &&
    rect.fill==='rgba(255,0,0,0.05)' && rect.stroke==='rgba(255,0,0,0)' && !rect.dashed));
assert.deepEqual(Array.from(draws[0].options.plotLabelTabs.choices,choice=>choice.label),
    ['instant hőigény','átlagos fűtővíz hőm.']);
assert.ok(draws.some(draw => draw.options.curveTooltip === 'előremenő'));
assert.ok(draws.some(draw => draw.options.curveTooltip === 'visszatérő' && draw.options.plotStyle.col === 'rgb(0,40,150)'));
assert.ok(draws.filter(draw=>draw.options.background?.show===false).some(draw=>draw.options.curveEndText.show));
assert.ok(draws.slice(1).every(draw=>!draw.options.rects),'temperature curves do not duplicate the background');
draws.length = 0;
context.demand = {heating_state:context.states,heating_demand: [{h_of_day_frac:1,demand_kw:0},{h_of_day_frac:1.01,demand_kw:null},
    {h_of_day_frac:1.02,demand_kw:12.25}]};
vm.runInContext("drawBoilerMetricPlot(demand,createBoilerMetricPlotSetting('2026-10-26','demand'))",context);
assert.equal(draws.length,1,'demand uses a single foundation with bars, not curves');
assert.equal(barDraws.length,1);
assert.equal(barDraws[0].rows,context.demand.heating_demand,'logged values are passed through unchanged');
assert.equal(barDraws[0].metric.key,'demand_kw');
assert.equal(barDraws[0].metric.unit,'kW');
assert.equal(barDraws[0].metric.color,'rgb(230,130,0)');
assert.equal(barDraws[0].metric.precision,2);
assert.equal(barDraws[0].range,draws[0].options.domain.left);
assert.equal(draws[0].options.rects.list.length,2);
assert.ok(draws[0].options.rects.list.every(rect=>rect.y1===0&&rect.y2===draws[0].options.domain.left[1]));
context.openPeriod = [{h_of_day_frac:8,cycle_states:{1:1,2:0,3:0,4:0}}];
assert.equal(evaluate("boilerHeatingPeriodRects(openPeriod,'2026-10-27',[0,20])[0].x2"),12);
assert.equal(evaluate("boilerHeatingPeriodRects(openPeriod,'2026-10-26',[0,20])[0].x2"),24);
assert.deepEqual(evaluate("boilerHeatingPeriodRects(undefined,'2026-10-26',[0,20])"),[]);
draws.length = 0;
vm.runInContext("drawBoilerMetricPlot({},createBoilerMetricPlotSetting('2026-10-26','temperature'))",context);
assert.equal(draws.length,1);
assert.equal(draws[0].options.emptyMessage,'Az adott napra nincs kapcsolási adat.');
assert.match(source,/if \(openBoilerMetricPlot\(event, this.id\)\) return;/);
assert.match(source,/case 'boiler_metrics':\s*drawBoilerMetricPlot/);
assert.match(source,/type === 'heating_demand'/);
console.log('Boiler details passed: demand stream, Ctrl binding, date/metric memory, daily pump-on membership, full-day means, causal alignment, missing data, colours and labels.');
