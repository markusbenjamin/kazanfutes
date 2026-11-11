// URL gating without live Firebase/Sheet traffic or browser dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../docs/admin_message.js'), 'utf8');

function fixture(search) {
    let focused = 0, rendered = 0;
    const box = {hidden: true, contains: () => false, focus() {focused++;}, addEventListener() {}};
    const content = {scrollTop: 0};
    const button = {addEventListener() {}};
    const window = {location: {search}};
    const context = require('./dashboard_test_context.cjs')({URL, URLSearchParams, window, document: {
        activeElement: {}, getElementById(id) {
            return id === 'admin-message' ? box : id === 'admin-message-content' ? content : button;
        }
    }});
    vm.runInContext(source, context);
    context.formatAdminMessage = () => {rendered++;};
    return {context, box, window, counts: () => ({focused, rendered}),
        update(value, condition) {context.value = value; context.condition = arguments.length > 1 ? condition : true;
            vm.runInContext('updateAdminMessage(value, condition)', context);}};
}

const gated = fixture('');
for (const condition of [false, null, undefined, 0, 1, 'True', 'true']) {
    gated.update('Boiler message', condition);
    assert.equal(gated.box.hidden,true,'Only an explicitly true condition permits the message');
}
assert.deepEqual(gated.counts(),{focused:0,rendered:0});
vm.runInContext("updateAdminMessage('Boiler message')",gated.context);
assert.equal(gated.box.hidden,true,'An omitted condition must not show the message');
gated.update('Boiler message',true);
assert.equal(gated.box.hidden,false,'Boiler fault shows the configured message');
gated.update('Boiler message',false);
assert.equal(gated.box.hidden,true,'Fault recovery hides the message immediately');
gated.update('Boiler message',true);
assert.equal(gated.box.hidden,false,'Condition-based hiding does not acknowledge the message');
vm.runInContext('dismissAdminMessage()',gated.context);
gated.update('Boiler message',false);
gated.update('Boiler message',true);
assert.equal(gated.box.hidden,true,'Manual dismissal still survives polling and condition changes');
gated.update('Changed boiler message',false);
assert.equal(gated.box.hidden,true);
gated.update('Changed boiler message',true);
assert.equal(gated.box.hidden,false,'A changed message can show during a fault');
gated.update('',true);
assert.equal(gated.box.hidden,true,'Empty messages remain suppressed during a fault');

for (const search of ['?ref_source=form', '?zoom=0.8&ref_source=form&preview=phase-summary-v1', '?ref_source=%66orm']) {
    const page = fixture(search);
    for (const value of ['Admin message', 'Admin message', 'Changed message', '', null]) {
        page.update(value);
        assert.equal(page.box.hidden, true, search);
    }
    assert.deepEqual(page.counts(), {focused: 0, rendered: 0}, 'suppressed messages never render or take focus');
    page.box.hidden = false;
    page.update('New update');
    assert.equal(page.box.hidden, true, 'polling also hides an already visible message');
    page.window.location.search = '';
    page.update('Admin message');
    assert.equal(page.box.hidden, false, 'URL suppression does not acknowledge the message');
}
for (const search of ['', '?ref_source=other', '?ref_source=', '?ref_source=Form', '?other=ref_source%3Dform']) {
    const page = fixture(search);
    page.update('Admin message');
    assert.equal(page.box.hidden, false, 'ordinary URLs still show messages: ' + search);
    vm.runInContext('dismissAdminMessage()', page.context);
    page.update('Admin message');
    assert.equal(page.box.hidden, true, 'normal dismissal still survives polling');
    page.update('Changed message');
    assert.equal(page.box.hidden, false, 'changed messages still show');
    assert.deepEqual(page.counts(), {focused: 2, rendered: 2});
}
console.log('Admin message URL gating passed: form referrals suppressed across polling, other URLs and dismissal unchanged.');
