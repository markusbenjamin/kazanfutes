const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const draws = [], loads = [];
const selection = () => ({append: selection, attr() {return this;}, style() {return this;}, text() {return this;}});
const context = vm.createContext({Number, Math, Date, Object, dayStamp: () => '2026-10-21',
    mainGraphSetting: {}, mainGraphContentLocked: false, dashboardFont: 'Consolas', clearMainGraphs() {}, drawMainGraph() {},
    collectDataFromGitHub: (requests, callback) => loads.push({requests, callback}),
    drawPlot: (data, options) => {draws.push({data, options}); return {plotElement: selection(), plotDims: {w:200,h:100}};}});
for (const file of ['cycle_heat_plots.js', 'room_control_plots.js', 'boiler_kpi_plots.js'])
    vm.runInContext(fs.readFileSync(path.join(root, 'docs', file), 'utf8'), context);
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
console.log('Boiler KPI: sourced LHV conversion, four-cycle sum, aligned observations, missing/zero gas, weighted rollup, Alt binding and calendar navigation passed.');
