const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const createContext = require('./dashboard_test_context.cjs');
const source = fs.readFileSync('docs/data.js','utf8');
const polling = source.slice(source.indexOf('function getDataFromFirebase('),source.indexOf('function renderDashboardState('));

async function main() {
    for (const language of ['hu','en']) for (const replay of [false,true]) for (const heating of [0,1]) {
        let rendered=0;
        const messages=[];
        const config={admin_message:'Üzenet',admin_message_en:'Notice',admin_message_priority:'1',
            rain_protection_message:'Eső',rain_protection_message_priority:'3',
            boiler_fault_message:'Kazán',boiler_fault_message_priority:'2'};
        const payload={system:{switch:{system:heating},dashboard:config}};
        const context=createContext({window:{location:{search:'?lang='+language+'&demo=1&ref_source=form'}},
            fetchJSONEndpoint:()=>Promise.resolve(payload),dashboardReplayActive:()=>replay,
            updateDashboardMessageConfig:value=>messages.push(value),renderDashboardState:()=>{rendered++;},
            replayLatestLive:null,console});
        vm.runInContext(polling,context);
        vm.runInContext('getDataFromFirebase()',context);
        await new Promise(setImmediate);
        assert.deepEqual(messages,[],'Firebase must never overwrite message text and priorities read directly from the Sheet');
        assert.equal(rendered,replay?0:1,'Replay still protects the historical dashboard from live-state rendering');
        assert.equal(context.replayLatestLive,payload);
    }
    console.log('Message source isolation: Firebase cannot overwrite Sheet text/priorities; live/replay rendering remains independent in both languages.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
