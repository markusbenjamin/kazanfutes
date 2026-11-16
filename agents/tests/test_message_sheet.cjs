const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const csv='key,value\nadmin_message,"Hello, everyone\nSecond line"\nadmin_message_priority,3';
const rows=[['key','value'],['admin_message','Hello, everyone\nSecond line'],['admin_message_priority','3'],
    ['rain_protection_message','Rain text'],['rain_protection_message_priority','1'],
    ['boiler_fault_message','Boiler text'],['boiler_fault_message_priority','2'],['unrelated_setting','ignored']];
const updates=[],requests=[],timers=new Map(),listeners={};
let handler,interval,token=0;
const context=vm.createContext({Date,Number,Object,Array,AbortController,
    console:{warn(){}},document:{addEventListener:(name,callback)=>listeners[name]=callback},
    setTimeout:callback=>{timers.set(++token,callback);return token;},clearTimeout:id=>timers.delete(id),
    setInterval:(callback,period)=>interval={callback,period},
    fetch:(url,options)=>{requests.push({url,options});return handler(options);},
    d3:{csvParseRows:text=>{assert.equal(text,csv,'Pass quoted multiline CSV to the existing D3 parser intact');return context.rows;}},
    updateDashboardMessageConfig:config=>updates.push(JSON.parse(JSON.stringify(config)))});
context.rows=rows;
vm.runInContext(fs.readFileSync('docs/message_sheet.js','utf8'),context);
const run=code=>vm.runInContext(code,context);
const response=(body=csv,type='text/csv')=>({ok:true,headers:{get:()=>type},text:async()=>body});
async function main(){
    let resolve;
    handler=()=>new Promise(callback=>resolve=callback);
    const first=run('refreshDashboardMessageSheet()'),second=run('refreshDashboardMessageSheet()');
    assert.equal(first,second,'One in-flight request even when refreshes overlap');
    assert.equal(requests.length,1);
    assert.ok(requests[0].url.startsWith('https://docs.google.com/spreadsheets/d/1sXoPC301Wurbm7yW5A956dlFEJcwM-fIb090fKOxROw/export?format=csv'));
    assert.equal(requests[0].options.credentials,'omit','Direct public read uses no account credentials');
    assert.equal(requests[0].options.cache,'no-store');
    resolve(response());assert.equal(await first,true);
    assert.equal(updates[0].admin_message,'Hello, everyone\nSecond line');
    assert.equal(updates[0].boiler_fault_message_priority,'2');
    assert.equal(updates[0].rain_protection_message_priority,'1');
    assert.equal(updates[0].admin_message_en,'');
    assert.equal(updates[0].unrelated_setting,undefined);
    assert.equal(timers.size,0);
    for (const failure of [()=>Promise.resolve({ok:false,status:401}),
        ()=>Promise.resolve(response('<html>Sign in</html>','text/html')),()=>Promise.reject(Error('offline'))]){
        handler=failure;assert.equal(await run('refreshDashboardMessageSheet()'),false);
        assert.equal(updates.length,1,'A failed Sheet read never clears last successful messages or acknowledgement');
    }
    handler=options=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('timeout'))));
    const pending=run('refreshDashboardMessageSheet()');
    [...timers.values()][0]();assert.equal(await pending,false,'A hung request times out');
    assert.equal(updates.length,1);
    context.rows=[['admin_message',''],['rain_protection_message',''],['boiler_fault_message','']];
    handler=async()=>response();
    assert.equal(await run('refreshDashboardMessageSheet()'),true);
    assert.equal(Object.values(updates.at(-1)).every(value=>value===''),true,'A successful empty config clears all messages');
    context.rows=[['setting','value'],['unrelated','x']];
    assert.equal(await run('refreshDashboardMessageSheet()'),false,'Unexpected data cannot replace the config');
    const count=updates.length;
    context.rows=rows;handler=async()=>response();
    listeners.DOMContentLoaded();
    assert.equal(interval.period,30000,'Read on load and every 30 seconds');
    await run('dashboardMessageSheetRequest');
    assert.equal(updates.length,count+1);
    assert.equal(timers.size,0);
    console.log('Direct Sheet messages: public CSV source, multiline content, whitelisted fields, priority values, polling, request coalescing, failed reads, timeout and recovery passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
