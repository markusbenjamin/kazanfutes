const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const styles = new Map(), roomPaints = [], pipePaints = [], ambientPaints = [];
const node = id => ({style(key,value) {styles.set(id + ':' + key,value);return this;},selectAll(){return this;}});
const context = vm.createContext({Date, Number, Math, Map, Set, Object, console,
    d3:{select:node,interpolateRgb:()=>fraction=>'scale:' + fraction},
    roomsDataAndState:{1:{roomID:'room_1',temp:20,occupancy:true}},
    updateRoomColor(...args){roomPaints.push(args);},
    updateCycleColor(...args){pipePaints.push(args);},
    updateAmbientAreas(system){ambientPaints.push(system);}});
const load = file=>vm.runInContext(fs.readFileSync(file,'utf8'),context);
load('docs/live_plot_data.js');
load('docs/replay_temperatures.js');
load('docs/dashboard_replay.js');
const helpers = fs.readFileSync('docs/codebase.js','utf8');
vm.runInContext(helpers.slice(helpers.indexOf('function dateFromTimestamp('),helpers.indexOf('function addTimeToDate(')),context);
load('docs/radiator_plots.js');
const run = code=>vm.runInContext(code,context);
const stamp = minute=>'2026-11-11-09-' + String(minute).padStart(2,'0') + '-00';
context.stamp = stamp;
run(`
const t = minute=>livePlotDate(stamp(minute)).getTime();
const series = new ReplayTemperatureSeries([{timestamp:stamp(0),value:20},{timestamp:stamp(4),value:24}],300);
`);
assert.equal(run('series.at(t(2))'),22,'Linear interpolation between real observations');
assert.equal(run('series.at(t(0))'),20);
assert.equal(run('series.at(t(4))'),24);
assert.equal(run('series.at(t(5))'),24,'Hold the last reading, never extrapolate its slope');
assert.equal(run('series.at(t(10))'),null,'Held readings still expire');
assert.equal(run('series.at(t(0)-60000)'),null,'No backward extrapolation');
run(`
const broken = new ReplayTemperatureSeries([{timestamp:stamp(0),value:20},
 {timestamp:stamp(2),value:null},{timestamp:stamp(4),value:24}],300);
const distant = new ReplayTemperatureSeries([{timestamp:stamp(0),value:20},{timestamp:stamp(10),value:30}],300);
const sourceChange = new ReplayTemperatureSeries([{timestamp:stamp(0),value:20},
 {timestamp:stamp(4),value:30,breakBefore:true}],300);
`);
assert.equal(run('broken.at(t(1))'),20,'Do not ramp towards unavailable values');
assert.equal(run('broken.at(t(2))'),null);
assert.equal(run('broken.at(t(3))'),null,'An outage is not bridged');
assert.equal(run('broken.at(t(4))'),24,'Recovery is discrete');
assert.equal(run('distant.at(t(4))'),20,'Long gaps are held, not interpolated');
assert.equal(run('distant.at(t(6))'),null);
assert.equal(run('sourceChange.at(t(2))'),20,'A detected source change is discrete');
run(`
const snapshot = (minute,temp,sourceMinute=minute)=>({timestamp:stamp(minute),state:{
 measured_temps:{1:temp},sensor_last_updated:{1:stamp(sourceMinute)}}});
const control = [snapshot(0,20),snapshot(1,20,0),snapshot(2,20,0),snapshot(3,20,0),snapshot(4,24)];
const roomRows = replayRoomObservations(control).get('1');
const roomTimeline = new ReplayTemperatureTimeline(control,{});
`);
assert.equal(run('roomRows.length'),2,'Controller repeats are not new sensor observations');
assert.equal(run("roomTimeline.rooms.get('1').at(t(2))"),22,'Use sensor times, not a brief ramp between controller polls');
run(`
const missing = new ReplayTemperatureTimeline([snapshot(0,20),{timestamp:stamp(1),state:{}},snapshot(4,24)],{});
const stale = new ReplayTemperatureTimeline([{timestamp:stamp(0),state:{measured_temps:{1:26.4},
 sensor_last_updated:{1:'2026-09-09-20-14-24'}}}],{});
const backwards = new ReplayTemperatureTimeline([snapshot(0,20),snapshot(4,24,0)],{});
const midnight = new ReplayTemperatureTimeline([
 {timestamp:'2026-11-10-23-59-00',state:{measured_temps:{1:20},sensor_last_updated:{1:'2026-11-10-23-59-00'}}},
 {timestamp:'2026-11-11-00-01-00',state:{measured_temps:{1:22},sensor_last_updated:{1:'2026-11-11-00-01-00'}}}],{});
`);
assert.equal(run("missing.rooms.get('1').at(t(2))"),null,'A missing room key is also an availability break');
assert.equal(run("stale.rooms.get('1').at(t(0))"),null,'Repeated stale Trafóház values cannot acquire a fresh timestamp');
assert.equal(run("backwards.rooms.get('1').at(t(2))"),20);
assert.equal(run("midnight.rooms.get('1').at(livePlotDate('2026-11-11-00-00-00').getTime())"),21,'Previous-day observations can interpolate across midnight');
run(`
const streams = {
 cycle_1_water_temps:[{timestamp:stamp(0),water_temp:30},{timestamp:stamp(4),water_temp:50}],
 cycle_2_water_temps:[{timestamp:stamp(0),water_temp:30},{timestamp:stamp(4),water_temp:50}],
 weather_station:[{timestamp:stamp(0),temperature_c:10},{timestamp:stamp(4),temperature_c:14}],
 radiator_temps:[{timestamp:stamp(0),probes:{'probe/a':30,'probe/b':40}},
 {timestamp:stamp(4),probes:{'probe/a':50,'probe/b':60}}]};
const timeline = new ReplayTemperatureTimeline(control,streams);
const actual = {state:{measured_temps:{1:20},sensor_last_updated:{1:stamp(0)},
 heatmeters:{1:{temp:30},2:{temp:30},last_updated:stamp(0)},pump_states:{1:1,2:0},
 weather_station:{timestamp:stamp(0),temperature_c:10},
 radiator_probes:{timestamp:stamp(0),devices:{probe:{a:30,b:40}}},
 radiator_valves:{timestamp:stamp(0),valves:{42:60}}}};
radiatorSystem = actual;
radiatorTargets.set('radiator',{id:'radiator',probes:['probe/a','probe/b'],trvs:['42'],cycle:1});
radiatorTargets.set('no_probe',{id:'no_probe',probes:[],trvs:['42'],cycle:1});
const before = JSON.stringify(actual);
dashboardReplayTime=t(2);
paintReplayTemperatureColours(timeline,actual,dashboardNow());
`);
assert.equal(roomPaints.at(-1)[1],22);
assert.equal(roomPaints.at(-1)[4],true,'Presence stays discrete');
assert.equal(pipePaints[0][2],40);
assert.equal(pipePaints[1][1],0,'Stopped pumps remain stopped while temperature changes');
assert.equal(run('cyclePipingColor(' + '({state:{pump_states:{2:0}}}),2)'), 'rgb(0,0,200)');
assert.equal(ambientPaints.at(-1).state.measured_temps[1],22);
assert.equal(ambientPaints.at(-1).state.weather_station.temperature_c,12,'Derived area colours use interpolated weather');
assert.equal(styles.get('#radiator:fill'),'scale:' + ((45-22)/28),'Interpolate each probe before averaging');
assert.equal(styles.get('#no_probe:fill'),'scale:0.6','Valve fallback remains discrete');
assert.equal(run('JSON.stringify(actual) === before'),true,'Never mutate actual snapshot, including readings used for faults');
assert.equal(context.roomsDataAndState[1].temp,20,'Never replace the actual room reading');
run(`actual.state.measured_temps[1]=null; actual.state.radiator_probes.devices={};
 paintReplayTemperatureColours(timeline,actual,dashboardNow());`);
assert.equal(roomPaints.at(-1)[1],null,'Future samples must not colour a currently unavailable room');
assert.equal(styles.get('#radiator:fill'),'scale:0.6','Unavailable probes fall back to actual valves, not future observations');
run(`
replayDay = {temperatures:new ReplayTemperatureTimeline([],{
 gas_usage:[{timestamp:stamp(0),burn_rate_in_m3_per_h:2},{timestamp:stamp(2),burn_rate_in_m3_per_h:6}]})};
dashboardReplayTime=t(1);
`);
context.currentGasUsageRate=2;
assert.equal(run('replayVisualGasUsageRate()'),4,'Interpolate gas only for visual consumers');
assert.equal(context.currentGasUsageRate,2,'The infobox gas rate remains the recorded reading');
const flames = [], hands = [];
Object.assign(context,{boilerState:1,boilerColdWaterError:false,boilerHeatingEnabled:true,aspectRatio:1,
    constrain:(v,min,max)=>Math.max(min,Math.min(max,v)),getBBoxP5jsDimensions:()=>({cx:0,cy:0,w:10,h:10}),
    mapSize:()=>({w:1,h:1}),random:()=>1,color:(...args)=>args,drawFlame:(...args)=>flames.push(args),
    isValidNumber:Number.isFinite,PI:Math.PI,TWO_PI:Math.PI*2,sin:Math.sin,cos:Math.cos,
    getZoomLevel:()=>1,roundTo:(v,step)=>Math.round(v/step)*step,isFractional:v=>!Number.isInteger(v),
    drawIsoscelesTriangle:(...args)=>hands.push(args)});
for (const name of ['strokeWeight','stroke','line','fill','noStroke','noFill','ellipse']) context[name]=()=>{};
const draw=fs.readFileSync('docs/draw.js','utf8');
vm.runInContext(draw.slice(draw.indexOf('function drawBoiler('),draw.indexOf('function textOnArcUprightWeighted(')),context);
run('drawBoiler()');
assert.ok(Math.abs(flames[0][2]-.58)<1e-10,'Flame strength follows the interpolated rate');
assert.ok(Math.abs(hands.at(-1)[4]-Math.PI*1.85)<1e-10,'The analog gas dial follows the same interpolated rate');
assert.equal(context.currentGasUsageRate,2);
context.boilerColdWaterError=true;
const count=flames.length;
run('drawBoiler()');
assert.equal(flames.length,count,'Interpolation cannot suppress the discrete boiler-fault override');
assert.ok(Math.abs(hands.at(-1)[4]-Math.PI*1.25)<1e-10);
run('dashboardReplayTime=null');
assert.equal(run('replayVisualGasUsageRate()'),2,'Live mode keeps its existing rate');
run('dashboardReplayTime=t(6)');context.currentGasUsageRate=0;
assert.equal(run('replayVisualGasUsageRate()'),0,'No extrapolation past stale gas readings');
console.log('Replay visuals: sensor-time interpolation, gaps, stale/missing readings, midnight, source changes, probe averages, discrete fallbacks, snapshot isolation, flame strength and gas dial passed.');
