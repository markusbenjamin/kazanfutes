const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const nodes = [], draws = [], tooltips = [], lines = [];
function selection() {return {attrs:{},events:{},append(tag){const child=selection(); child.tag=tag; nodes.push(child); return child;},
    attr(key,value){this.attrs[key]=value;return this;},style(){return this;},text(value){this.textValue=value;return this;},
    on(key,value){this.events[key]=value;return this;},raise(){return this;}};}
function scale(){let domain=[0,1],range=[0,1];const f=value=>range[0]+(value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
    f.domain=value=>(domain=value,f);f.range=value=>(range=value,f);return f;}
function line(){let x,y;const f=rows=>{lines.push(rows.map(row=>[x(row),y(row)]));return 'M0,0L1,1';};
    f.x=value=>(x=value,f);f.y=value=>(y=value,f);f.curve=value=>f;return f;}
const context=require('./dashboard_test_context.cjs')({Number,Math,Object,Map,isMobile:false,dashboardFont:'Consolas',
    dayStamp:()=> '2026-11-16',navigateMainPlotDay(){},mainGraphSetting:{},clearMainGraphs(){},drawMainGraph(){},
    collectDataFromGitHub:(requests,callback)=>context.lastLoad={requests,callback},
    d3:{scaleLinear:scale,line,curveCatmullRom:{alpha:()=> 'catmull-rom'},range:(a,b,s)=>Array.from({length:Math.ceil((b-a)/s)},(_,i)=>a+i*s)},
    drawPlot:(rows,options)=>{draws.push(options);return {plotElement:selection(),plotDims:{w:200,h:100}};},
    bindPlotCurveTooltip:(node,text)=>tooltips.push(text)});
for (const file of ['cycle_heat_plots','boiler_demand_bars','boiler_metric_plots','boiler_kpi_plots','boiler_water_phase'])
    vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../docs/'+file+'.js'),'utf8'),context);
context.drawPlotTitleSelector=()=>{};
const evaluate=code=>JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.data={heating_state:[{cycle_states:{1:1,2:1,3:0,4:0}}],
    cycle_1_water_temps:[{h_of_day_frac:1,water_temp:60,return_temp:40},{h_of_day_frac:1.01,water_temp:61,return_temp:null},
        {h_of_day_frac:1.02,water_temp:62,return_temp:42},{h_of_day_frac:2,water_temp:63,return_temp:43}],
    cycle_2_water_temps:[{h_of_day_frac:1,water_temp:50,return_temp:30},{h_of_day_frac:1.02,water_temp:52,return_temp:32}],
    cycle_3_water_temps:[{h_of_day_frac:1,water_temp:22,return_temp:21}],
    cycle_4_water_temps:[{h_of_day_frac:1,water_temp:55,return_temp:60044000}],
    cycle_1_heat_delivery:[{h_of_day_frac:1,flow_m3h:.5},{h_of_day_frac:1.02,flow_m3h:0},{h_of_day_frac:2,flow_m3h:-.1}],
    cycle_2_heat_delivery:[{h_of_day_frac:1,flow_m3h:0},{h_of_day_frac:1.02,flow_m3h:.2}],
    cycle_3_heat_delivery:[{h_of_day_frac:1,flow_m3h:null}],
    pumps_power:[{h_of_day_frac:1,pump_1_power:20,pump_2_power:0,pump_3_power:null},
        {h_of_day_frac:1.015,pump_1_power:0,pump_2_power:20,pump_3_power:null},
        {h_of_day_frac:2,pump_1_power:-1,pump_2_power:0,pump_3_power:null}]};
const before=JSON.stringify(context.data);
assert.deepEqual(evaluate("createBoilerMetricPlotSetting('2026-11-15','delivery').types"),
    ['heating_state',...Array.from({length:4},(_,i)=>'cycle_'+(i+1)+'_heat_delivery')]);
const curves=evaluate("boilerWaterPhaseCurves(data,{phaseMode:'all'})");
assert.equal(curves.length,4);
assert.equal(curves[0].segments.length,1,'only the pump-powered observation remains in the trajectory');
assert.equal(curves[3].segments.length,0,'corrupt return is rejected before axis allocation');
assert.deepEqual(curves[0].scatter.map(point=>point.h_of_day_frac),[1]);
assert.deepEqual(curves[1].scatter.map(point=>point.h_of_day_frac),[1.02],
    'another pump drawing power at the same time does not authorize this circuit’s dot');
assert.equal(curves[2].scatter.length,0,'unknown pump power is not positive power');
assert.ok(curves.every(curve=>JSON.stringify(curve.segments.flat())===JSON.stringify(curve.scatter)),
    'trajectory smoothing and scatter must have precisely the same source observations');
assert.deepEqual(curves.map(c=>c.color),['rgb(200,0,0)','rgb(230,130,0)','rgb(28,3,252)','rgb(0,130,0)']);
const mean=evaluate("boilerWaterPhaseCurves(data,{phaseMode:'average'})");
assert.equal(mean[0].segments[0][0].water_temp,55);
assert.equal(mean[0].segments[0][0].return_temp,35,'mean uses the same day-enabled membership as the time chart');
assert.ok(evaluate('boilerWaterPhaseRange(boilerWaterPhaseCurves(data,{phaseMode:"all"}))')[1]<=100);
assert.equal(evaluate("boilerWaterPhaseCurves(data,{phaseMode:'2'}).length"),1);
assert.equal(evaluate("boilerWaterPhaseCurves(data,{phaseMode:'2'})[0].cycle"),2);
vm.runInContext("drawBoilerWaterPhasePlot(data,{day:'2026-11-15',metric:'phase',phaseMode:'all'})",context);
assert.deepEqual({...draws[0].axesLabel},{bottom:'visszatérő (°C)',left:'előremenő (°C)'});
assert.deepEqual({...draws[0].dataKeys},{bottom:'return_temp',left:'water_temp'});
assert.equal(draws[0].domain.niceLeft,false,'manual trajectory and axes use exactly the same scales');
assert.equal(nodes.filter(node=>node.attrs.class==='boiler-water-phase-end').length,2);
assert.equal(nodes.filter(node=>node.attrs.class==='boiler-water-phase-observation').length,2,
    'scatter includes only the paired observations with their own strictly positive pump watts');
assert.ok(tooltips.some(text=>text.includes('1-es kör · 01:00')&&text.includes('előremenő: 60°C')),
    'endpoint markers also stop at the final eligible point, not a later idle reading');
assert.equal(JSON.stringify(context.data),before);
context.flowFixture={cycle_1_water_temps:[
    {h_of_day_frac:1,water_temp:60,return_temp:40},
    {h_of_day_frac:1.01,water_temp:99,return_temp:90},
    {h_of_day_frac:1.02,water_temp:62,return_temp:42}],
    cycle_1_heat_delivery:[{h_of_day_frac:1,flow_m3h:.5},{h_of_day_frac:1.01,flow_m3h:0},
        {h_of_day_frac:1.02,flow_m3h:.5}],
    pumps_power:[{h_of_day_frac:1,pump_1_power:20},{h_of_day_frac:1.005,pump_1_power:0},
        {h_of_day_frac:1.015,pump_1_power:20}]};
const filteredSmooth=evaluate("boilerWaterPhaseCurves(flowFixture,{phaseMode:'1'})[0].segments.map(segment=>boilerWaterPhaseSmooth(segment)).flat()");
assert.equal(filteredSmooth.length,2);
assert.ok(filteredSmooth.every(point=>point.water_temp>=60&&point.water_temp<=62&&point.return_temp>=40&&point.return_temp<=42),
    'a hidden pump-off temperature must not affect either coordinate of the smoothed path');
context.flowFixture.cycle_1_water_temps.push({h_of_day_frac:2,water_temp:null,return_temp:45},
    {h_of_day_frac:3,water_temp:70,return_temp:50});
context.flowFixture.cycle_1_heat_delivery.push({h_of_day_frac:2,flow_m3h:.5},{h_of_day_frac:3,flow_m3h:.5});
const continuous=evaluate("boilerWaterPhaseCurves(flowFixture,{phaseMode:'1'})[0]");
assert.equal(continuous.segments.length,1,'idle intervals, missing temperatures and long gaps never split the trajectory');
assert.deepEqual(continuous.segments[0].map(point=>point.h_of_day_frac),[1,1.02,3]);
assert.deepEqual(continuous.scatter,continuous.segments[0],'joining the curve does not add synthetic scatter points');
const tail=evaluate("boilerWaterPhaseSmooth(boilerWaterPhaseCurves(flowFixture,{phaseMode:'1'})[0].scatter).at(-1)");
assert.equal(tail.water_temp,70,'joining across a long gap does not average distant samples together');
context.powerFilterFixture={heating_state:[{cycle_states:{1:1}}],
    cycle_1_water_temps:[.99,1,1.01,1.02,1.03,1.04,2].map(h_of_day_frac=>({h_of_day_frac,water_temp:60,return_temp:40})),
    cycle_1_heat_delivery:[{h_of_day_frac:1,flow_m3h:0},{h_of_day_frac:1.02,flow_m3h:100}],
    pumps_power:[{h_of_day_frac:1,pump_1_power:20},{h_of_day_frac:1.005,pump_1_power:0,cp:true},
        {h_of_day_frac:1.015,pump_1_power:0},{h_of_day_frac:1.025,pump_1_power:null},
        {h_of_day_frac:1.035,pump_1_power:30},{h_of_day_frac:3,pump_1_power:0}]};
assert.deepEqual(evaluate("boilerWaterPhaseCurves(powerFilterFixture,{phaseMode:'1'})[0].scatter.map(point=>point.h_of_day_frac)"),
    [1,1.01,1.04,2], 'use causal, change-logged pump watts; ignore flow, commands, future readings and synthetic changepoints');
delete context.powerFilterFixture.pumps_power;
assert.equal(evaluate("boilerWaterPhaseCurves(powerFilterFixture,{phaseMode:'1'})[0].scatter.length"),0,
    'missing measured watts cannot fall back to flow or an on command');
for (const data of [{},{heating_state:[{cycle_states:{1:0,2:0,3:0,4:0}}]}]) {
    context.empty=data; draws.length=0;
    vm.runInContext("drawBoilerWaterPhasePlot(empty,createBoilerKPIPlotSetting('2026-11-15','phase'))",context);
    assert.match(draws[0].emptyMessage,/kapcsolási|engedélyezett/);
}
context.delivery={};
for (let cycle=1;cycle<=4;cycle++) context.delivery['cycle_'+cycle+'_heat_delivery']=[{h_of_day_frac:1,power_kw:cycle===4?0:cycle}];
assert.equal(evaluate('boilerDeliveredPower(delivery)[0].demand_kw'),6,'measured zero is a valid contribution');
context.delivery.cycle_2_heat_delivery.push({h_of_day_frac:1.01,power_kw:null},{h_of_day_frac:1.02,power_kw:5});
context.delivery.cycle_1_heat_delivery.push({h_of_day_frac:2,power_kw:1});
const delivered=evaluate('boilerDeliveredPower(delivery)');
assert.equal(delivered[1].demand_kw,null,'explicit missing power never becomes zero or a partial total');
assert.equal(delivered[2].demand_kw,9,'later valid power restores the total');
assert.equal(delivered[3].demand_kw,null,'stale circuit data cannot silently enter a new total');
delete context.delivery.cycle_4_heat_delivery;
assert.equal(evaluate('boilerDeliveredPower(delivery)[0].demand_kw'),null,'an absent stream is unknown');
context.window={location:{search:'?lang=en'}};
assert.equal(evaluate("dashboardText('térfogatáram')"),'flow rate');
assert.equal(evaluate("dashboardText('előremenő / visszatérő fázissík')"),'supply / return phase plane');
context.samples=[{h_of_day_frac:1,water_temp:20,return_temp:10},
    {h_of_day_frac:1+1/60,water_temp:60,return_temp:40},
    {h_of_day_frac:1+2/60,water_temp:20,return_temp:10}];
const samplesBefore=JSON.stringify(context.samples);
const smoothed=evaluate('boilerWaterPhaseSmooth(samples)');
assert.deepEqual(smoothed.map(point=>point.h_of_day_frac),context.samples.map(point=>point.h_of_day_frac),
    'smoothing retains chronological order and every observation time');
assert.ok(smoothed.every(point=>point.return_temp>=10&&point.return_temp<=40));
assert.ok(smoothed[1].water_temp<60&&smoothed[1].water_temp>20,'brief jitter is smoothed on both coordinates');
const loop=evaluate('boilerWaterPhaseSmooth(samples,.1)');
assert.ok(loop[0].water_temp<loop[1].water_temp&&loop[1].water_temp>loop[2].water_temp,
    'temporal turns/loops survive: the trajectory is never sorted by supply temperature');
assert.equal(JSON.stringify(context.samples),samplesBefore,'smoothing is presentation-only');
assert.deepEqual(evaluate('boilerWaterPhaseSmooth([])'),[]);
context.samples=[{h_of_day_frac:1,water_temp:20,return_temp:10}];
assert.deepEqual(evaluate('boilerWaterPhaseSmooth(samples)'),context.samples,'single observations remain visible');
vm.runInContext("mainGraphSetting=createBoilerKPIPlotSetting('2026-11-15','phase');selectBoilerWaterPhase('2')",context);
assert.equal(context.mainGraphSetting.phaseMode,'2');
assert.equal(context.mainGraphSetting.day,'2026-11-15');
assert.equal(evaluate('createBoilerKPIPlotSetting().phaseMode'),'2','nested selection survives reopening');
vm.runInContext('drawBoilerKPIView()',context);
assert.equal(context.lastLoad.requests.length,6,'phase analytics loads same-day temperatures and measured pump watts');
assert.ok(context.lastLoad.requests.every(request=>request.day==='2026-11-15'));
const pending=context.lastLoad.callback,drawCount=draws.length;
vm.runInContext("selectBoilerWaterPhase('3')",context);
pending({});
assert.equal(draws.length,drawCount,'a slower previous circuit selection cannot replace the new one');
assert.deepEqual(evaluate('boilerWaterPhaseTabs(mainGraphSetting).choices.map(choice=>choice.key)'),
    ['average','all','1','2','3','4']);
console.log('Boiler delivery and paired water-temperature phase views passed.');
