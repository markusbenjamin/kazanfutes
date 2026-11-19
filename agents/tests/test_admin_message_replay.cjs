const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const createContext=require('./dashboard_test_context.cjs');
for(const language of ['hu','en']) {
    let active=false,formats=0;
    const pane={hidden:true};
    const box={hidden:true,contains:()=>false,focus(){},addEventListener(){}};
    const button={addEventListener(){}};
    const content={scrollTop:0};
    const context=createContext({window:{location:{search:'?lang='+language}},
        dashboardReplayActive:()=>active,
        document:{activeElement:{},getElementById:id=>({'admin-message':box,'admin-message-content':content,
            'admin-message-ok':button,'admin-message-close':button,'replay-pane':pane})[id]}});
    vm.runInContext(fs.readFileSync('docs/admin_message.js','utf8'),context);
    context.formatAdminMessage=()=>formats++;
    const run=code=>vm.runInContext(code,context);
    run(`updateDashboardMessageConfig({admin_message:'Admin',admin_message_en:'Admin EN',admin_message_priority:3,
        boiler_fault_message:'Fault',boiler_fault_message_en:'Fault EN',boiler_fault_message_priority:2,
        rain_protection_message:'Rain',rain_protection_message_en:'Rain EN',rain_protection_message_priority:1})`);
    assert.equal(box.hidden,false);
    pane.hidden=false;
    run('renderDashboardMessage()');
    assert.equal(box.hidden,true,'opening the replay pane hides an already visible popup while loading');
    run("updateAdminMessage('Updated while loading')");
    assert.equal(box.hidden,true,'Sheet polling cannot reopen a popup during loading');
    active=true;
    const before=formats;
    run("updateAdminMessage('Updated during replay');updateDashboardWarnings({boilerError:true,rainProtection:true});renderDashboardMessage()");
    assert.equal(box.hidden,true,'playing or paused replay never shows admin/fault/rain popups');
    assert.equal(formats,before,'suppressed notices are not formatted or focused');
    run("refreshDashboardMessageLanguage('hu')");
    assert.equal(box.hidden,true,'language changes cannot reopen a popup');
    active=false;pane.hidden=true;
    run('renderDashboardMessage()');
    assert.equal(box.hidden,false,'returning live restores the latest unacknowledged admin message');
    run('dismissAdminMessage()');
    pane.hidden=false;active=true;
    run("updateAdminMessage('Updated during replay')");
    active=false;pane.hidden=true;
    run('renderDashboardMessage()');
    assert.equal(box.hidden,true,'replay does not clear an existing dismissal');
    run('updateDashboardWarnings({boilerError:true})');
    assert.equal(box.hidden,false);
    run('dismissAdminMessage()');
    pane.hidden=false;active=true;
    run('updateDashboardWarnings({});updateDashboardWarnings({boilerError:true,rainProtection:true})');
    active=false;pane.hidden=true;
    run('updateDashboardWarnings({boilerError:true})');
    assert.equal(box.hidden,true,'historical warning changes cannot reset a dismissed live fault occurrence');
}
console.log('Replay notices passed: immediate loading suppression, polling/language isolation, paused playback, live restoration and preserved admin/fault acknowledgement in both languages.');
