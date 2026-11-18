const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const makeContext = require('./dashboard_test_context.cjs');
const day = '2026-11-18';
const ctx = makeContext({Date, Number, Object, Math});
const run = code => JSON.parse(JSON.stringify(vm.runInContext(code,ctx)));
const at = (minute,second=0) => new Date(2026,10,18,12,minute,second);
// The startup callback runs before a plot is selected. Do not expose a global
// named `setting`: it would hide an accidental free variable in the collector.
const startup=makeContext({Date,Number,Object,Math});
startup.clock=at(0);
startup.snapshot={state:{weather_station:{timestamp:day+'-12-00-00',temperature_c:8,humidity_pct:70}}};
assert.doesNotThrow(()=>vm.runInContext('recordLivePlotReadings(snapshot,clock)',startup),
    'Firebase startup must succeed without any selected plot');
assert.equal(vm.runInContext("livePlotBuffers.get('weather_station').length",startup),1);
startup.raw={[day]:{weather_station:[{h_of_day_frac:11,temperature_c:7}]}};
startup.selectedPlot={day,title:'weather_metrics',metric:'rain',types:['weather_station']};
assert.equal(vm.runInContext('withLivePlotReadings(raw,selectedPlot,snapshot,clock)',startup)[day].weather_station.length,1);
startup.selectedPlot.metric='temperature';
assert.equal(vm.runInContext('withLivePlotReadings(raw,selectedPlot,snapshot,clock)',startup)[day].weather_station.length,2);
ctx.setting = {title:'boiler_metrics',metric:'temperature',day,
    types:['cycle_1_water_temps','pumps_power','radiator_temps']};
ctx.payload = {[day]:{
    cycle_1_water_temps:[{timestamp:day+'-11-55-00',h_of_day_frac:11+55/60,water_temp:58,return_temp:38}],
    pumps_power:[{timestamp:day+'-11-55-00',h_of_day_frac:11+55/60,pump_1_power:0}],
    radiator_temps:[{timestamp:day+'-11-55-00',h_of_day_frac:11+55/60,probes:{'shelly/100':40,'shelly/101':35}}]
}};
const original = JSON.stringify(ctx.payload);
function sample(minute,second,supply,pump,probe,returned=40) {
    ctx.now=at(minute,second);
    const stamp=run('livePlotStamp(now)');
    ctx.system={state:{
        heatmeters:{last_updated:stamp,1:{temp:supply,return_temp:returned}},
        pumps:{last_updated:stamp,power:{1:pump}},
        radiator_probes:{timestamp:stamp,devices:{shelly:{100:probe,101:null}}}
    }};
    // Capture even while no chart/history request is active.
    vm.runInContext('recordLivePlotReadings(system,now)',ctx);
}
const draw = () => run('withLivePlotReadings(payload,setting,system,now)')[day];
sample(0,5,60,0,50);
sample(0,25,40,40,30);
let result=draw();
assert.equal(result.cycle_1_water_temps.at(-1).water_temp,50,'average distinct readings in the current minute');
assert.equal(result.radiator_temps.at(-1).probes['shelly/100'],40,'average nested probe channels independently');
assert.equal(result.radiator_temps.at(-1).probes['shelly/101'],null,'missing probes remain missing');
assert.equal(result.cycle_1_water_temps.length,2,'one minute creates one endpoint, not a swarm of points');
assert.deepEqual(result.pumps_power.slice(1).map(row=>row.pump_1_power),[0,40],'electrical steps are not averaged');
ctx.now=at(0,45);
for(let poll=0;poll<5;poll++) draw();
assert.equal(draw().cycle_1_water_temps.at(-1).water_temp,50,'unchanged publications cannot bias the mean');
assert.equal(run("livePlotBuffers.get('cycle_1_water_temps').length"),2,'redraws do not accumulate samples');
sample(1,5,70,0,60);
result=draw();
const frozen=result.cycle_1_water_temps[1];
assert.equal(frozen.water_temp,50);
assert.equal(result.cycle_1_water_temps.at(-1).water_temp,70);
sample(1,25,50,0,40);
result=draw();
assert.deepEqual(result.cycle_1_water_temps[1],frozen,'later readings never rewrite a completed minute');
assert.equal(result.cycle_1_water_temps.at(-1).water_temp,60);
assert.deepEqual(result.pumps_power.slice(1).map(row=>row.pump_1_power),[0,40,0,0]);
assert.equal(JSON.stringify(ctx.payload),original,'archives and caches stay immutable');
assert.ok(result.cycle_1_water_temps.slice(1).every(row=>row.live),'buffered points retain live bridge identity');
const retained=run("livePlotBuffers.get('cycle_1_water_temps')");
const latestSystem=ctx.system;
ctx.system={state:{heatmeters:{last_updated:day+'-12-00-25',1:{temp:90,return_temp:40}}}};
assert.equal(draw().cycle_1_water_temps.at(-1).water_temp,60,'out-of-order publications cannot change the live mean');
assert.deepEqual(run("livePlotBuffers.get('cycle_1_water_temps')"),retained);
ctx.system=latestSystem;
// Reusing an augmented payload still must not append duplicates.
const raw=ctx.payload;
ctx.payload={[day]:result};
assert.deepEqual(draw(),result);
ctx.payload=raw;
// A newly downloaded archive takes precedence over buffered source readings.
ctx.payload[day].cycle_1_water_temps.push({timestamp:day+'-12-01-10',h_of_day_frac:12+70/3600,water_temp:66,return_temp:40});
result=draw();
assert.equal(result.cycle_1_water_temps.length,3);
assert.equal(result.cycle_1_water_temps.at(-1).water_temp,50,'exclude already archived samples from the live mean');
ctx.payload[day].cycle_1_water_temps.push({timestamp:day+'-12-01-25',h_of_day_frac:12+85/3600,water_temp:52,return_temp:40});
assert.equal(draw().cycle_1_water_temps.at(-1).water_temp,52,'archive at now wins');
// No buffered standalone curve when the selected historical stream is empty.
ctx.payload[day].cycle_1_water_temps=[];
assert.deepEqual(draw().cycle_1_water_temps,[]);
ctx.payload=raw;
ctx.setting.day='2026-11-17';
assert.deepEqual(run('withLivePlotReadings(payload,setting,system,now)'),JSON.parse(JSON.stringify(raw)));
ctx.setting.day=day;ctx.setting.title='room_control_phase';
assert.deepEqual(run('withLivePlotReadings(payload,setting,system,now)'),JSON.parse(JSON.stringify(raw)));
ctx.setting.title='boiler_metrics';ctx.now=at(10);
assert.deepEqual(run('withLivePlotReadings(payload,setting,system,now)'),JSON.parse(JSON.stringify(raw)),
    'stale publications do not keep a live tail alive');

// Preserve actual zeros; a bad last reading cannot resurrect an earlier valid one.
vm.runInContext('livePlotBuffers.clear()',ctx);
ctx.payload={[day]:{cycle_1_water_temps:[{h_of_day_frac:11,water_temp:50,return_temp:35}]}};
sample(11,0,60,0,40);
sample(11,20,null,0,40);
assert.equal(draw().cycle_1_water_temps.at(-1).water_temp,undefined);
assert.equal(draw().cycle_1_water_temps.at(-1).return_temp,40);

// Retention and day rollover are bounded even with one publication per second.
vm.runInContext('livePlotBuffers.clear()',ctx);
for(let index=0;index<800;index++) {
    ctx.now=new Date(at(20).getTime()+index*1000);
    const stamp=run('livePlotStamp(now)');
    ctx.system={state:{heatmeters:{last_updated:stamp,1:{temp:40+index%10,return_temp:30}}}};
    vm.runInContext('recordLivePlotReadings(system,now)',ctx);
}
assert.equal(run("livePlotBuffers.get('cycle_1_water_temps').length"),720);
ctx.now=at(100);
ctx.system.state.heatmeters.last_updated=run('livePlotStamp(now)');
vm.runInContext('recordLivePlotReadings(system,now)',ctx);
assert.equal(run("livePlotBuffers.get('cycle_1_water_temps').length"),1,'expire samples older than one hour');
ctx.now=new Date(2026,10,19,0,0,0);ctx.system={state:{}};
vm.runInContext('recordLivePlotReadings(system,now)',ctx);
assert.equal(run('livePlotBuffers.size'),0,'never carry a prior day tail into the new day');
const source=fs.readFileSync('docs/data.js','utf8');
assert.match(source,/recordLivePlotReadings\(fullFirebaseDataJSON\.system\);\s*replayLatestLive/,
    'capture at Firebase receipt independently of the displayed chart and replay mode');
console.log('Live tail passed: independent collection, one-minute means, frozen bins, deduplication, nested probes, sharp power edges, archive precedence, stale/invalid isolation, loading gates and bounded retention.');
