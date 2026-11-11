const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('docs/data.js','utf8');
const styles = new Map();
const context = vm.createContext({console, Date, Number, Math,
    d3:{select:id=>({style(key,value){
        if (!styles.has(id)) styles.set(id,{});
        styles.get(id)[key]=value;return this;
    }}),interpolateRgb(){},scaleSequential:()=>({domain:()=>temp=>'temperature-'+temp})}
});
const helpers = fs.readFileSync('docs/codebase.js','utf8');
vm.runInContext(helpers.slice(helpers.indexOf('function dateFromTimestamp('),helpers.indexOf('function addTimeToDate(')), context);
vm.runInContext(fs.readFileSync('docs/dashboard_replay.js','utf8'),context);
vm.runInContext(source.slice(source.indexOf('function updateRoomColor('),source.indexOf('function updateCycleColor(')),context);
const run = code=>vm.runInContext(code,context);
const fill = ()=>styles.get('#room_10').fill;
run(`dashboardReplayTime = new Date(2026,10,4,12).getTime();`);
run(`updateRoomColor('room_10',20,'2026-11-04-11-59-00',{},false);`);
assert.equal(fill(),'temperature-20');
run(`updateRoomColor('room_10',26.4,'2026-09-09-20-14-24',{},false);`);
assert.equal(fill(),'rgba(31,31,32,0.8)','Nov 4 Trafóház must clear its old live colour for the September reading');
assert.equal(styles.get('#room_10')['fill-opacity'],'1');
for (const expression of [
 "null,'2026-11-04-11-59-00'", "20,null", "20,'invalid'", "20,'2026-11-11-11-59-00'",
 "20,'2026-11-04-09-59-59'"
]) {
 run(`updateRoomColor('room_10',21,'2026-11-04-11-59-00',{},false);`);
 run(`updateRoomColor('room_10',${expression},{},true);`);
 assert.equal(fill(),'rgba(31,31,32,0.8)','Unavailable timestamp or temperature clears colour: '+expression);
 assert.match(styles.get('#room_10').mask,/repeating-linear-gradient/,'Presence remains independent of missing temperature');
}
run(`updateRoomColor('room_10',0,'2026-11-04-10-00-00',{},false);`);
assert.equal(fill(),'temperature-0','Valid zero and the two-hour boundary are allowed');
run(`updateRoomColor('room_10',22,'2026-11-04-11-59-00',{},false);`);
assert.equal(fill(),'temperature-22','A fresh reading restores normal temperature colour');
console.log('Missing room temperature: stale Trafóház replay, null/invalid/future stamps, live-colour reset, freshness boundary, zero, presence independence and recovery passed.');
