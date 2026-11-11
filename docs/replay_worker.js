// Read existing published control logs off the UI thread. Retain snapshots,
// not the much larger diagnostic/PID log. No new logging or preview API.
const REPLAY_LOG_ROOT = 'https://raw.githubusercontent.com/markusbenjamin/kazanfutes/main/data/logs/';

async function replayLog(day, relative, select, lastOnly = false) {
    const today = new Date().toLocaleDateString('en-CA', {timeZone: 'Europe/Budapest'});
    let response = await fetch(REPLAY_LOG_ROOT + relative + '.' + day);
    if (!response.ok && day === today) response = await fetch(REPLAY_LOG_ROOT + relative);
    if (!response.ok) throw Error('Missing historical log: ' + day);
    const reader = response.body.getReader(), decoder = new TextDecoder();
    const rows = new Map();
    let tail = '', last = null;
    const consume = line => {
        let row;
        try { row = JSON.parse(line); } catch { return; } // Incomplete final log line is harmless.
        if (!row?.timestamp?.startsWith(day + '-') || !select(row)) return;
        if (lastOnly) { if (!last || row.timestamp >= last.timestamp) last = row; }
        else rows.set(row.timestamp, row);
    };
    while (true) {
        const {value, done} = await reader.read();
        tail += decoder.decode(value, {stream: !done});
        const lines = tail.split('\n');
        tail = lines.pop();
        lines.forEach(consume);
        if (done) break;
    }
    if (tail) consume(tail);
    return lastOnly ? last ? [last] : [] : [...rows.values()].sort((a,b) => a.timestamp.localeCompare(b.timestamp));
}

self.onmessage = async ({data: {day, previous}}) => {
    const stateKeys = ['measured_temps', 'measured_humidity', 'sensor_last_updated', 'humidity_last_updated',
        'occupancy', 'set_temps', 'set_temps_interp', 'valve_states', 'room_states', 'pump_states', 'boiler_state', 'mode'];
    const snapshots = async (date, lastOnly) => (await replayLog(date,
        'service_execution/heating_control/heating_control.json', row => row.measured_temps && row.pump_states, lastOnly))
        .map(row => ({timestamp: row.timestamp, state: Object.fromEntries(
            [...stateKeys.filter(key => Object.hasOwn(row, key)).map(key => [key, row[key]]), ['last_updated', row.timestamp]])}));
    try {
        const results = await Promise.allSettled([snapshots(day, false), snapshots(previous, true),
            replayLog(day, 'service_execution/schedule_and_config_updater/schedule_and_config_updater.json',
                row => row.success_export_condensed_schedule_locally === true)]);
        if (results[0].status !== 'fulfilled' || !results[0].value.length) throw Error('No control snapshots for ' + day);
        self.postMessage({control: results[0].value,
            seed: results[1].status === 'fulfilled' ? results[1].value : [],
            schedule: results[2].status === 'fulfilled' ? results[2].value.map(row => ({timestamp: row.timestamp})) : []});
    } catch (error) { self.postMessage({error: error.message}); }
};
