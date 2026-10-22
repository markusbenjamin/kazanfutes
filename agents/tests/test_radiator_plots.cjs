const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const calls = [];
const context = vm.createContext({Number,Math,Date,Object,Map,Set,Array,
    dayStamp:()=> '2026-10-22', dateFromTimestamp:stamp=>new Date(stamp.slice(0,10)+'T'+stamp.slice(11).replaceAll('-',':')),
    getFractionalHourOfDay:()=>12, drawPlot:(data,options)=>calls.push({data,options}),
    navigateMainPlotDay:()=>{}, mainGraphSetting:{}, mainGraphContentLocked:false,
    d3:{interpolateRgb:()=>value=>'color-'+value}, drawMainGraph:()=>{}});
for (const file of ['cycle_heat_plots.js','room_metric_plots.js','radiator_plots.js'])
    vm.runInContext(fs.readFileSync('docs/'+file,'utf8'),context);
const read = script=>JSON.parse(JSON.stringify(vm.runInContext(script,context)));
assert.equal(read('radiatorMean([null,0,40])'),20);
assert.equal(read('radiatorMean([null,undefined])'),null);
assert.equal(read('radiatorTooltipText({temperature:42.3,valve:0})'),'42.3 °C · 0%');
assert.equal(read('radiatorTooltipText({temperature:null,valve:75})'),'75%');
assert.equal(read('heatingTemperatureColor(null)'),'rgb(255,0,0)');
assert.equal(read('heatingTemperatureColor(20)'),'color-0');
assert.equal(read('heatingTemperatureColor(22)'),'color-0');
assert.equal(read('heatingTemperatureColor(36)'),'color-0.5');
assert.equal(read('heatingTemperatureColor(50)'),'color-1');
assert.equal(read('heatingTemperatureColor(70)'),'color-1');
assert.equal(read('cyclePipingColor({state:{pump_states:{1:0}}},1)'),'rgb(0,0,200)');
assert.equal(read('radiatorElementColor({cycle:1},{temperature:null,valve:null},{state:{pump_states:{1:0}}})'),'rgb(0,0,200)');
assert.equal(read('radiatorElementColor({cycle:1},{temperature:null,valve:null},{state:{pump_states:{1:1}}})'),'rgb(255,0,0)');
assert.equal(read('radiatorElementColor({cycle:1},{temperature:36,valve:100},{state:{pump_states:{1:0}}})'),'color-0.5');
assert.equal(read('radiatorElementColor({cycle:1},{temperature:NaN,valve:null},null)'),'rgb(0,0,200)');
assert.equal(read('radiatorElementColor({cycle:1},{temperature:null,valve:25},{state:{pump_states:{1:0}}})'),'color-0.25');
assert.equal(read('radiatorElementColor({cycle:1},{temperature:null,valve:0},{state:{pump_states:{1:1}}})'),'color-0');
const now=new Date();
context.freshStamp=[now.getFullYear(),now.getMonth()+1,now.getDate(),now.getHours(),now.getMinutes(),now.getSeconds()]
    .map(value=>String(value).padStart(2,'0')).join('-');
assert.equal(read('radiatorElementColor({cycle:1},{temperature:null,valve:null},{state:{pump_states:{1:1},heatmeters:{last_updated:freshStamp,1:{temp:36}}}})'),'color-0.5');
context.mapping=JSON.parse(fs.readFileSync('system/radiator_mapping.json','utf8'));
context.node={id:'golyafeszek_radiator_1', getAttribute:key=>({'data-probes':'["ovi_radiatorok_shelly/temperature:100","ovi_radiatorok_shelly/temperature:101"]','data-trvs':'["71"]'})[key]??null,
    closest:()=>({id:'cycle1_radiators'})};
const target=read('radiatorTargetFromElement(node,mapping)');
assert.equal(target.probes.length,2); assert.deepEqual(target.trvs,['71']); assert.equal(target.cycle,1);
context.namedNode={id:'merce_targyalo_radiator_1',getAttribute:key=>key==='data-display-label'?'Diós Edit':null,
    closest:()=>({id:'cycle2_radiators'})};
const namedTarget=read('radiatorTargetFromElement(namedNode,mapping)');
assert.equal(namedTarget.label,'Diós Edit');
assert.equal(namedTarget.location,'merce_targyalo');
assert.ok(namedTarget.probes.includes('merce_radiatorok_2_shelly/temperature:100'));
context.target=target;
vm.runInContext('radiatorTargets.set(target.id,target)',context);
assert.equal(read('radiatorPlotSetting(target).metric'),'average');
context.valveTarget={...target,probes:[]};
assert.equal(read('radiatorPlotSetting(valveTarget).metric'),'valves');
const originalAttribute=context.node.getAttribute;
context.node.getAttribute=key=>key==='data-probes'?'["wrong/temperature:100"]':originalAttribute(key);
assert.throws(()=>vm.runInContext('radiatorTargetFromElement(node,mapping)',context),/outside mapped unit/);
context.rows=[{h_of_day_frac:1,probes:{a:0,b:40}},{h_of_day_frac:1.05,probes:{a:null,b:50}},
    {h_of_day_frac:1.1,probes:{a:null,b:null}},{h_of_day_frac:2,probes:{a:60,b:80}}];
const series=read('radiatorSeries(rows,"probes",["a","b"])');
assert.equal(series[0].value,20); assert.equal(series.at(-1).value,70);
assert.ok(series.some(row=>row.h_of_day_frac>1.1&&row.h_of_day_frac<2&&row.value===null));
assert.equal(series.find(row=>row.h_of_day_frac===1.05).value,25);
context.dropoutRows=[
    {h_of_day_frac:12.55,probes:{a:49.1,b:21.6}},
    {h_of_day_frac:12.55+1/60,probes:{a:48.1,b:null}},
    {h_of_day_frac:12.55+2/60,probes:{a:47.2,b:21.6}},
    {h_of_day_frac:12.55+3/60,probes:{a:null,b:null}},
    {h_of_day_frac:12.55+8/60,probes:{a:45,b:null}},
    {h_of_day_frac:12.55+9/60,probes:{a:44,b:22}}
];
const dropoutSeries=read('radiatorSeries(dropoutRows,"probes",["a","b"])');
const sampleAt=time=>dropoutSeries.find(row=>Math.abs(row.h_of_day_frac-time)<1e-10).value;
assert.ok(Math.abs(sampleAt(12.55+1/60)-34.85)<1e-10,'missing cool probe must not spike the mean');
assert.ok(Math.abs(sampleAt(12.55+3/60)-34.4)<1e-10,'brief simultaneous dropout keeps the consistent pair');
assert.equal(sampleAt(12.55+8/60),null,'do not switch to the one surviving probe after expiry');
assert.equal(sampleAt(12.55+9/60),33,'resume once all probes have fresh values');
context.partialRows=[{h_of_day_frac:0,probes:{a:0,b:null}},{h_of_day_frac:1/60,probes:{a:null,b:20}}];
const partial=read('radiatorSeries(partialRows,"probes",["a","b"])');
assert.equal(partial[0].value,null,'no partial mean before all probes have been seen');
assert.equal(partial.at(-1).value,10,'zero temperature remains a real reading');
assert.equal(read('radiatorSeries([{h_of_day_frac:1,valves:{a:20}},{h_of_day_frac:1.01,valves:{a:null}}],"valves",["a"])').at(-1).value,null);
assert.equal(read('radiatorFresh("2026-10-22-10-00-00",300,new Date("2026-10-22T10:10:00"))'),false);
context.data={radiator_temps:[{h_of_day_frac:1,probes:{'ovi_radiatorok_shelly/temperature:100':20,'ovi_radiatorok_shelly/temperature:101':40}}],
    radiator_valves:[{h_of_day_frac:1,valves:{71:0}},{h_of_day_frac:1.01,valves:{71:50}}]};
context.setting={sourceElementId:target.id,metric:'average',detailed:false,day:'2026-10-22'};
vm.runInContext('drawRadiatorPlot(data,setting)',context);
assert.equal(calls[1].data[0].value,30); assert.equal(calls[0].options.axesLabel.left,'°C');
assert.equal(calls[1].options.plotStyle.endCap,true);
assert.equal(calls[1].options.curveEndText.show,true);
assert.equal(calls[1].options.curveEndText.text,'30 °C');
assert.equal(calls[1].options.curveEndText.col,calls[1].options.plotStyle.col);
calls.length=0; context.setting={...context.setting,metric:'probes',detailed:true};
vm.runInContext('drawRadiatorPlot(data,setting)',context);
assert.equal(calls.length,3); assert.equal(calls[0].options.plotLabelTabs.choices.length,3);
assert.ok(calls.slice(1).every(call=>call.options.plotStyle.endCap));
assert.deepEqual(calls.slice(1).map(call=>call.options.curveEndText.text),['20 °C','40 °C']);
calls.length=0; context.setting={...context.setting,metric:'average'};
context.gappedData={radiator_temps:[context.data.radiator_temps[0],{...context.data.radiator_temps[0],h_of_day_frac:2}],radiator_valves:[]};
vm.runInContext('drawRadiatorPlot(gappedData,setting)',context);
assert.ok(calls.length>2,'test must contain separate curve pieces');
assert.equal(calls.slice(1).filter(call=>call.options.plotStyle.endCap).length,1,'only the final curve piece gets a dot');
assert.equal(calls.at(-1).options.plotStyle.endCap,true);
assert.equal(calls.slice(1).filter(call=>call.options.curveEndText.show).length,1,'only the final curve piece gets end-value text');
assert.equal(calls.at(-1).options.curveEndText.text,'30 °C');
assert.ok(calls.slice(1).every(call=>!call.options.plotStyle.startCap));
calls.length=0; context.setting.metric='valves';
vm.runInContext('drawRadiatorPlot(data,setting)',context);
assert.equal(calls[0].options.axesLabel.left,'%'); assert.equal(calls[1].options.plotStyle.stepAfter,true);
assert.equal(calls[1].data[0].value,0);
assert.equal(calls[1].options.plotStyle.endCap,false,'valve curve style stays unchanged');
assert.equal(calls[1].options.curveEndText.show,true);
assert.equal(calls[1].options.curveEndText.text,'50%');
calls.length=0;
context.data={};
vm.runInContext('drawRadiatorPlot(data,setting)',context);
assert.equal(calls.length,1);
assert.equal(calls[0].options.curveEndText.show,false,'missing data must not show a zero-value label');
console.log('Radiators passed: SVG unit validation, group means, raw TRV percentages, fallback blue, gaps, freshness, tooltips and selector modes.');
