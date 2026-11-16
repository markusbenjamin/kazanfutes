const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const createContext=require('./dashboard_test_context.cjs');
const source=fs.readFileSync('docs/admin_message.js','utf8');
function page(language) {
    const renders=[],events={};
    const box={hidden:true,focus(){},contains:()=>false,addEventListener(name,callback){events[name]=callback;}};
    const ok={addEventListener(name,callback){events['ok:'+name]=callback;}};
    const close={addEventListener(name,callback){events['close:'+name]=callback;}};
    const content={scrollTop:0};
    const context=createContext({window:{location:{search:'?lang='+language}},
        document:{activeElement:{},getElementById:id=>({'admin-message':box,'admin-message-content':content,
            'admin-message-ok':ok,'admin-message-close':close})[id]}});
    vm.runInContext(source,context);
    context.formatAdminMessage=message=>renders.push(message);
    const run=code=>vm.runInContext(code,context);
    return {box,renders,events,run,
        config(value){context.value=value;run('updateDashboardMessageConfig(value)');},
        admin(value){context.value=value;run('updateAdminMessage(value)');},
        warn(boilerError=false,rainProtection=false){context.value={boilerError,rainProtection};run('updateDashboardWarnings(value)');}};
}
for (const language of ['hu','en']) {
    const view=page(language),boiler=language==='hu'?'kazán hiba!':'boiler fault!',rain=language==='hu'?'esővédelem!':'rain protection!';
    const config={boiler_fault_message:'kazán hiba!',boiler_fault_message_en:'boiler fault!',boiler_fault_message_priority:2,
        rain_protection_message:'esővédelem!',rain_protection_message_en:'rain protection!',rain_protection_message_priority:1,
        admin_message_priority:3};
    view.config(config);
    view.admin('Admin A');assert.equal(view.renders.at(-1),'Admin A');
    view.warn(true);assert.equal(view.renders.at(-1),boiler);
    assert.equal(view.box.hidden,false);
    const count=view.renders.length;
    view.admin('Admin B');view.warn(true);
    assert.equal(view.renders.length,count,'Admin polling cannot overwrite or repeatedly redraw the error');
    view.events['ok:click']();assert.equal(view.box.hidden,true);
    view.warn(true);view.admin('Admin B');
    assert.equal(view.box.hidden,true,'A dismissed error stays silent and still defers the admin message');
    view.warn(true,true);assert.equal(view.renders.at(-1),rain);
    assert.equal(view.box.hidden,false,'A higher-priority error is a new notification');
    view.events['close:click']();view.warn(true,true);
    assert.equal(view.box.hidden,true,'X dismisses the current rain occurrence');
    view.warn(true,false);
    assert.equal(view.box.hidden,true,'An already acknowledged, uninterrupted boiler error remains acknowledged');
    view.warn();assert.equal(view.renders.at(-1),'Admin B');
    assert.equal(view.box.hidden,false,'Latest pending admin content returns when errors clear');
    view.events.keydown({key:'Escape'});assert.equal(view.box.hidden,true);
    view.warn(true);assert.equal(view.renders.at(-1),boiler);
    assert.equal(view.box.hidden,false,'Clearing then recurring resets error acknowledgement');
    view.warn();assert.equal(view.box.hidden,true,'Error display does not forget admin acknowledgement');
    view.admin('Admin C');assert.equal(view.box.hidden,false);
    view.warn(true,true);assert.equal(view.renders.at(-1),rain);
    view.events['close:click']();view.warn(true,false);
    assert.equal(view.renders.at(-1),boiler);
    assert.equal(view.box.hidden,false,'After rain clears, an unacknowledged boiler error appears');
    view.admin('');assert.equal(view.box.hidden,false,'An empty admin field cannot suppress an active error');
    view.warn();assert.equal(view.box.hidden,true);
    const reload=page(language);reload.config(config);reload.warn(true);
    assert.equal(reload.box.hidden,false,'Reload starts without old error acknowledgement');
}
const view=page('hu');
let config={admin_message:'Admin from Sheet',admin_message_priority:' 1 ',
    boiler_fault_message:'Boiler text from Sheet',boiler_fault_message_priority:'2',
    rain_protection_message:'Rain text from Sheet',rain_protection_message_priority:'3'};
view.config(config);view.warn(true,true);
assert.equal(view.renders.at(-1),'Admin from Sheet','Configured admin priority can supersede either error');
config={...config,boiler_fault_message_priority:'0'};view.config(config);
assert.equal(view.renders.at(-1),'Boiler text from Sheet','Numeric priorities can reverse the former fixed ordering');
view.events['ok:click']();view.config(config);
assert.equal(view.box.hidden,true);
config={...config,boiler_fault_message:'Updated boiler text'};view.config(config);
assert.equal(view.box.hidden,false,'Changed configured text can show during the same error occurrence');
assert.equal(view.renders.at(-1),'Updated boiler text');
config={...config,boiler_fault_message:' ',rain_protection_message_priority:-1};view.config(config);
assert.equal(view.renders.at(-1),'Rain text from Sheet','Empty higher-priority messages do not suppress nonempty candidates');
view.warn(false,false);assert.equal(view.renders.at(-1),'Admin from Sheet','Inactive errors never display regardless of priority');
for (const value of ['',undefined,null,'invalid',Infinity]) {
    view.config({...config,admin_message_priority:value,rain_protection_message_priority:1});view.warn(false,true);
    assert.equal(view.renders.at(-1),'Rain text from Sheet','Missing or invalid priorities rank last');
}
view.config({});assert.equal(view.box.hidden,true,'No configured text means no hardcoded error fallback');
const english=page('en');english.config(config);english.warn(true,true);
assert.equal(english.box.hidden,true,'English messages require their corresponding configured English text');
english.config({...config,rain_protection_message_en:'Configured rain notice'});
assert.equal(english.renders.at(-1),'Configured rain notice');
console.log('Shared post-it messages: configured text and numeric priority, both languages, empty fields, Ok/X/Escape, occurrence acknowledgement, changed content and deferred messages passed.');
