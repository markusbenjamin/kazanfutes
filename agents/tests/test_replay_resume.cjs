const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const nodes = new Map();
const node = id => {
    if (!nodes.has(id)) {
        const classes = new Set();
        nodes.set(id,{hidden:true,disabled:true,value:'',textContent:'',style:{},
            classList:{contains:name=>classes.has(name),toggle(name){
                if (classes.has(name)) {classes.delete(name);return false;}
                classes.add(name);return true;
            }},setAttribute(){},focus(){},getBoundingClientRect:()=>id === 'general_infobox'
                ? {left:24,top:120,width:250,height:300} : {left:400,top:350,width:500,height:48}});
    }
    return nodes.get(id);
};
let loads = [], paints = 0, liveRefreshes = 0;
const context = vm.createContext({Date, Number, Math, Map, Object, console,
    document:{getElementById:node,querySelectorAll:()=>[]},window:{innerWidth:1200,innerHeight:800},cancelAnimationFrame(){},
    dayStamp:()=>'2026-11-11',dashboardPageOptions:()=>({language:'hu'}),
    elementToMainGraphSettingMapping:{room:{day:'2026-11-11'}},
    mainGraphDefaultSetting:{title:'all_rooms',day:'2026-11-11'},
    mainGraphSetting:{title:'all_rooms',day:'2026-11-11'},mainGraphContentLocked:false,
    getDataFromFirebase(){liveRefreshes++;},writeGasUsageToDial(){},writeCycleEnergyToMarkers(){},drawMainGraph(){}});
vm.runInContext(fs.readFileSync('docs/dashboard_replay.js','utf8'),context);
const run = source=>vm.runInContext(source,context);
context.updateReplayPane=()=>{};context.updateDashboardClock=()=>{};
context.replayPaint=()=>{paints++;};
context.loadReplayDay=day=>{loads.push(day);run(`replayLoadingDay='${day}'`);};
run('openReplayPane()');
assert.deepEqual(loads,['2026-11-11'],'First opening automatically requests today');
assert.equal(node('replay-pane').hidden,false);
assert.equal(node('replay-pane').classList.contains('replay-minimized'),true,'Clock opens the compact view');
assert.equal(node('replay-pane').style.left,'24px','Align the pane with the infobox left edge');
assert.equal(node('replay-pane').style.top,'64px','Position just above the infobox');
run('openReplayPane()');
assert.equal(loads.length,1,'Repeated clock clicks do not restart an in-flight load');
run(`replayLoadingDay=null; replayDay={day:'2026-11-04'};
 dashboardReplayTime=new Date(2026,10,4,12,34,56).getTime(); replayPlaying=true;
 replaySavedPlot={title:'all_rooms',day:'2026-11-11'};
 mainGraphSetting={title:'room_control_phase',day:'2026-11-04',roomNumToPlot:4};mainGraphContentLocked=true;`);
const cursor=run('dashboardReplayTime');
run('leaveReplay()');
assert.equal(run('dashboardReplayActive()'),false,'Closing returns the dashboard to live mode');
assert.equal(run('replayPlaying'),false);
assert.equal(node('replay-pane').hidden,true);
assert.equal(liveRefreshes,1);
assert.equal(context.mainGraphSetting.title,'all_rooms');
assert.equal(context.mainGraphSetting.day,'2026-11-11');
run(`mainGraphSetting={title:'weather_metrics',day:'2026-11-11'};openReplayPane();`);
assert.equal(loads.length,1,'Reopening a loaded replay needs no network request');
assert.equal(run('dashboardReplayTime'),cursor,'Resume at the exact last cursor, rather than midnight or current live time');
assert.equal(run('replayPlaying'),false,'Resume paused even when closing during playback');
assert.equal(context.mainGraphSetting.title,'room_control_phase','Restore the last replay plot');
assert.equal(context.mainGraphContentLocked,true);
assert.equal(node('replay-day').value,'2026-11-04');
assert.equal(node('replay-controls').disabled,false);
assert.equal(node('replay-pane').hidden,false);
assert.equal(paints,1);
run('leaveReplay()');
assert.equal(context.mainGraphSetting.title,'weather_metrics','Restore the current live view on the next close');
run('openReplayPane()');
assert.equal(run('dashboardReplayTime'),cursor,'Repeated close/open cycles preserve the cursor');
assert.equal(run('replayPlaying'),false);
console.log('Replay pane: automatic today load, in-flight reuse, close-to-live, exact paused resume, plot restoration and repeated reopening passed.');
