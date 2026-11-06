const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const page = fs.readFileSync('docs/send_via_qr_code.html','utf8');
assert.doesNotMatch(page, /<script\b|<iframe\b|<form\b|http-equiv|script\.google\.com|onload\s*=/i,
    'old QR URLs must land on a static page with no submission or automatic navigation');
assert.match(page,/QR-kódos fűtéskérés megszűnt/);

const source = fs.readFileSync('docs/data.js','utf8');
assert.doesNotMatch(source,/override_rooms_qr/,'QR writes must not change dashboard notifications');
const context = vm.createContext({URLSearchParams,window:{location:{search:''}},console:{log(){}},getIsMobile:()=>false});
vm.runInContext(source.slice(source.indexOf('function extractURLParams('),source.indexOf('function getIsMobile(')),context);
for (const [search, expected] of [['?ref_source=qr',false],['?ref_source=form',true],['',false]]) {
    context.window.location.search=search;
    vm.runInContext('extractURLParams()',context);
    assert.equal(context.fromRequest,expected);
}

const notification = source.slice(source.indexOf('            let timeSinceLastRequest ='), source.indexOf('            externalTemp ='));
context.updateJSON={override_rooms:{last_update_timestamp:'form-timestamp',room_name:'PK'}};
Object.defineProperty(context.updateJSON,'override_rooms_qr',{get(){throw Error('deprecated QR notification accessed');}});
Object.assign(context,{timePassedSince:()=>5,dateFromTimestamp:value=>value,hourStamp:()=> '10:00',
    fromRequest:true,initialLockDone:false,mainGraphContentLocked:false,
    elementToMainGraphSettingMapping:{PK:{roomNumToPlot:3}}});
vm.runInContext(notification,context);
assert.equal(vm.runInContext('requestOrigin',context),'form');
assert.equal(vm.runInContext('requestTarget',context),'PK');
assert.equal(context.mainGraphSetting.roomNumToPlot,3,'normal form referral still selects its room');
console.log('QR retirement passed: inert entry page, no QR notification effects, no QR referral lock, normal forms unchanged.');
