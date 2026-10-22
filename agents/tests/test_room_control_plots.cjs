const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const draws = [], loads = [], labels = [], nodes = [];
function selection() {
    const node = {attrs: {}, styles: {}, append: () => selection(), attr(key, value) {this.attrs[key]=value;return this;},
        style(key,value) {this.styles[key]=value;return this;}, text(value) {this.value=value;return this;},
        node() {return {getComputedTextLength: () => String(this.value || '').length * parseFloat(this.styles['font-size'] || 5) * .6};}};
    nodes.push(node);
    return node;
}
function scaleLinear() {
    let domain, range;
    const scale = value => range[0] + (value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
    scale.domain = values => {domain=values;return scale;}; scale.range = values => {range=values;return scale;};
    return scale;
}
const context = vm.createContext({Number, Math, Date, Object, mainGraphSetting: {}, mainGraphContentLocked: false,
    dashboardFont: 'Consolas', dayStamp: () => '2026-10-21', clearMainGraphs() {},
    elementToMainGraphSettingMapping: {Oktopusz: {title:'room_plot',roomNumToPlot:1}, cycle1:{title:'cycle_water_temp'}},
    allControlledRooms:[1,2], roomsDataAndState:{1:{name:'Oktopusz szita'},2:{name:'Gólyafészek'}},
    roomsColorScale: ()=>'green', roomsColorRemap:[1,2], d3:{scaleLinear},
    drawPlot: (data,options)=>{draws.push({data,options}); return {plotElement:selection(),plotDims:{w:200,h:100}};},
    bindPlotCurveTooltip: (target,label)=>labels.push(label),
    collectDataFromGitHub: (requests,callback)=>loads.push({requests,callback}),
    drawMainGraph() {}
});
vm.runInContext(fs.readFileSync(path.join(root,'docs/cycle_heat_plots.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(root,'docs/room_control_plots.js'),'utf8'),context);
context.drawPlotTitleSelector=()=>{};
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.event={ctrlKey:false,altKey:false,preventDefault(){}};
assert.equal(evaluate("openRoomControlPlot(event,'Oktopusz')"),false);
context.event.ctrlKey=true;
assert.equal(evaluate("openRoomControlPlot(event,'Oktopusz')"),false); // Existing Ctrl room selector wins.
assert.equal(evaluate("openRoomControlPlot(event,'general_infobox')"),false); // Analytics consistently uses Alt, not Ctrl.
context.event.ctrlKey=false; context.event.altKey=true;
assert.equal(evaluate("openRoomControlPlot(event,'general_infobox')"),true);
assert.equal(context.mainGraphSetting.title,'room_control_overview');
assert.equal(context.mainGraphContentLocked,true);
const overviewSetting=context.mainGraphSetting;
vm.runInContext("selectRoomControlOverviewState('above_off')",context);
assert.notEqual(context.mainGraphSetting,overviewSetting);
assert.equal(context.mainGraphSetting.overviewState,'above_off');
assert.equal(context.mainGraphSetting.day,'2026-10-21');
vm.runInContext('navigateRoomControlDay(-1)',context);
assert.equal(context.mainGraphSetting.overviewState,'above_off');
vm.runInContext("selectRoomControlOverviewState('below_on')",context);
context.event.ctrlKey=false; context.event.altKey=true;
assert.equal(evaluate("openRoomControlPlot(event,'Oktopusz')"),true);
assert.equal(context.mainGraphSetting.roomNumToPlot,1);
vm.runInContext('navigateRoomControlDay(-1)',context);
assert.equal(context.mainGraphSetting.day,'2026-10-20');
assert.equal(context.mainGraphSetting.title,'room_control_diagnostic');
vm.runInContext('navigateRoomControlDay(1)',context);
const today=context.mainGraphSetting;
vm.runInContext('navigateRoomControlDay(1)',context);
assert.equal(context.mainGraphSetting,today);
const row=(mae,hours,bias=0)=>({mae_on_c:mae,bias_on_c:bias,heating_seconds:hours*3600,
    valid_seconds:hours*3600,occupied_seconds:hours*3600,comfort_seconds:hours*1800,absolute_error_on_kh:mae*hours,
    signed_error_on_kh:bias*hours,coverage_pct:50,quadrant_seconds:{below_on:hours*1800,above_on:0,below_off:0,above_off:0},
    quadrant_error_kh:{below_on:mae*hours/2,above_on:0,below_off:0,above_off:0}});
context.rows=[row(1,1),row(3,3),null];
assert.equal(evaluate('aggregateRoomControlKPIs(rows).mae_on_c'),2.5);
assert.equal(evaluate('aggregateRoomControlKPIs(rows).comfort_pct'),50);
assert.equal(evaluate('aggregateRoomControlKPIs(rows).observed_days'),2);
assert.equal(evaluate('roomControlStateHours(aggregateRoomControlKPIs(rows),true,true)'),2); // Four observed hours / two observed days, not / seven.
assert.equal(evaluate('roomControlStateHours(aggregateRoomControlKPIs(rows),false,true)'),0);
assert.equal(evaluate('roomControlStateHours(null,true,true)'),null);
assert.equal(evaluate('aggregateRoomControlKPIs([{occupied_seconds:3600,comfort_seconds:900}]).comfort_pct'),25);
assert.equal(evaluate('aggregateRoomControlKPIs([{occupied_seconds:0,comfort_seconds:0}]).comfort_pct'),null);
assert.equal(evaluate('aggregateRoomControlKPIs([]).mae_on_c'),null);
assert.equal(evaluate('aggregateRoomControlKPIs([{valid_seconds: 3600, heating_seconds: 3600}]).mae_on_c'),null);
assert.deepEqual(evaluate('roomControlStateDistribution(rows[0],true)'),{seconds:3600,below:50,within:50,above:0});
assert.equal(evaluate('roomControlStateDistribution(rows[0],false)'),null); // No off time is not perfect control.
assert.equal(evaluate('roomControlStateDistribution(null,true)'),null);
context.rareHeating={valid_seconds:86400,heating_seconds:3600,quadrant_seconds:{below_on:900,above_on:900,below_off:0,above_off:82800}};
assert.deepEqual(evaluate('roomControlStateDistribution(rareHeating,true)'),{seconds:3600,below:25,within:50,above:25});
assert.deepEqual(evaluate('roomControlStateDistribution(rareHeating,false)'),{seconds:82800,below:0,within:0,above:100});
assert.equal(evaluate('roomControlStateDistribution({valid_seconds:3600,heating_seconds:1800,quadrant_seconds:{}},true)'),null);
context.days=['2026-10-19','2026-10-20','2026-10-21'];
context.data={'2026-10-19':{room_control_kpis:{rooms:{1:row(0,1)}}},
    '2026-10-21':{room_control_kpis:{rooms:{1:row(2,2)}}}};
assert.equal(evaluate("roomControlDailyRow(data,'2026-10-19',1).state_error_k"),0);
assert.equal(evaluate("roomControlDailyRow(data,'2026-10-20',1)"),null);
assert.equal(evaluate("roomControlDailyRow(data,'2026-10-21',1).state_error_k"),2);
assert.equal(evaluate("roomControlDailyRow(data,'2026-10-21',1,'above_off')"),null);
context.stateData={day:{room_control_kpis:{rooms:{1:{valid_seconds:7200,heating_seconds:3600,
    quadrant_seconds:{below_on:900,above_on:1800,below_off:600,above_off:1200},
    quadrant_error_kh:{below_on:.25,above_on:1,below_off:.5,above_off:4/3}}}}}};
assert.deepEqual(evaluate("ROOM_CONTROL_QUADRANTS.map(s=>roomControlDailyRow(stateData,'day',1,s.key).state_error_k)"),[1,2,3,4]);
assert.equal(evaluate("roomControlDailyRow({'d':{room_control_kpis:{rooms:{1:{mae_on_c:0,heating_seconds:0}}}}},'d',1)"),null);
vm.runInContext('drawRoomControlView()',context);
assert.equal(loads[0].requests.length,8);
assert.equal(loads[0].requests[0].day,'2026-10-14');
assert.equal(loads[0].requests.at(-1).day,'2026-10-21');
const before=draws.length;
context.mainGraphSetting={title:'all_rooms'};
loads[0].callback({});
assert.equal(draws.length,before); // A late KPI request cannot replace another plot.
context.setting={title:'room_control_overview',day:'2026-10-21',windowDays:7};
const beforeOverview=draws.length;
vm.runInContext('drawRoomControlOverview(data,setting)',context);
assert.ok(labels.some(label=>label.includes('átlagos absz. eltérés: 2,0 K')));
assert.ok(labels.some(label=>label.includes('nyitással súlyozott állapotidő: 1,0 h')));
assert.equal(draws.length,beforeOverview+1); // One grid foundation, no overlapping per-room curves or end labels.
assert.equal(nodes.filter(node=>node.attrs.class==='room-kpi-cell').length,14);
assert.ok(nodes.some(node=>node.value==='0,0')); // Real zero remains visible.
assert.ok(nodes.some(node=>node.value==='—')); // Missing cells are unknown, never false zero.
assert.equal(draws.at(-1).options.margins.left,.03);
assert.equal(draws.at(-1).options.plotLabelTabs.choices.length,4);
assert.ok(nodes.filter(node=>node.attrs.class==='room-kpi-room-label').every(node=>node.attrs.x===0));
context.setting={title:'room_control_diagnostic',day:'2026-10-21',windowDays:7,roomNumToPlot:1};
vm.runInContext('drawRoomControlDiagnostic(data,setting)',context);
assert.equal(nodes.filter(node=>node.attrs.class==='room-kpi-state-bar').length,4);
assert.equal(draws.at(-1).options.margins.top,.22);
assert.ok(nodes.some(node=>node.value==='ma'));
assert.ok(nodes.some(node=>node.value==='7 nap'));
assert.ok(nodes.some(node=>String(node.value).endsWith(' h/nap')));
const outlines=nodes.filter(node=>node.attrs.class==='room-kpi-bar-outline');
assert.equal(new Set(outlines.map(node=>node.attrs.stroke)).size,1);
assert.equal(new Set(outlines.map(node=>node.attrs['stroke-width'])).size,1);
assert.deepEqual(evaluate('roomControlStateParts(true).map(p=>p.fill)'),['#8fbc79','white','#e58d8d']);
assert.deepEqual(evaluate('roomControlStateParts(false).map(p=>p.fill)'),['#e58d8d','white','#8fbc79']);
assert.ok(nodes.some(node=>node.attrs.class==='room-kpi-state-background'&&node.attrs['data-state']==='on'&&node.attrs.fill==='#fff0f3'));
assert.ok(nodes.some(node=>node.attrs.class==='room-kpi-state-background'&&node.attrs['data-state']==='off'&&node.attrs.fill==='#eef5ff'));
context.data={};
vm.runInContext('drawRoomControlDiagnostic(data,setting)',context);
assert.ok(draws.every(call => call.options.dataKeys?.left && call.options.dataKeys?.bottom));
assert.ok(draws.some(call=>call.options.plotLabelTabs?.prefix.includes('(K)')));
assert.ok(nodes.some(node=>node.value==='±0,5 K'));
assert.ok(nodes.every(node=>!String(node.value).includes('°C')));
assert.ok(labels.every(label=>!label.includes('°C')));
const source=fs.readFileSync(path.join(root,'docs/data.js'),'utf8');
assert.match(source,/if \(isRoomControlView\(mainGraphSetting\)\)/);
assert.match(source,/if \(openRoomControlPlot\(event, this.id\)\) return;/);
assert.match(source,/type === 'room_control_kpis'/);
console.log('Room control views passed: Alt analytics, fixed calendar window, weighted KPIs, uncluttered daily grid, missing cells, zero error, stale responses and cell tooltips.');
