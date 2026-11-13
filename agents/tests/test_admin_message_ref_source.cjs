// Configured messages are independent of URL and heating conditions.
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
        update(value) {context.value = value;
            vm.runInContext('updateAdminMessage(value)', context);}};
}

for (const search of ['', '?ref_source=form', '?zoom=0.8&ref_source=form&preview=phase-summary-v1',
    '?ref_source=%66orm', '?demo=1', '?lang=en&demo=1&ref_source=form', '?ref_source=other']) {
    const page = fixture(search);
    for (const value of [undefined, null, '', ' \r\n\t ']) {
        page.update(value);
        assert.equal(page.box.hidden,true,'Empty messages stay hidden: '+search);
    }
    page.update('Admin message');
    assert.equal(page.box.hidden,false,'A configured message needs no condition: '+search);
    page.update('Admin message');
    assert.deepEqual(page.counts(),{focused:1,rendered:1},'Polling does not reformat or steal focus');
    vm.runInContext('dismissAdminMessage()', page.context);
    page.update('Admin message');
    assert.equal(page.box.hidden,true,'Manual dismissal survives polling');
    page.update('Changed message');
    assert.equal(page.box.hidden,false,'A changed message still shows');
    page.update('');
    assert.equal(page.box.hidden,true,'Clearing the configured message hides it');
    page.update('Admin message');
    assert.equal(page.box.hidden,false,'Clearing the config resets acknowledgement');
}
const legacy = fixture('');
vm.runInContext("updateAdminMessage('No boiler fault', false)",legacy.context);
assert.equal(legacy.box.hidden,false,'An obsolete false condition cannot suppress the message');
assert.equal(fixture('').box.hidden,true);
const reload=fixture('');reload.update('Admin message');
assert.equal(reload.box.hidden,false,'Reload makes an acknowledged message available again');
console.log('Admin messages: unconditional display across page modes, empty content, repeat polling, acknowledgement, changed messages and reload passed.');
