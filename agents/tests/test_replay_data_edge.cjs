const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const nodes = new Map(), renders = [], colours = [];
const node = id => {
    if (!nodes.has(id)) nodes.set(id,{disabled:false,value:'2026-11-11',dataset:{},textContent:'',setAttribute(){}});
    return nodes.get(id);
};
let frame = null, cancelled = 0;
const context = vm.createContext({Date, Number, Math, Map, Set, Object, structuredClone, console,
    document:{getElementById:node},performance:{now:()=>0},
    requestAnimationFrame:callback=>{frame=callback;return 1;},cancelAnimationFrame(){cancelled++;frame=null;},
    currentGasTotal:0,currentGasUsageRate:0,
    writeGasUsageToDial(){},writeCycleEnergyToMarkers(){},drawMainGraph(){},updateDashboardClock(){},
    renderDashboardState(payload){renders.push({time:vm.runInContext('dashboardReplayTime',context),payload});},
    dashboardPageOptions:()=>({language:'hu'}),dashboardText:text=>text,
    selectorWeekday:()=>'szerda',dayStamp:()=>'2026-11-11',
    hourStamp:date=>[date.getHours(),date.getMinutes(),date.getSeconds()].map(v=>String(v).padStart(2,'0')).join(':'),
    getFractionalHourOfDay:date=>date.getHours()+date.getMinutes()/60+date.getSeconds()/3600});
for (const file of ['live_plot_data.js','replay_temperatures.js','dashboard_replay.js'])
    vm.runInContext(fs.readFileSync('docs/'+file,'utf8'),context);
context.paintReplayTemperatureColours=(timeline,system,date)=>colours.push(date.getTime());
context.updateDashboardClock=()=>{};
const helpers = fs.readFileSync('docs/codebase.js','utf8');
vm.runInContext(helpers.slice(helpers.indexOf('function dateFromTimestamp('),helpers.indexOf('function addTimeToDate(')),context);
const run = code=>vm.runInContext(code,context);
run(`
const stamp = '2026-11-11-09-02-00';
const history = {seed:[{timestamp:'2026-11-10-23-59-00',state:{}}],schedule:[],control:[
 {timestamp:'2026-11-11-09-00-00',state:{last_updated:'2026-11-11-09-00-00',pump_states:{1:1}}},
 {timestamp:stamp,state:{last_updated:stamp,pump_states:{1:1}}}]};
const weather = [{timestamp:'2026-11-11-09-05-00',temperature_c:12}];
replayDay = new DashboardReplayDay('2026-11-11',history,{weather_station:weather});
dashboardReplayTime = livePlotDate('2026-11-11-00-00-00').getTime();
`);
const end = run('livePlotDate(stamp).getTime()');
assert.equal(run('replayDay.endTime'),end,'The last selected-day controller snapshot defines the loaded edge');
assert.equal(run("new DashboardReplayDay('2026-11-11',{seed:history.seed,schedule:[],control:[]},{}).endTime"),run("livePlotDate('2026-11-11-00-00-00').getTime()"),'A previous-day seed cannot extend the selected day');
run('seekReplay(86399)');
assert.equal(run('dashboardReplayTime'),end,'End key and seeking cannot pass the loaded edge');
assert.equal(run('replayPlaying'),false);
assert.equal(renders.at(-1).time,end);
assert.equal(renders.at(-1).payload.system.state.last_updated,'2026-11-11-09-02-00');
assert.equal(run('dashboardReplayTime-livePlotDate(replayLastSystem.state.last_updated).getTime()'),0,'Final infobox is rendered at its data timestamp, never stale wall time');
assert.equal(node('replay-timeline').max,32520);
assert.equal(node('replay-timeline').value,32520);
assert.equal(node('replay-play').disabled,true,'Play is disabled at the edge; restart remains available');
assert.equal(node('replay-restart').disabled,false);
assert.equal(node('replay-time').textContent,'09:02:00');
run('seekReplay(32519);playReplay()');
assert.equal(run('replayPlaying'),true);
assert.equal(typeof frame,'function');
const tick=frame;
tick(500);
assert.equal(run('dashboardReplayTime'),end,'A playback frame overshooting the edge is clamped exactly');
assert.equal(run('replayPlaying'),false,'Playback pauses automatically at the loaded edge');
assert.equal(frame,null,'No animation frame remains scheduled at the end');
assert.ok(cancelled>0);
assert.equal(renders.at(-1).time,end,'The final full render is not skipped between quarter-second updates');
assert.equal(colours.at(-1),end);
run('seekReplay(-20)');
assert.equal(run('dashboardNow().getHours()'),0,'The lower seeking boundary is still midnight');
assert.equal(node('replay-play').disabled,false);
run('playReplay()');
const paintCount=renders.length, colourCount=colours.length;
frame(300); // One full render.
frame(350); // A lightweight colour frame between full renders.
assert.equal(renders.length,paintCount+1);
assert.equal(colours.length,colourCount+2,'Colours update between full dashboard renders');
run('pauseReplay()');
console.log('Replay data edge: fixed loaded endpoint, bounded seeking/timeline, exact final infobox render, automatic pause, restart and lightweight colour cadence passed.');
