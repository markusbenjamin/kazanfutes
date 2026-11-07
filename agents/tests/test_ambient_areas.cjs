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
console.log('Area colours: assigned-room means, valid zero, stale/missing sources and WS90-only origin passed.');
