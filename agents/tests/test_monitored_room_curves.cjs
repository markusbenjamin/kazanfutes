const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const d3={mean:(rows,get)=>rows.reduce((sum,row)=>sum+get(row),0)/rows.length,
    extent:(rows,get)=>[Math.min(...rows.map(get)),Math.max(...rows.map(get))]};
const context=vm.createContext({console,d3});
const data=fs.readFileSync('docs/data.js','utf8');
vm.runInContext(data.slice(data.indexOf('const ROOM_TEMPERATURE_DISPLAY_STEP_HOURS'),data.indexOf('function drawPlot(')),context);
const helpers=fs.readFileSync('docs/codebase.js','utf8');
vm.runInContext(helpers.slice(helpers.indexOf('function calculateMovingAverage('),helpers.indexOf('function getUnixDay(')),context);
vm.runInContext(fs.readFileSync('docs/room_registry.js','utf8'),context);
vm.runInContext(`roomV2Name=()=> 'Teakonyha'; let result;
 function drawPlot(rows,options) {
   result={rows,options,drawn:calculateMovingAverage(rows,'temp',options.smoothing.left)};
 }
 const samples=Array.from({length:15},(_,hour)=>({h_of_day_frac:hour+1,temp:22-hour/7}));
 drawRoomV2MeasuredPlot({room_17_measurements:samples},{roomNumToPlot:17});`,context);
const run=source=>vm.runInContext(source,context);
assert.ok(run('result.drawn[0].temp-result.drawn.at(-1).temp')>1.5,
    'Sparse daily measurements must retain their cooling trend, not collapse to one average');
assert.equal(run('JSON.stringify(result.rows)'),run('JSON.stringify(prepareRoomTemperatureForDisplay(samples))'),
    'Single-room and overview curves use the same prepared temperature history');
assert.equal(run('result.rows.at(-1).temp'),20);
assert.equal(run('result.options.curveEndText.text'),'20.0 °C');
assert.equal(run('samples.length'),15,'Display processing must not mutate logged measurements');
run('drawRoomV2MeasuredPlot({},{roomNumToPlot:17})');
assert.equal(run('result.rows.length'),0);
assert.equal(run('result.options.curveEndText.show'),false);
console.log('Monitored room curves: sparse-day trend, shared processing, latest label, source preservation and empty history passed.');
