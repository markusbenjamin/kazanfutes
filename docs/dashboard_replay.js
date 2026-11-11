// A display-only clock. Wall-clock timers/network freshness still use real time.
let dashboardReplayTime = null;
function dashboardNow() { return dashboardReplayTime === null ? new Date() : new Date(dashboardReplayTime); }
function dashboardReplayActive() { return dashboardReplayTime !== null; }

function replayAsOf(rows, stamp) {
    let low = 0, high = rows.length;
    while (low < high) {
        const middle = (low + high) >>> 1;
        if (rows[middle].timestamp <= stamp) low = middle + 1;
        else high = middle;
    }
    return low ? rows[low - 1] : null;
}

function replayIndex(rows) {
    const unique = new Map();
    (rows || []).forEach(row => { if (typeof row?.timestamp === 'string') unique.set(row.timestamp, row); });
    return [...unique.values()].sort((a,b) => a.timestamp.localeCompare(b.timestamp));
}

class DashboardReplayDay {
    constructor(day, history, plots, seeds = {}) {
        this.day = day;
        this.control = replayIndex([...history.seed, ...history.control]);
        this.schedule = replayIndex(history.schedule);
        this.plots = plots;
        this.streams = Object.fromEntries(Object.entries(plots).filter(([,rows]) => Array.isArray(rows))
            .map(([type, rows]) => [type, replayIndex([...(seeds[type] || []), ...rows])]));
        // Explicit day-level inference agreed for replay, independent of cursor time.
        this.enabled = [1,2,3,4].filter(cycle => history.control.some(row => row.state.pump_states?.[cycle] === 1));
    }
    latest(type, stamp) { return replayAsOf(this.streams[type] || [], stamp); }
    snapshot(date) {
        const stamp = livePlotStamp(date), control = replayAsOf(this.control, stamp);
        const state = control ? structuredClone(control.state) : {last_updated: this.day + '-00-00-00'};
        state.pump_states ||= Object.fromEntries([1,2,3,4].map(cycle => [cycle, null]));
        state.measured_temps ||= {}; state.sensor_last_updated ||= {}; state.room_states ||= {};
        const weather = this.latest('weather_station', stamp);
        state.weather_station = weather ? {...weather} : null;
        state.external_temp = weather && livePlotFresh(weather.timestamp, 300, date) ? weather.temperature_c : null;
        const probes = this.latest('radiator_temps', stamp), valves = this.latest('radiator_valves', stamp);
        const devices = {};
        Object.entries(probes?.probes || {}).forEach(([source, value]) => {
            const slash = source.indexOf('/');
            (devices[source.slice(0, slash)] ||= {})[source.slice(slash + 1)] = value;
        });
        state.radiator_probes = {timestamp: probes?.timestamp, devices};
        state.radiator_valves = {timestamp: valves?.timestamp, valves: valves?.valves || {}};
        // Per-circuit timestamps avoid pretending a missing/stale meter is fresh
        // just because another meter reported. Existing logger samples all four.
        state.heatmeters = {};
        for (const cycle of [1,2,3,4]) {
            const water = this.latest('cycle_' + cycle + '_water_temps', stamp);
            const heat = this.latest('cycle_' + cycle + '_heat_delivery', stamp);
            state.heatmeters[cycle] = {temp: water && livePlotFresh(water.timestamp,600,date) ? water.water_temp : null,
                return_temp: water && livePlotFresh(water.timestamp,600,date) ? water.return_temp : null,
                power: heat?.power_kw, flow: heat?.flow_m3h};
        }
        state.heatmeters.last_updated = stamp;
        const pumps = this.latest('pumps_power', stamp);
        state.pumps = {last_updated: pumps?.timestamp,
            power: Object.fromEntries([1,2,3,4].map(cycle => [cycle, pumps?.['pump_' + cycle + '_power'] ?? null]))};
        state.boiler_plugs = {};
        for (const source of ['boiler_1_plug','boiler_2_plug']) {
            const row = this.latest(source + '_power', stamp);
            if (row) state.boiler_plugs[source] = {timestamp: row.timestamp, power_w: row.power_w, reachable: true};
        }
        const gas = this.latest('gas_usage', stamp);
        state.gas = {dial_turn_secs: gas?.secs_since_last_turn ?? null};
        const rooms = Object.fromEntries(Object.keys(state.room_states).map(id => [id, {vote: state.room_states[id], reason: 'none'}]));
        return {system: {state, switch: {system: this.enabled.length ? 1 : 0,
            cycles: Object.fromEntries([1,2,3,4].map(cycle => [cycle, this.enabled.includes(cycle) ? 0 : -1]))},
            control: {rooms, cycles: state.pump_states, last_updated: state.last_updated, error: {error: false, where: ''}}},
            schedule: {last_updated: replayAsOf(this.schedule, stamp)?.timestamp || control?.timestamp || stamp,
                condensed_schedule: {}, request_lists: {}}, update: {override_rooms: {}}};
    }
    clip(type, date) {
        const rows = this.plots[type];
        if (!Array.isArray(rows)) {
            if (rows?.points) return {...rows, points: rows.points.filter(row => row.timestamp <= livePlotStamp(date))};
            return rows;
        }
        const stamp = livePlotStamp(date);
        return rows.filter(row => !row.timestamp || row.timestamp <= stamp);
    }
}

let replayDay = null, replayLatestLive = null, replayPlaying = false, replaySpeed = 5;
let replayLoadNumber = 0, replayFrame = 0, replayLastFrame = 0, replayLastPaint = 0, replayLastPlot = 0;
let replayWorker = null, replaySavedPlot = null, replayResumeState = null, replayLoadingDay = null;
const replayDayCache = new Map();

function replayText(hu, en) { return dashboardPageOptions().language === 'en' ? en : hu; }

function replayPlotPayload(payload) {
    if (!dashboardReplayActive()) return payload;
    const stamp = livePlotStamp(dashboardNow()), day = stamp.slice(0,10);
    const clip = value => {
        if (Array.isArray(value)) return value.filter(row => !row.timestamp || row.timestamp <= stamp);
        if (value?.points) return {...value, points: clip(value.points)};
        return value;
    };
    return Object.fromEntries(Object.entries(payload).map(([date, types]) => [date,
        date > day ? {} : date < day ? types : Object.fromEntries(Object.entries(types).map(([type, rows]) => [type, clip(rows)]))]));
}

function replaySyncPlotDay(day) {
    Object.values(elementToMainGraphSettingMapping).forEach(setting => { setting.day = day; });
    mainGraphDefaultSetting.day = day;
    mainGraphSetting = {...mainGraphSetting, day};
}

function navigateReplayDay(delta) {
    if (!dashboardReplayActive()) return false;
    const day = shiftedSelectorDay(replayDay.day, delta);
    if (day <= dayStamp(new Date())) {
        document.getElementById('replay-day').value = day;
        loadReplayDay(day);
    }
    return true;
}

function replayPaint(redrawPlot = true) {
    if (!replayDay || !dashboardReplayActive()) return;
    const date = dashboardNow(), stamp = livePlotStamp(date), day = replayDay.day;
    const gas = replayDay.latest('gas_usage', stamp);
    // Daily counters reset at midnight; yesterday's accumulated volume must not carry.
    const todayGas = gas?.timestamp.startsWith(day + '-') ? gas : null;
    currentGasTotal = todayGas?.burnt_volume ?? 0;
    currentGasUsageRate = gas && livePlotFresh(gas.timestamp,180,date) ? Math.round(gas.burn_rate_in_m3_per_h * 10) / 10 : 0;
    writeGasUsageToDial({[day]: {gas_usage: [{burnt_volume: currentGasTotal}]}}, true);
    const energy = Object.fromEntries([1,2,3,4].map(cycle => {
        const type = 'cycle_' + cycle + '_heat_delivery', row = replayDay.latest(type, stamp);
        return [type, row?.timestamp.startsWith(day + '-') ? [row] : [{energy_kwh: 0}]];
    }));
    writeCycleEnergyToMarkers({[day]: energy}, true);
    renderDashboardState(replayDay.snapshot(date), {replay: true});
    if (redrawPlot) { mainPlotLivePayload = null; drawMainGraph(); }
    updateDashboardClock(); updateReplayPane();
}

async function loadReplayDay(day) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || day > dayStamp(new Date())) return;
    const generation = ++replayLoadNumber;
    replayLoadingDay = day;
    pauseReplay();
    replayWorker?.terminate();
    const status = document.getElementById('replay-status');
    status.textContent = replayText('Napi adatok betöltése…', 'Loading daily data…');
    document.getElementById('replay-controls').disabled = true;
    updateReplayPane();
    try {
        let result = replayDayCache.get(day);
        if (!result) {
            const previous = shiftedSelectorDay(day, -1);
            const historyPromise = new Promise((resolve,reject) => {
                const worker = new Worker('replay_worker.js?v=20261111-replay2');
                replayWorker = worker;
                worker.onmessage = ({data}) => { worker.terminate(); data.error ? reject(Error(data.error)) : resolve(data); };
                worker.onerror = () => { worker.terminate(); reject(Error('Historical log loading failed')); };
                worker.postMessage({day, previous});
            });
            // Fetch using the normal chart loader/cache, including the same GitHub
            // paths used in production. Missing optional streams stay unavailable.
            const types = ['weather_station','external_temp','radiator_temps','radiator_valves','heating_state',
                'gas_usage','pumps_power','heating_demand','boiler_commands',
                'boiler_1_plug_power','boiler_2_plug_power',
                ...[1,2,3,4].flatMap(cycle => ['cycle_' + cycle + '_water_temps','cycle_' + cycle + '_heat_delivery']),
                ...allMeasuredRooms.flatMap(room => ['room_' + room + '_measurements'])];
            const seedTypes = ['weather_station','radiator_temps','radiator_valves','gas_usage','pumps_power',
                ...[1,2,3,4].map(cycle => 'cycle_' + cycle + '_water_temps')];
            const fetchType = (date,type) => new Promise(resolve => collectDataFromGitHub([{day:date,type}], data => resolve([type, data[date]?.[type]]), {unclipped:true}));
            const [history, plots, seeds] = await Promise.all([historyPromise,
                Promise.all(types.map(type => fetchType(day,type))),
                Promise.all(seedTypes.map(type => fetchType(previous,type)))]);
            result = new DashboardReplayDay(day, history, Object.fromEntries(plots.filter(([,rows]) => rows)),
                Object.fromEntries(seeds.map(([type,rows]) => [type, Array.isArray(rows) ? rows.slice(-1) : []])));
            replayDayCache.set(day, result);
            if (replayDayCache.size > 2) replayDayCache.delete(replayDayCache.keys().next().value);
        }
        if (generation !== replayLoadNumber) return;
        if (!dashboardReplayActive()) replaySavedPlot = {...mainGraphSetting};
        replayDay = result;
        replayResumeState = null;
        dashboardReplayTime = dateFromTimestamp(day + '-00-00-00').getTime();
        document.getElementById('admin-message').hidden = true;
        replaySyncPlotDay(day);
        document.getElementById('replay-controls').disabled = false;
        status.textContent = '';
        replayPaint();
    } catch (error) {
        if (generation !== replayLoadNumber) return;
        status.textContent = replayText('Ehhez a naphoz nem elérhető a napló.', 'The log is unavailable for this day.');
        console.error('Replay:', error);
    } finally {
        if (generation === replayLoadNumber) replayLoadingDay = null;
    }
}

function pauseReplay() {
    replayPlaying = false;
    cancelAnimationFrame(replayFrame);
    updateReplayPane();
}

function playReplay() {
    if (replayPlaying || !replayDay || !dashboardReplayActive()) return;
    replayPlaying = true; replayLastFrame = performance.now(); replayLastPaint = 0; replayLastPlot = 0;
    const tick = time => {
        if (!replayPlaying) return;
        // Clamp wall-clock pauses when the browser tab is backgrounded.
        const elapsed = Math.min(time - replayLastFrame, 1000);
        replayLastFrame = time;
        const end = dateFromTimestamp(replayDay.day + '-23-59-59').getTime();
        const available = Math.min(end, Date.now());
        dashboardReplayTime = Math.min(available, dashboardReplayTime + elapsed * replaySpeed * 60);
        if (time - replayLastPaint >= 250) {
            const plotDue = time - replayLastPlot >= 1000 || !replayLastPlot;
            replayPaint(plotDue); replayLastPaint = time;
            if (plotDue) replayLastPlot = time;
        }
        updateDashboardClock(); updateReplayPane();
        if (dashboardReplayTime >= available) { replayPaint(); pauseReplay(); return; }
        replayFrame = requestAnimationFrame(tick);
    };
    replayFrame = requestAnimationFrame(tick); updateReplayPane();
}

function seekReplay(seconds) {
    if (!replayDay) return;
    const start = dateFromTimestamp(replayDay.day + '-00-00-00').getTime();
    dashboardReplayTime = Math.min(Date.now(), start + Math.max(0, Math.min(86399, seconds)) * 1000);
    replayPaint();
}

function stopReplay() {
    pauseReplay();
    if (dashboardReplayActive()) seekReplay(0);
}

function restartReplay() {
    stopReplay();
    playReplay();
}

function leaveReplay() {
    if (replayDay && dashboardReplayActive()) {
        replayResumeState = {data: replayDay, time: dashboardReplayTime,
            plot: {...mainGraphSetting}, locked: mainGraphContentLocked};
    }
    ++replayLoadNumber; replayWorker?.terminate(); replayWorker = null;
    replayLoadingDay = null;
    pauseReplay(); dashboardReplayTime = null; replayDay = null;
    document.getElementById('replay-controls').disabled = true;
    document.getElementById('replay-status').textContent = '';
    replaySyncPlotDay(dayStamp(new Date()));
    if (replaySavedPlot) mainGraphSetting = {...replaySavedPlot};
    replaySavedPlot = null; mainPlotLivePayload = null;
    document.getElementById('replay-pane').hidden = true;
    if (replayLatestLive) renderDashboardState(replayLatestLive);
    getDataFromFirebase(); writeGasUsageToDial(); writeCycleEnergyToMarkers(); drawMainGraph();
    updateDashboardClock(); updateReplayPane();
}

function updateReplayPane() {
    const button = document.getElementById('replay-play');
    if (!button) return;
    const ready = dashboardReplayActive() && !!replayDay && !document.getElementById('replay-controls').disabled;
    button.disabled = !ready || replayPlaying;
    document.getElementById('replay-pause').disabled = !ready || !replayPlaying;
    document.getElementById('replay-stop').disabled = !ready;
    document.getElementById('replay-restart').disabled = !ready;
    document.getElementById('replay-speed').disabled = !ready;
    button.setAttribute('aria-pressed', String(replayPlaying));
    const now = dashboardNow();
    const date = replayDay?.day || replayLoadingDay || dayStamp(now);
    document.getElementById('replay-compact-date').textContent = dashboardPageOptions().language === 'en'
        ? date : date.replaceAll('-', '.') + '.';
    document.getElementById('replay-time').textContent = hourStamp(now, true);
    document.getElementById('replay-timeline').value = getFractionalHourOfDay(now) * 3600;
    updateReplayWeekday();
}

function updateReplayWeekday() {
    const day = document.getElementById('replay-day').value;
    document.getElementById('replay-next-day').disabled = !day || day >= dayStamp(new Date());
    const label = document.getElementById('replay-date-display');
    if (label.dataset.day === day) return;
    label.dataset.day = day;
    label.textContent = /^\d{4}-\d{2}-\d{2}$/.test(day)
        ? (dashboardPageOptions().language === 'en' ? day : day.replaceAll('-', '.') + '.')
            + ' (' + dashboardText(selectorWeekday(day)) + ')' : replayText('Dátum választása', 'Choose date');
}

function selectReplayDay(delta) {
    const input = document.getElementById('replay-day');
    const next = shiftedSelectorDay(input.value || dayStamp(new Date()), delta);
    if (next > dayStamp(new Date())) return;
    input.value = next;
    updateReplayWeekday();
}

function openReplayPane() {
    const pane = document.getElementById('replay-pane');
    pane.hidden = false;
    if (!pane.classList.contains('replay-minimized')) toggleReplayPaneSize();
    const date = document.getElementById('replay-day');
    if (!dashboardReplayActive() && replayResumeState) {
        replaySavedPlot = {...mainGraphSetting};
        replayDay = replayResumeState.data;
        dashboardReplayTime = replayResumeState.time;
        replayPlaying = false;
        replaySyncPlotDay(replayDay.day);
        mainGraphSetting = {...replayResumeState.plot};
        mainGraphContentLocked = replayResumeState.locked;
        date.value = replayDay.day;
        document.getElementById('replay-controls').disabled = false;
        document.getElementById('replay-status').textContent = '';
        document.getElementById('admin-message').hidden = true;
        replayPaint();
    } else if (!dashboardReplayActive() && !replayLoadingDay) {
        date.value = dayStamp(new Date());
        loadReplayDay(date.value);
    }
    date.max = dayStamp(new Date());
    updateReplayPane();
    const infobox = document.getElementById('general_infobox');
    if (infobox) {
        const anchor = infobox.getBoundingClientRect(), box = pane.getBoundingClientRect();
        pane.style.transform = 'none';
        pane.style.left = Math.max(0, Math.min(window.innerWidth - box.width, anchor.left)) + 'px';
        pane.style.top = Math.max(0, anchor.top - box.height - 8) + 'px';
    }
    (pane.classList.contains('replay-minimized') ? document.getElementById('replay-size') : date).focus({preventScroll:true});
}

function toggleReplayPaneSize() {
    const pane = document.getElementById('replay-pane'), box = pane.getBoundingClientRect();
    pane.style.transform = 'none'; pane.style.left = box.left + 'px'; pane.style.top = box.top + 'px';
    const minimized = pane.classList.toggle('replay-minimized');
    const button = document.getElementById('replay-size');
    const label = minimized ? replayText('Kibontás', 'Expand') : replayText('Kis méret', 'Minimize');
    button.setAttribute('aria-expanded', String(!minimized));
    button.setAttribute('aria-label', label); button.title = label;
    document.querySelectorAll('#replay-speed option').forEach(option => {
        option.textContent = minimized ? option.value + replayText(' p/mp', ' min/s') : replayText(option.dataset.hu, option.dataset.en);
    });
    const resized = pane.getBoundingClientRect();
    pane.style.left = Math.max(0,Math.min(window.innerWidth-resized.width,resized.left)) + 'px';
    pane.style.top = Math.max(0,Math.min(window.innerHeight-resized.height,resized.top)) + 'px';
}

function updateDashboardClock() {
    const face = document.getElementById('clock');
    const group = document.getElementById('dashboard-clock-hands');
    if (!face || !group) return;
    const now = dashboardNow(), box = face.getBBox(), x = box.x + box.width / 2, y = box.y + box.height / 2;
    const r = Math.min(box.width, box.height) * .42;
    const hand = (name, fraction, length) => {
        const angle = fraction * Math.PI * 2 - Math.PI / 2;
        const node = group.querySelector('[data-hand="' + name + '"]');
        node.setAttribute('x1',x); node.setAttribute('y1',y);
        node.setAttribute('x2',x + Math.cos(angle) * r * length); node.setAttribute('y2',y + Math.sin(angle) * r * length);
    };
    hand('hour', (now.getHours() % 12 + now.getMinutes() / 60) / 12, .57);
    hand('minute', (now.getMinutes() + now.getSeconds() / 60) / 60, .83);
    group.querySelector('circle').setAttribute('cx',x); group.querySelector('circle').setAttribute('cy',y);
    face.setAttribute('aria-label',replayText('Visszajátszás', 'Replay') + ' ' + hourStamp(now));
    updateReplayPane();
}

function initializeReplayClock() {
    const face = document.getElementById('clock');
    if (!face) return;
    face.style.stroke = 'black'; face.style.strokeOpacity = '1';
    face.style.fill = 'white'; face.style.fillOpacity = '1';
    face.style.cursor = 'pointer'; face.style.pointerEvents = 'all';
    face.setAttribute('role','button'); face.setAttribute('tabindex','0');
    const activate = event => { event.stopPropagation(); openReplayPane(); };
    face.addEventListener('click',activate);
    face.addEventListener('mousedown',event=>event.stopPropagation());
    face.addEventListener('touchstart',event=>event.stopPropagation(), {passive:true});
    face.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();activate(event);}});
    const svg = 'http://www.w3.org/2000/svg', group = document.createElementNS(svg,'g');
    group.id = 'dashboard-clock-hands'; group.style.pointerEvents = 'none';
    const box = face.getBBox(), x = box.x + box.width / 2, y = box.y + box.height / 2, r = Math.min(box.width,box.height) * .42;
    for (let i = 0; i < 12; i++) {
        const angle = i * Math.PI / 6;
        const line = document.createElementNS(svg,'line');
        Object.entries({x1:x+Math.sin(angle)*r*.92,y1:y-Math.cos(angle)*r*.92,x2:x+Math.sin(angle)*r,y2:y-Math.cos(angle)*r,
            stroke:'#777','stroke-width':r*.035}).forEach(([key,value])=>line.setAttribute(key,value)); group.append(line);
    }
    for (const name of ['hour','minute']) {
        const line = document.createElementNS(svg,'line');
        line.setAttribute('data-hand',name); line.setAttribute('stroke','black');
        line.setAttribute('stroke-width',r*(name === 'hour' ? .09 : .055)); line.setAttribute('stroke-linecap','round'); group.append(line);
    }
    const centre = document.createElementNS(svg,'circle'); centre.setAttribute('r',r*.09); centre.setAttribute('fill','black'); group.append(centre);
    face.parentNode.append(group);
    updateDashboardClock(); setInterval(updateDashboardClock,1000);
}

function initializeReplayPane() {
    const pane = document.getElementById('replay-pane');
    let drag = null;
    pane.addEventListener('pointerdown', event => {
        if (event.button !== 0 || event.target.closest('input, button, select, a')) return;
        const box = pane.getBoundingClientRect();
        drag = {id:event.pointerId, x:event.clientX - box.left, y:event.clientY - box.top};
        // Replace the initial centred positioning only when dragging starts.
        pane.style.transform = 'none'; pane.style.left = box.left + 'px'; pane.style.top = box.top + 'px';
        pane.setPointerCapture(event.pointerId); pane.classList.add('replay-dragging');
        event.preventDefault(); event.stopPropagation();
    });
    pane.addEventListener('pointermove', event => {
        if (!drag || event.pointerId !== drag.id) return;
        const box = pane.getBoundingClientRect();
        pane.style.left = Math.max(0, Math.min(window.innerWidth - box.width, event.clientX - drag.x)) + 'px';
        pane.style.top = Math.max(0, Math.min(window.innerHeight - box.height, event.clientY - drag.y)) + 'px';
    });
    const stopDragging = event => {
        if (!drag || event.pointerId !== drag.id) return;
        drag = null; pane.classList.remove('replay-dragging');
        if (pane.hasPointerCapture(event.pointerId)) pane.releasePointerCapture(event.pointerId);
    };
    pane.addEventListener('pointerup',stopDragging);
    pane.addEventListener('pointercancel',stopDragging);
    pane.addEventListener('lostpointercapture',stopDragging);
    window.addEventListener('resize', () => {
        if (!pane.style.left || pane.hidden) return;
        const box = pane.getBoundingClientRect();
        pane.style.left = Math.max(0, Math.min(window.innerWidth - box.width, box.left)) + 'px';
        pane.style.top = Math.max(0, Math.min(window.innerHeight - box.height, box.top)) + 'px';
    });
    pane.addEventListener('click',event=>event.stopPropagation());
    pane.addEventListener('keydown',event=>{if(event.key === 'Escape') leaveReplay();});
    document.getElementById('replay-close').addEventListener('click',()=>leaveReplay());
    document.getElementById('replay-size').addEventListener('click',toggleReplayPaneSize);
    document.getElementById('replay-load').addEventListener('click',()=>loadReplayDay(document.getElementById('replay-day').value));
    document.getElementById('replay-previous-day').addEventListener('click',()=>selectReplayDay(-1));
    document.getElementById('replay-next-day').addEventListener('click',()=>selectReplayDay(1));
    document.getElementById('replay-day').addEventListener('input',updateReplayWeekday);
    const dateInput = document.getElementById('replay-day');
    const openDatePicker = () => { if (typeof dateInput.showPicker === 'function') dateInput.showPicker(); };
    dateInput.addEventListener('click',openDatePicker);
    dateInput.addEventListener('keydown',event=>{
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openDatePicker(); }
    });
    dateInput.setAttribute('aria-label',replayText('Dátum', 'Date'));
    document.getElementById('replay-play').addEventListener('click',playReplay);
    document.getElementById('replay-pause').addEventListener('click',pauseReplay);
    document.getElementById('replay-stop').addEventListener('click',stopReplay);
    document.getElementById('replay-restart').addEventListener('click',restartReplay);
    document.getElementById('replay-timeline').addEventListener('input',event=>seekReplay(Number(event.target.value)));
    document.getElementById('replay-speed').addEventListener('change',event=>{replaySpeed=Number(event.target.value);});
    pane.querySelectorAll('[data-hu]').forEach(node=>{node.textContent=replayText(node.dataset.hu,node.dataset.en);});
    const labels = {play:['Lejátszás','Play'],pause:['Szünet','Pause'],stop:['Leállítás','Stop'],
        restart:['Újra az elejétől','Replay from start'],size:['Kis méret','Minimize'],close:['Bezárás','Close'],
        load:['Napi adatok betöltése','Load daily data'],
        'previous-day':['Előző nap','Previous day'],'next-day':['Következő nap','Next day']};
    Object.entries(labels).forEach(([id,label])=>{
        const button=document.getElementById('replay-'+id), text=replayText(...label);
        button.setAttribute('aria-label',text);button.title=text;
    });
}
