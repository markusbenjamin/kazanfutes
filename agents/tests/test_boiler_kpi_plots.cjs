const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const draws = [], loads = [], nodes = [], headings = [], tooltips = [];
const selection = () => ({attrs: {}, append(tag) {const node=selection();node.tag=tag;nodes.push(node);return node;},
    attr(key,value) {this.attrs[key]=value;return this;}, style() {return this;}, text() {return this;}});
function scale() {let domain,range;const f=value=>range[0]+(value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
    f.domain=value=>(domain=value,f);f.range=value=>(range=value,f);return f;}
const context = require('./dashboard_test_context.cjs')({Number, Math, Date, Object, dayStamp: () => '2026-10-21',
    mainGraphSetting: {}, mainGraphContentLocked: false, dashboardFont: 'Consolas', isMobile:false, mobileViewScaler:1.8,
    d3:{scaleLinear:scale}, bindPlotCurveTooltip:(node,label)=>tooltips.push(label), clearMainGraphs() {}, drawMainGraph() {},
    collectDataFromGitHub: (requests, callback) => loads.push({requests, callback}),
    drawPlot: (data, options) => {draws.push({data, options}); return {plotElement: selection(), plotDims: {w:200,h:100}};}});
for (const file of ['cycle_heat_plots.js', 'room_control_plots.js', 'boiler_kpi_plots.js'])
    vm.runInContext(fs.readFileSync(path.join(root, 'docs', file), 'utf8'), context);
context.drawPlotTitleSelector=(node,dims,options)=>headings.push(options);
context.bindPlotCurveTooltip=(node,label)=>tooltips.push(label);
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code, context)));
context.data = {gas_usage: [{h_of_day_frac: 10, burnt_volume: 10}]};
for (let cycle = 1; cycle <= 4; cycle++) context.data['cycle_' + cycle + '_heat_delivery'] = [{h_of_day_frac: 11, energy_kwh: 20}];
assert.equal(evaluate('boilerDailyKPI(data).heat_kwh'), 80);
assert.equal(evaluate('boilerDailyKPI(data).gas_kwh'), 10 * 34 / 3.6);
assert.ok(Math.abs(evaluate('boilerDailyKPI(data).ratio_pct') - 84.70588235) < 1e-6);
assert.equal(evaluate('boilerDailyKPI({})'), null);
context.data.cycle_4_heat_delivery = [];
assert.equal(evaluate('boilerDailyKPI(data)'), null); // Never count missing cycle energy as zero.
context.data.cycle_4_heat_delivery = [{h_of_day_frac: 10, energy_kwh: 20}];
assert.equal(evaluate('boilerDailyKPI(data)'), null); // No common aligned heat observations.
context.data.cycle_4_heat_delivery = [{h_of_day_frac: 11, energy_kwh: 20}];
context.data.gas_usage[0].burnt_volume = 0;
assert.equal(evaluate('boilerDailyKPI(data).ratio_pct'), null); // No division by zero or false 0%.
assert.equal(evaluate('aggregateBoilerKPIs([{heat_kwh:5,gas_kwh:10},{heat_kwh:90,gas_kwh:100}])'), 100 * 95 / 110);
assert.equal(evaluate('aggregateBoilerKPIs([])'), null);
context.elementToMainGraphSettingMapping = {};
context.event = {ctrlKey:true,altKey:false,preventDefault(){}};
assert.equal(evaluate('openRoomControlPlot(event,"boiler_body")'), false);
context.event = {ctrlKey:false,altKey:true,preventDefault(){}};
assert.equal(evaluate('openRoomControlPlot(event,"boiler_body")'), true);
assert.equal(context.mainGraphSetting.title, 'boiler_kpi');
vm.runInContext('drawBoilerKPIView()', context);
assert.equal(loads.length,4,'daily loads are bounded to four concurrent requests');
assert.equal(loads[0].requests.length, 5);
assert.equal(loads[0].requests[0].day, '2026-09-22');
assert.equal(context.mainGraphSetting.windowDays,30);
vm.runInContext('navigateMainPlotDay(-1)', context);
assert.equal(context.mainGraphSetting.day, '2026-10-20');
assert.equal(context.mainGraphSetting.title, 'boiler_kpi');
const count = draws.length;
loads[0].callback({});
assert.equal(draws.length, count); // Stale date cannot repaint current view.
vm.runInContext('drawBoilerKPIView({})', context);
assert.equal(draws.at(-1).options.plotDateNavigation.day, '2026-10-20');
assert.equal(draws.at(-1).options.margins.top, .29);
assert.ok(nodes.some(node=>node.attrs.class==='boiler-analytics-title'));
assert.equal(headings.at(-1).prefix,'','analytics heading has a separate row');
assert.equal(headings.at(-1).selected,'ratio');
assert.deepEqual(Array.from(headings.at(-1).choices,choice=>choice.label),
    ['hatásfok','előremenő / visszatérő fázissík']);
const original=context.mainGraphSetting;
context.byDay={'2026-10-20':{gas_usage:[{h_of_day_frac:11,burnt_volume:10}],
    ...Object.fromEntries([1,2,3,4].map(cycle=>['cycle_'+cycle+'_heat_delivery',[{h_of_day_frac:11,energy_kwh:20}]]))}};
nodes.length=0;
vm.runInContext('drawBoilerKPIView(byDay)',context);
const bars=nodes.filter(node=>node.attrs.class==='boiler-efficiency-bar');
assert.equal(bars.length,1,'one daily bar per complete energy observation; missing days are not zero-filled');
assert.equal(bars[0].attrs['data-day'],'2026-10-20');
assert.ok(bars[0].attrs.height>0&&bars[0].attrs.width>0);
assert.equal(bars[0].attrs.stroke,'none');
assert.equal(draws.at(-1).options.axesLabel.left,'hatásfok (%)');
assert.equal(draws.at(-1).options.tickVals.bottom.length,7,'date labels stay readable over thirty days');
vm.runInContext("selectBoilerKPIView('scatter')",context);
assert.equal(context.mainGraphSetting,original,'retired daily-points view cannot be selected');
assert.equal(evaluate("createBoilerKPIPlotSetting('2026-10-20','scatter').metric"),'ratio');
vm.runInContext('drawBoilerKPIView()',context);
const pending=loads.at(-1),drawCount=draws.length;
vm.runInContext("selectBoilerKPIView('phase')",context);
assert.equal(context.mainGraphSetting.metric,'phase');
assert.equal(context.mainGraphSetting.day,'2026-10-20');
assert.equal(evaluate('createBoilerKPIPlotSetting().metric'),'phase','opening analytics remembers the selected view');
pending.callback({});
assert.equal(draws.length,drawCount,'a previous view response cannot repaint phase analytics');
vm.runInContext('drawBoilerKPIView()',context);
assert.equal(loads.at(-1).requests.length,6,'phase view loads one day of temperatures, measured pump watts and heating state');
assert.ok(loads.at(-1).requests.every(request=>request.day==='2026-10-20'));
assert.equal(vm.runInContext('typeof drawBoilerDailyScatter',context),'undefined','retired renderer is removed');
context.mainGraphSetting={title:'all_rooms'};
const other=context.mainGraphSetting;
vm.runInContext("selectBoilerKPIView('ratio')",context);
assert.equal(context.mainGraphSetting,other);
vm.runInContext("mainGraphSetting=createBoilerKPIPlotSetting('2026-10-20','ratio')",context);
loads.length=0;draws.length=0;
vm.runInContext('drawBoilerKPIView()',context);
let completed=0;
while(completed<loads.length) loads[completed++].callback({});
assert.equal(completed,30,'all thirty daily loads eventually complete through the bounded queue');
assert.equal(draws.length,1,'the completed window draws one bar-chart foundation');
console.log('Boiler analytics passed: KPI calculations, two-view selector, retired view, phase loading, date/view memory and stale-response isolation.');
