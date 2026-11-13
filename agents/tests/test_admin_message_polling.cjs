const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const createContext = require('./dashboard_test_context.cjs');
const source = fs.readFileSync('docs/data.js','utf8');
const polling = source.slice(source.indexOf('function getDataFromFirebase('),source.indexOf('function renderDashboardState('));

async function main() {
    for (const language of ['hu','en']) for (const replay of [false,true]) for (const heating of [0,1]) {
        let rendered=0;
        const messages=[];
        const payload={system:{switch:{system:heating},dashboard:{admin_message:'Üzenet',admin_message_en:'Notice'}}};
        const context=createContext({window:{location:{search:'?lang='+language+'&demo=1&ref_source=form'}},
            fetchJSONEndpoint:()=>Promise.resolve(payload),dashboardReplayActive:()=>replay,
            updateAdminMessage:value=>messages.push(value),renderDashboardState:()=>{rendered++;},
            replayLatestLive:null,console});
        vm.runInContext(polling,context);
        vm.runInContext('getDataFromFirebase()',context);
        await new Promise(setImmediate);
        assert.deepEqual(messages,[language==='hu'?'Üzenet':'Notice'],'Polling displays the live notice regardless of heating, page mode or replay');
        assert.equal(rendered,replay?0:1,'Replay still protects the historical dashboard from live-state rendering');
        assert.equal(context.replayLatestLive,payload);
    }
    console.log('Admin polling: both languages, heating on/off, demo/form URLs and live notices during replay passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
