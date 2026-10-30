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
    const context = vm.createContext({URL, URLSearchParams, window, document: {
        activeElement: {}, getElementById(id) {
            return id === 'admin-message' ? box : id === 'admin-message-content' ? content : button;
        }
    }});
    vm.runInContext(source, context);
    context.formatAdminMessage = () => {rendered++;};
    return {context, box, window, counts: () => ({focused, rendered}),
        update(value) {context.value = value; vm.runInContext('updateAdminMessage(value)', context);}};
}

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
