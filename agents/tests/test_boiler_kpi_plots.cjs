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
const context = vm.createContext({Number, Math, Date, Object, dayStamp: () => '2026-10-21',
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
assert.equal(loads[0].requests.length, 35);
assert.equal(loads[0].requests[0].day, '2026-10-15');
vm.runInContext('navigateMainPlotDay(-1)', context);
assert.equal(context.mainGraphSetting.day, '2026-10-20');
assert.equal(context.mainGraphSetting.title, 'boiler_kpi');
const count = draws.length;
loads[0].callback({});
assert.equal(draws.length, count); // Stale date cannot repaint current view.
vm.runInContext('drawBoilerKPIView({})', context);
assert.equal(draws.at(-1).options.plotDateNavigation.day, '2026-10-20');
assert.equal(draws.at(-1).options.margins.top, .24);
assert.equal(headings.at(-1).selected,'ratio');
assert.deepEqual(Array.from(headings.at(-1).choices,choice=>choice.label),['hőhasznosítás','napi pontok']);
vm.runInContext("selectBoilerKPIView('scatter')",context);
assert.equal(context.mainGraphSetting.metric,'scatter');
assert.equal(context.mainGraphSetting.day,'2026-10-20');
assert.equal(evaluate('createBoilerKPIPlotSetting().metric'),'scatter','opening analytics remembers the selected tab');
context.data.gas_usage[0].burnt_volume=10;
context.byDay={'2026-10-20':context.data,'2026-10-19':context.data};
const original=JSON.stringify(context.byDay);
nodes.length=0;
vm.runInContext('drawBoilerKPIView(byDay)',context);
assert.equal(headings.at(-1).selected,'scatter');
assert.equal(draws.at(-1).options.axesLabel.bottom,'napi leadott hő (kWh)');
assert.equal(draws.at(-1).options.axesLabel.left,'leadott hő / gázenergia (%)');
assert.equal(draws.at(-1).options.domain.niceLeft,false,'point coordinates and axes use the same range');
let points=nodes.filter(node=>node.attrs.class==='boiler-scatter-point');
assert.equal(points.length,2,'one observation per valid day, never one per log row');
assert.equal(points.at(-1).attrs['data-day'],'2026-10-20','selected day is layered on top');
const circles=nodes.filter(node=>node.tag==='circle'&&node.attrs.fill!=='transparent');
assert.deepEqual(circles.map(node=>node.attrs.fill),['black','red']);
assert.ok(circles[1].attrs.r>circles[0].attrs.r);
assert.ok(tooltips.some(label=>label.includes('2026-10-20')&&label.includes('leadott: 80')&&label.includes('84,7%')));
assert.equal(JSON.stringify(context.byDay),original,'cached daily files are never mutated');
context.scatterRows=[{day:'2026-10-20',heat_kwh:0,gas_kwh:10,ratio_pct:0},
    {day:'2026-10-19',heat_kwh:50,gas_kwh:25,ratio_pct:200},
    {day:'2026-10-18',heat_kwh:5,gas_kwh:0,ratio_pct:null},{day:'2026-10-17'}];
nodes.length=0;
vm.runInContext('drawBoilerDailyScatter(scatterRows,mainGraphSetting)',context);
points=nodes.filter(node=>node.attrs.class==='boiler-scatter-point');
assert.equal(points.length,2,'zero heat with positive gas is valid; missing/zero gas is not');
assert.equal(points.at(-1).attrs['data-ratio-pct'],0);
assert.ok(draws.at(-1).options.domain.left[1]>200,'ratios above 100% remain visible');
assert.ok(nodes.filter(node=>node.tag==='circle').every(node=>Number.isFinite(node.attrs.cx)&&Number.isFinite(node.attrs.cy)));
vm.runInContext('drawBoilerKPIView()',context);
const staleTab=loads.at(-1),beforeTab=draws.length;
vm.runInContext("selectBoilerKPIView('ratio')",context);
staleTab.callback(context.byDay);
assert.equal(draws.length,beforeTab,'stale tab responses cannot replace the selected chart');
const sameSetting=context.mainGraphSetting;
vm.runInContext("selectBoilerKPIView('bad')",context);
assert.equal(context.mainGraphSetting,sameSetting);
context.isMobile=true;
vm.runInContext('drawBoilerDailyScatter([],mainGraphSetting)',context);
assert.equal(draws.at(-1).options.emptyMessage,'Nincs elegendő energiaadat.');
context.mainGraphSetting={title:'all_rooms'};
const other=context.mainGraphSetting;
vm.runInContext("selectBoilerKPIView('scatter')",context);
assert.equal(context.mainGraphSetting,other);
console.log('Boiler KPI: daily scatter, one point per day, zero/missing energy, shared conversion, tab/date memory, mobile scale and stale-response isolation passed.');
