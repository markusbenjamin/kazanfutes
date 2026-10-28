const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const calls=[],nodes=[];
let coarse=false;
const base=(title,extra={})=>({title,day:'2026-10-22',types:['source'],conditionals:[],...extra});
const background=base('all_rooms',{roomNumsToPlot:[1,2,11],hoveredCycle:0});
const mapping={Room:base('room_plot',{roomNumToPlot:1}),cycle2:base('cycle_water_temp',{cycleNum:2}),
    external_thermometer:base('external_temp'),boiler_body:base('heating_state'),gas_dial:base('gas_usage')};
const context=vm.createContext({Number,Math,Date,Object,Map,isMobile:false,window:{matchMedia:()=>({matches:coarse})},
    dayStamp:()=> '2026-10-22',dayDataNotAvailable:false,dataWaitTime:0,mainGraphSetting:background,mainGraphContentLocked:false,
    mainGraphDefaultSetting:background,elementToMainGraphSettingMapping:mapping,allMeasuredRooms:[1,2,11],
    allControlledRooms:[1,2],roomsDataAndState:{1:{name:'Room',cycle:2},2:{name:'Other',cycle:1}},
    cyclesDataAndState:{2:{rooms:[1,2]}},radiatorTargets:new Map(),dashboardFont:'Consolas',
    radiatorPlotSetting:(target,detailed,day)=>({title:'radiator',sourceElementId:target.id,detailed,day}),
    drawMainGraph:data=>calls.push(data)});
for(const file of ['cycle_heat_plots','room_metric_plots','weather_plots','room_control_plots','boiler_kpi_plots','boiler_metric_plots','mobile_plot_views'])
    vm.runInContext(fs.readFileSync('docs/'+file+'.js','utf8'),context);
const evaluate=code=>JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.event={preventDefault(){},ctrlKey:false,altKey:false};
assert.equal(evaluate("openMobilePlotTarget(event,'Room')"),false);
assert.equal(calls.length,0);
coarse=true;
assert.equal(evaluate("openMobilePlotTarget(event,'Room')"),true);
assert.equal(context.mainGraphSetting.title,'room_plot');
assert.deepEqual(evaluate('mobilePlotViewOptions().modes'),['alap','részletes','analitika']);
assert.equal(context.mainGraphContentLocked,true);
context.mainGraphSetting={...context.mainGraphSetting,day:'2026-10-20'};
vm.runInContext("roomMetricSelections.Room='co2'; selectMobilePlotView('részletes')",context);
assert.equal(context.mainGraphSetting.title,'room_metrics');
assert.equal(context.mainGraphSetting.metric,'co2');
assert.equal(context.mainGraphSetting.day,'2026-10-20');
vm.runInContext("selectMobilePlotView('analitika')",context);
assert.equal(context.mainGraphSetting.title,'room_control_phase','touch room analytics defaults to the phase plane');
assert.equal(context.mainGraphSetting.day,'2026-10-20');
vm.runInContext("selectMobilePlotView('alap')",context);
assert.equal(context.mainGraphSetting.title,'room_plot');
assert.equal(context.mainGraphSetting.day,'2026-10-20');
assert.equal(mapping.Room.day,'2026-10-22');
assert.notEqual(context.mainGraphSetting.types,mapping.Room.types);
assert.equal(evaluate("openMobilePlotTarget(event,'cycle2_infobox')"),true);
assert.deepEqual(evaluate('mobilePlotViewOptions().modes'),['alap','analitika']);
assert.deepEqual(evaluate('mainGraphSetting.roomNumsToPlot'),[1,2]);
vm.runInContext("selectMobilePlotView('analitika')",context);
assert.equal(context.mainGraphSetting.title,'room_control_phase','touch cycle analytics defaults to the phase plane');
assert.equal(context.mainGraphSetting.cycleNum,2);
vm.runInContext("openMobilePlotTarget(event,'general_infobox'); selectMobilePlotView('analitika')",context);
assert.equal(context.mainGraphSetting.cycleNum,null);
vm.runInContext("selectRoomAnalyticView('phase')",context);
assert.equal(context.mainGraphSetting.title,'room_control_phase');
assert.deepEqual(evaluate('mainGraphSetting.types'),['room_1_phase_points','room_2_phase_points']);
vm.runInContext("openMobilePlotTarget(event,'cycle2_infobox'); selectMobilePlotView('analitika'); selectRoomAnalyticView('phase')",context);
assert.equal(context.mainGraphSetting.cycleNum,2);
assert.deepEqual(evaluate('mainGraphSetting.types'),['room_1_phase_points']);
vm.runInContext("openMobilePlotTarget(event,'cycle2'); selectMobilePlotView('részletes')",context);
assert.equal(context.mainGraphSetting.detailed,true);
assert.equal(context.mainGraphSetting.cycleNum,2);
vm.runInContext("openMobilePlotTarget(event,'external_thermometer'); selectMobilePlotView('részletes')",context);
assert.equal(context.mainGraphSetting.title,'weather_metrics');
vm.runInContext("openMobilePlotTarget(event,'boiler_body')",context);
assert.deepEqual(evaluate('mobilePlotViewOptions().modes'),['alap','részletes','analitika']);
vm.runInContext("selectMobilePlotView('részletes')",context);
assert.equal(context.mainGraphSetting.title,'boiler_metrics');
vm.runInContext("selectMobilePlotView('analitika')",context);
assert.equal(context.mainGraphSetting.title,'boiler_kpi');
assert.equal(evaluate("mobilePlotTarget('gas_dial')"),null);
context.radiatorTargets.set('pk_radiator_1',{id:'pk_radiator_1'});
vm.runInContext("openMobilePlotTarget(event,'pk_radiator_1'); selectMobilePlotView('részletes')",context);
assert.equal(context.mainGraphSetting.title,'radiator');
assert.equal(context.mainGraphSetting.detailed,true);
context.event.ctrlKey=true;
assert.equal(evaluate("openMobilePlotTarget(event,'Room')"),false,'modifier-click handling remains intact');
context.event.ctrlKey=false;
vm.runInContext('clearMobilePlotContext()',context);
assert.equal(evaluate('mobilePlotViewOptions()'),null);
context.isMobile=true;coarse=false;
assert.equal(evaluate('mobilePlotViewsEnabled()'),true,'explicit legacy mobile layout is supported too');
function node(){const item={attrs:{},styles:{},events:{},append:()=>node(),attr(k,v){this.attrs[k]=v;return this;},
    style(k,v){this.styles[k]=v;return this;},text(v){this.value=v;return this;},on(k,v){this.events[k]=v;return this;}};nodes.push(item);return item;}
context.container=node();context.options={modes:['alap','részletes','analitika'],mode:'részletes'};
vm.runInContext('drawMobilePlotViewSelector(container,{w:300},options)',context);
assert.deepEqual(nodes.filter(node=>node.attrs.role==='tab').map(node=>node.attrs['aria-label']),['alap','részletes','analitika']);
assert.equal(nodes.filter(node=>node.attrs['aria-selected']==='true').length,1);
assert.ok(nodes.filter(node=>node.attrs.role==='tab').every(node=>node.events.touchstart&&node.events.mousedown&&node.events.click));
const source=fs.readFileSync('docs/data.js','utf8');
assert.match(source,/if \(openMobilePlotTarget\(event, this.id\)\) return;/);
assert.doesNotMatch(source,/mobileHeaderHeight/);
assert.match(source,/y: containerDims.h \* ops.margins.top,/);
assert.match(source,/labelRight: containerDims.w - mobileSelectorWidth/);
const labels=nodes.filter(node=>node.value&&context.options.modes.includes(node.value));
const hits=nodes.filter(node=>node.attrs.fill==='transparent');
assert.ok(labels.every(node=>node.attrs.y<0&&node.styles['text-anchor']==='end'));
assert.ok(hits.every(node=>node.attrs.y+node.attrs.height<0),'all hit areas stay above the frame');
assert.equal(hits.at(-1).attrs.x+hits.at(-1).attrs.width,300,'selector ends at frame right edge');
assert.equal(labels.at(-1).attrs.x,300-10.8*.75,'text has the same edge inset as the lock label');
console.log('Mobile views passed: touch-only tabs, contextual views, date/metric preservation, desktop shortcuts, right-aligned controls above the frame and unchanged plot geometry.');
