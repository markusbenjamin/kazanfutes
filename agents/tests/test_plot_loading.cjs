const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const createContext = require('./dashboard_test_context.cjs');

for (const language of ['hu', 'en']) {
    let now = 0, nextTimer = 0;
    const timers = new Map();
    const context = createContext({window: {location: {search: '?lang=' + language}},
        mainGraphSetting: {title: 'room_control_phase', roomNumToPlot: 2, day: '2026-11-02'},
        setTimeout(callback, delay) {timers.set(++nextTimer, {at: now + delay, callback});return nextTimer;},
        clearTimeout(id) {timers.delete(id);}});
    const run = code => vm.runInContext(code, context);
    const advance = ms => {
        now += ms;
        for (const [id, timer] of timers) if (timer.at <= now) {timers.delete(id);timer.callback();}
    };
    const label = () => ({element: {isConnected: true}, attrs: {}, value: '',
        node() {return this.element;}, attr(key, value) {this.attrs[key] = value;return this;},
        text(value) {this.value = value;return this;}});
    const loading = language === 'en' ? 'Loading data.' : 'Adatok betöltése.';
    const unavailable = language === 'en' ? 'No valid phase points for this day.' : 'Az adott napra nincs érvényes fázispont.';
    context.label = label();
    assert.equal(run('beginMainPlotLoading(mainGraphSetting)'), true);
    run("setPlotEmptyMessage(label, 'Az adott napra nincs érvényes fázispont.')");
    assert.equal(context.label.value, loading);
    assert.equal(context.label.attrs['data-plot-status'], 'loading');
    advance(9999);
    assert.equal(context.label.value, loading);
    // Polling, an empty result, or a redraw must not restart the deadline.
    assert.equal(run('beginMainPlotLoading({...mainGraphSetting})'), false);
    advance(1);
    assert.equal(context.label.value, unavailable);
    assert.equal(context.label.attrs['data-plot-status'], 'empty');
    context.again = label();
    run("setPlotEmptyMessage(again, 'Az adott napra nincs érvényes fázispont.')");
    assert.equal(context.again.value, unavailable);

    // Changing date/filter/room starts a fresh grace period, cancels old timers.
    context.old = context.label;
    run("mainGraphSetting = {...mainGraphSetting, day: '2026-11-01'}; beginMainPlotLoading(mainGraphSetting)");
    context.label = label();
    run("setPlotEmptyMessage(label, 'Az adott napra nincs érvényes fázispont.')");
    advance(3000);
    context.oldLoading = context.label;
    run("mainGraphSetting = {...mainGraphSetting, presenceMode: 'occupied'}; beginMainPlotLoading(mainGraphSetting)");
    context.label = label();
    run("setPlotEmptyMessage(label, 'Jelenlétkor nincs érvényes fázisadat.')");
    advance(7000);
    assert.equal(context.label.value, loading, 'old query deadline cannot affect the new view');
    assert.equal(context.oldLoading.value, loading, 'cancelled timers do not alter an old plot');
    // Data arrival removes the old status node. Timeout must not redraw/overwrite it.
    context.label.element.isConnected = false;
    context.label.value = 'curve has replaced this node';
    advance(3000);
    assert.equal(context.label.value, 'curve has replaced this node');
    context.late = label();
    run("setPlotEmptyMessage(late, 'Jelenlétkor nincs érvényes fázisadat.')");
    assert.equal(context.late.attrs['data-plot-status'], 'empty');
    run('mainGraphSetting = {...mainGraphSetting, roomNumToPlot: 3}; beginMainPlotLoading(mainGraphSetting)');
    context.late = label();
    run("setPlotEmptyMessage(late, 'Jelenlétkor nincs érvényes fázisadat.')");
    assert.equal(context.late.value, loading);
    // A known missing probe mapping is configuration, not a pending download.
    context.config = label();
    run("setPlotEmptyMessage(config, 'A szobához nincs radiátor-hőmérő rendelve.')");
    assert.equal(context.config.attrs['data-plot-status'], 'empty');
    assert.notEqual(context.config.value, loading);

    // Exercise the actual drawMainGraph gateway with a hanging/empty request.
    const source = fs.readFileSync(path.resolve(__dirname, '../../docs/data.js'), 'utf8');
    vm.runInContext(source.slice(source.indexOf('function drawMainGraph('), source.indexOf('function rescueMainGraph(')), context);
    const draws = [], loads = [];
    Object.assign(context, {isRoomControlView: () => false, clearMainGraphs() {},
        drawPlot: (data, options) => {draws.push({data, options});},
        collectDataFromGitHub: (requests, callback) => loads.push({requests, callback})});
    run("mainGraphSetting = {title:'external_temp',day:'2026-10-31',types:['external_temp']}; drawMainGraph()");
    assert.equal(draws[0].data, undefined, 'new hover immediately renders loading, not the previous plot');
    assert.equal(loads.length, 1);
    loads[0].callback({});
    assert.equal(draws.at(-1).options.emptyMessage, 'Az adott napra nincs adat.');
}
console.log('Plot loading passed in both languages: ten-second grace, stable deadlines, query isolation, disconnected/valid-plot safety, immediate loading and normal empty results.');
