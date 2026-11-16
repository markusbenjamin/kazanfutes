const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({Date,Number,Math,Object,Map,Set,Array,console,
    d3:{mean:(rows,read)=>{const values=rows.map(read).filter(Number.isFinite);return values.reduce((sum,value)=>sum+value,0)/values.length;}}});
vm.runInContext(fs.readFileSync('docs/plot_history.js','utf8'),context);
const source=fs.readFileSync('docs/codebase.js','utf8'),start=source.indexOf('function calculateMovingAverage(');
vm.runInContext(source.slice(start,source.indexOf('\nfunction ',start+1)),context);
const evaluate=code=>JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.prior=[19,20,22,23.9].map(h_of_day_frac=>({h_of_day_frac,temp:18,timestamp:'2026-11-15-23-54-00'}));
context.current=[{h_of_day_frac:.1,temp:20,timestamp:'2026-11-16-00-06-00'}];
const before=JSON.stringify([context.prior,context.current]);
assert.deepEqual(evaluate('addPlotHistory(current,prior).map(row=>row.h_of_day_frac)'),[-4,-2,-.10000000000000142,.1]);
assert.equal(JSON.stringify([context.prior,context.current]),before,'history is display-only; cached source rows stay unchanged');
assert.equal(evaluate("plotPreviousDay('2026-03-01')"),'2026-02-28');
assert.deepEqual(evaluate("plotHistoryTypesForSetting({title:'boiler_metrics',metric:'demand',types:['heating_demand']})"),[]);
assert.deepEqual(evaluate("plotHistoryTypesForSetting({title:'weather_metrics',metric:'rain',types:['weather_station']})"),[]);
assert.deepEqual(evaluate("plotHistoryTypesForSetting({title:'weather_metrics',metric:'direction',types:['weather_station']})"),[]);
assert.deepEqual(evaluate("plotHistoryTypesForSetting({title:'room_metrics',metric:'occupancy',types:['room_1_environment']})"),[]);
assert.deepEqual(evaluate("plotHistoryTypesForSetting({title:'all_rooms',types:['room_1_measurements','gas_usage','heating_state']})"),['room_1_measurements']);
context.short=[18,19,20,21].map((temp,index)=>({h_of_day_frac:index/60,temp}));
const causal=evaluate("calculateMovingAverage(short,'temp',25,true)");
assert.deepEqual(causal.map(row=>row.temp),[18,18.5,19,19.5],'short replay histories do not collapse to one flat moving mean');
context.longer=[...context.short,{h_of_day_frac:1,temp:40}];
assert.deepEqual(evaluate("calculateMovingAverage(longer,'temp',25,true).slice(0,4)"),causal,
    'new replay samples never rewrite previously smoothed values');
context.padded=[{h_of_day_frac:-.1,temp:18},{h_of_day_frac:.1,temp:20}];
assert.deepEqual(evaluate("trimPlotHistory(padded,'h_of_day_frac','temp',[0,24])"),
    [{h_of_day_frac:0,temp:19},{h_of_day_frac:.1,temp:20}],'smoothing context is trimmed at midnight, with an interpolated boundary');
context.padded=[{h_of_day_frac:-.1,temp:18}];
assert.deepEqual(evaluate("trimPlotHistory(padded,'h_of_day_frac','temp',[0,24])"),[],'previous-only live days do not acquire a fake curve');
assert.deepEqual(evaluate("trimPlotHistory(padded,'h_of_day_frac','temp',[0,24],0)"),[{h_of_day_frac:0,temp:18}]);
context.padded=[{h_of_day_frac:-3,temp:18}];
assert.deepEqual(evaluate("trimPlotHistory(padded,'h_of_day_frac','temp',[0,24],0)"),[],'stale previous-day temperatures stay absent');

const dataSource=fs.readFileSync('docs/data.js','utf8'),collectorStart=dataSource.indexOf('function collectDataFromGitHub(');
vm.runInContext(dataSource.slice(dataSource.indexOf('const ROOM_TEMPERATURE_DISPLAY_STEP_HOURS'),
    dataSource.indexOf('function drawPlot(')),context);
context.dashboardReplayActive=()=>true;
context.sparse=[{h_of_day_frac:-.6,temp:18},{h_of_day_frac:.6,temp:20}];
assert.equal(evaluate('prepareRoomTemperatureForDisplay(sparse).find(row=>row.h_of_day_frac===0).temp'),18,
    'replay resampling holds the preceding measurement rather than retrospectively interpolating towards a later reading');
context.dashboardReplayActive=()=>false;
assert.equal(evaluate('prepareRoomTemperatureForDisplay(sparse).find(row=>row.h_of_day_frac===0).temp'),19);
vm.runInContext(dataSource.slice(collectorStart,dataSource.indexOf('function dataToCollectGenerator(',collectorStart)),context);
const day='2026-11-16',previous='2026-11-15',stamp=new Date().toISOString();
context.loadedData={[day]:{room_1_measurements:{timestamp:stamp,data:[
    {h_of_day_frac:.1,temp:20,timestamp:day+'-00-06-00'},
    {h_of_day_frac:10,temp:30,timestamp:day+'-10-00-00'}]},gas_usage:{timestamp:stamp,data:[{h_of_day_frac:.1,burnt_volume:1}]}},
    [previous]:{room_1_measurements:{timestamp:stamp,data:[{h_of_day_frac:23.9,temp:18,timestamp:previous+'-23-54-00'}]}}};
context.dataExpiry=5;context.dashboardReplayActive=()=>true;
context.replayPlotPayload=payload=>Object.fromEntries(Object.entries(payload).map(([day,types])=>[day,
    Object.fromEntries(Object.entries(types).map(([type,rows])=>[type,rows?.filter(row=>row.h_of_day_frac<=.1)]))]));
context.fetchJSONEndpoint=()=>{throw Error('cached history must not cause a network request');};
context.collected=null;context.capture=payload=>context.collected=payload;
vm.runInContext(`collectDataFromGitHub([{day:'${day}',type:'room_1_measurements'},{day:'${day}',type:'gas_usage'}],capture,
    {historyTypes:['room_1_measurements']})`,context);
assert.deepEqual(Object.keys(context.collected),[day],'the previous day is context, not another displayed day');
assert.equal(context.collected[day].room_1_measurements.length,2,'history survives clipping but future replay readings do not');
assert.equal(context.collected[day].room_1_measurements[0].plot_history,true);
assert.equal(context.collected[day].gas_usage.length,1,'daily totals do not inherit yesterday’s counter');
console.log('Plot history passed: stream policy, midnight clipping, cache reuse, causal replay smoothing, future isolation and daily resets.');
