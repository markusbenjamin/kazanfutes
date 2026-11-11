const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const script = fs.readFileSync('docs/replay_worker.js','utf8');
const day = '2026-11-10', previous = '2026-11-09';
const state = (stamp,temp) => ({timestamp:stamp,measured_temps:{1:temp},pump_states:{1:1},room_states:{1:1}});
const logs = {
 [day]: [JSON.stringify({timestamp:day+'-00-00-00',PID_state:{unused:'large diagnostic'}}),
  JSON.stringify(state(day+'-00-01-00',20)), 'malformed', JSON.stringify(state(day+'-00-02-00',21)),
  JSON.stringify(state(day+'-00-01-00',20.5)), JSON.stringify(state('2026-11-11-00-00-00',99))].join('\n'),
 [previous]: [JSON.stringify(state(previous+'-23-58-00',18)), JSON.stringify(state(previous+'-23-59-00',19))].join('\n')
};
const urls = [], self = {postMessage(value){this.result=value;}};
const context = vm.createContext({console, Date, Map, Object, TextDecoder, self,
 fetch:async url => {
  urls.push(url);
  let text = url.includes('schedule_and_config_updater') ? JSON.stringify({timestamp:day+'-00-00-30',success_export_condensed_schedule_locally:true})
   : url.endsWith('.'+day) ? logs[day] : logs[previous];
  const bytes = new TextEncoder().encode(text);
  let cursor = 0;
  return {ok:true,body:{getReader:()=>({read:async()=>{
   if(cursor === bytes.length) return {done:true};
   const next = Math.min(bytes.length,cursor+17), value=bytes.slice(cursor,next);cursor=next;return {value,done:false};
  }})}};
 }});
vm.runInContext(script, context);
(async()=>{
 await self.onmessage({data:{day,previous}});
 assert.equal(self.result.error,undefined);
 assert.equal(self.result.control.length,2,'Only complete control snapshots are retained');
 assert.equal(self.result.control[0].state.measured_temps[1],20.5,'The later duplicate replaces its earlier value');
 assert.equal(self.result.control[1].state.measured_temps[1],21);
 assert.equal(self.result.seed.length,1,'Only the last previous-day snapshot is kept');
 assert.equal(self.result.seed[0].state.measured_temps[1],19);
 assert.equal(self.result.schedule[0].timestamp,day+'-00-00-30');
 assert(urls.every(url=>url.startsWith('https://raw.githubusercontent.com/markusbenjamin/kazanfutes/main/data/logs/')));
 console.log('Replay worker: fragmented NDJSON, malformed lines, duplicate timestamps, date filtering, midnight seed and GitHub-only reads passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
