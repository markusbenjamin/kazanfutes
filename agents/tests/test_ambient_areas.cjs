const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({console});
vm.runInContext(fs.readFileSync('docs/live_plot_data.js','utf8'),context);
vm.runInContext(fs.readFileSync('docs/ambient_areas.js','utf8'),context);
vm.runInContext(`const now=new Date(2026,10,7,12,0,0);
 const state={measured_temps:{13:20,25:22,1:18,16:24},
 sensor_last_updated:{13:'2026-11-07-12-00-00',25:'2026-11-07-12-00-00',1:'2026-11-07-12-00-00',16:'2026-11-07-12-00-00'},
 weather_station:{temperature_c:3,timestamp:'2026-11-07-12-00-00'},external_temp:99};
 const system={state};`,context);
const run=source=>vm.runInContext(source,context);
assert.equal(run(`ambientAreaTemperature({rooms:['13','25']},system,now)`),21);
assert.equal(run(`ambientAreaTemperature({rooms:['25','1','16']},system,now)`),(22+18+24)/3);
assert.equal(run(`ambientAreaTemperature({source:'ws90',rooms:[]},system,now)`),3);
run(`state.sensor_last_updated[25]='2026-11-07-08-00-00'; state.measured_temps[13]=0;`);
assert.equal(run(`ambientAreaTemperature({rooms:['13','25']},system,now)`),0);
run(`state.measured_temps[13]=null;`);
assert.equal(run(`ambientAreaTemperature({rooms:['13','25']},system,now)`),null);
run(`state.weather_station.timestamp='2026-11-07-11-50-00';`);
assert.equal(run(`ambientAreaTemperature({source:'ws90',rooms:[]},system,now)`),null);
run(`const estimateSystem={state:{measured_temps:{9:20,10:null,2:22,25:18},
 sensor_last_updated:{9:'2026-11-07-12-00-00',10:'2026-11-07-12-00-00',2:'2026-11-07-12-00-00',25:'2026-11-07-12-00-00'},
 weather_station:{temperature_c:10,timestamp:'2026-11-07-12-00-00'}}};`);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.pult,estimateSystem,now)`),18);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.lepcso_1,estimateSystem,now)`),20);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.lepcso_2,estimateSystem,now)`),20);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.lepcsohaz,estimateSystem,now)`),16);
run(`estimateSystem.state.weather_station.temperature_c=17.5;`);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.pult,estimateSystem,now)`),20);
run(`estimateSystem.state.weather_station.temperature_c=40; estimateSystem.state.measured_temps[10]=24;`);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.pult,estimateSystem,now)`),22);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.lepcso_1,estimateSystem,now)`),22);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.lepcsohaz,estimateSystem,now)`),24);
run(`estimateSystem.state.weather_station.timestamp='2026-11-07-11-50-00';`);
assert.equal(run(`ambientAreaTemperature(ambientAreaMappings.pult,estimateSystem,now)`),20);
console.log('Area colours passed: room means, missing/stale sources, WS90, shared stairs and gradual outdoor adjustments.');
