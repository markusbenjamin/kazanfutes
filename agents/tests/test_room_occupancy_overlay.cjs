const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../../docs/data.js'), 'utf8');
const render = source.slice(source.indexOf('function updateRoomColor('), source.indexOf('function updateCycleColor('));
const rooms = new Map();
const select = id => {
    if (!rooms.has(id)) rooms.set(id, new Map());
    return {style(key, value) {
        if (value === null) rooms.get(id).delete(key);
        else rooms.get(id).set(key, value);
        return this;
    }};
};
const context = vm.createContext({
    d3: {select, interpolateRgb: () => {}, scaleSequential: () => ({domain: () => temp => 'room-' + temp})},
    timePassedSince: age => age, dateFromTimestamp: age => age
});
vm.runInContext(render, context);
const update = (occupancy, age = 0, room = 'PK') => context.updateRoomColor(room, 21, age, {}, occupancy);
const styles = () => rooms.get('#PK');

for (const clear of [false, 0, null, undefined, -1, '0', 'false']) {
    update(true);
    assert.match(styles().get('mask'), /repeating-linear-gradient/);
    assert.equal(styles().get('mask'), styles().get('-webkit-mask'));
    update(clear);
    assert.equal(styles().has('mask'), false, 'clear/unknown presence removes the standard mask');
    assert.equal(styles().has('-webkit-mask'), false, 'clear/unknown presence removes the WebKit mask');
    assert.equal(styles().get('fill'), 'room-21', 'temperature colouring is unchanged');
}
update(1);
update(false, 121);
assert.equal(styles().has('mask'), false, 'stale temperature must not block clearing presence');
update(true, 121);
assert.ok(styles().has('mask'), 'fresh presence is independent of stale temperature');
update(null, 121);
assert.equal(styles().has('-webkit-mask'), false);
update(true, 0, 'Merce');
update(false);
assert.ok(rooms.get('#Merce').has('mask'), 'clearing one room does not change another');
update(false);
assert.equal(styles().has('mask'), false, 'repeated empty refreshes stay clear');
console.log('Occupancy overlay passed: on/off/unknown transitions, both mask properties, stale-temperature independence, room isolation and unchanged temperature colours.');
