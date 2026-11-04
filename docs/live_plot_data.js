// Display-only live endpoints. Never mutate the archived/cached chart streams.
function livePlotDate(stamp) {
    if (typeof stamp !== 'string' || !/^\d{4}(?:-\d{2}){5}$/.test(stamp)) return null;
    const [year, month, day, hour, minute, second] = stamp.split('-').map(Number);
    const date = new Date(year, month - 1, day, hour, minute, second);
    return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day
        && date.getHours() === hour && date.getMinutes() === minute && date.getSeconds() === second ? date : null;
}

function livePlotStamp(date) {
    return [date.getFullYear(), date.getMonth() + 1, date.getDate(), date.getHours(), date.getMinutes(), date.getSeconds()]
        .map((value, index) => index ? String(value).padStart(2, '0') : String(value)).join('-');
}

function livePlotFresh(stamp, seconds, now) {
    const date = livePlotDate(stamp);
    const age = date ? (now - date) / 1000 : NaN;
    return Number.isFinite(age) && age >= -30 && age <= seconds;
}

function livePlotNumber(value, minimum = -Infinity, maximum = Infinity) {
    return Number.isFinite(value) && value >= minimum && value <= maximum ? value : undefined;
}

function withLivePlotReadings(payload, setting, system, now = new Date()) {
    const stamp = livePlotStamp(now), day = stamp.slice(0, 10);
    if (setting.day !== day || !system?.state || setting.title.startsWith('room_control_') || setting.title === 'boiler_kpi') return payload;
    const state = system.state, data = {...payload[day]}, result = {...payload, [day]: data};
    const requested = type => Object.hasOwn(data, type) || setting.types?.includes(type);
    const hour = now.getHours() + now.getMinutes() / 60 + now.getSeconds() / 3600;
    const add = (type, fields, observed, age) => {
        if (!requested(type) || !livePlotFresh(observed, age, now)) return;
        const rows = data[type];
        if (!Array.isArray(rows)) return;
        // A live value extends loaded history; it must never create a curve.
        // Gate each channel/source separately (e.g. supply history is not return history).
        const history = rows.filter(row => row?.live !== true && Number.isFinite(row?.h_of_day_frac)
            && row.h_of_day_frac >= 0 && row.h_of_day_frac < hour);
        const known = {};
        Object.entries(fields).forEach(([key, value]) => {
            if (value === undefined) return;
            if (value !== null && typeof value === 'object') {
                const sources = Object.fromEntries(Object.entries(value).filter(([source]) =>
                    history.some(row => Number.isFinite(row[key]?.[source]))));
                if (Object.keys(sources).length) known[key] = sources;
            } else if (history.some(row => Number.isFinite(row[key]))) known[key] = value;
        });
        if (!Object.keys(known).length) return;
        const latest = rows.reduce((last, row) => Number.isFinite(row?.h_of_day_frac)
            && (!last || row.h_of_day_frac > last.h_of_day_frac) ? row : last, null);
        // Never append out of order or replace a later archived observation with an older snapshot.
        if (latest && (latest.h_of_day_frac >= hour || livePlotDate(latest.timestamp) > livePlotDate(observed))) return;
        data[type] = [...rows, {timestamp: stamp, h_of_day_frac: hour, ...known,
            live: true, source_timestamp: observed}];
    };
    const controlFresh = livePlotFresh(state.last_updated, 180, now);
    if (controlFresh) {
        for (const room of Object.keys(state.measured_temps || {})) {
            const temp = livePlotFresh(state.sensor_last_updated?.[room], 7200, now)
                ? livePlotNumber(state.measured_temps[room], -40, 60) : undefined;
            const hum = livePlotFresh(state.humidity_last_updated?.[room], 7200, now)
                ? livePlotNumber(state.measured_humidity?.[room], 0, 100) : undefined;
            add('room_' + room + '_measurements', {temp, hum}, state.last_updated, 180);
            // Keep the room's mean opening, not a guessed radiator/TRV association.
            const snapshot = state.radiator_valves;
            const ids = system.setup?.rooms?.[room]?.thermostats;
            const valves = snapshot && typeof ids === 'string' ? ids.split(';').map(id => snapshot.valves?.[id])
                : !snapshot ? state.valve_states?.[room] : null;
            const values = (valves || []).filter(value => livePlotNumber(value, 0, 100) !== undefined);
            if (values.length) add('room_' + room + '_valve_state',
                {valve: values.reduce((sum, value) => sum + value, 0) / values.length / 100},
                snapshot?.timestamp || state.last_updated, snapshot ? 600 : 180);
        }
        if ([1,2,3,4].every(cycle => [0,1].includes(state.pump_states?.[cycle])))
            add('heating_state', {cycle_states: {...state.pump_states}}, state.last_updated, 180);
    }
    const meters = state.heatmeters;
    for (const cycle of [1,2,3,4]) {
        const meter = meters?.[cycle];
        if (!meter) continue;
        const water_temp = livePlotNumber(meter.temp, .001, 99.999);
        const return_temp = livePlotNumber(meter.return_temp, .001, 99.999);
        const flow_m3h = livePlotNumber(meter.flow, 0);
        let power_kw = livePlotNumber(meter.power, 0);
        if (power_kw > 0) {
            const expected = 1.163 * flow_m3h * (water_temp - return_temp);
            if (!(flow_m3h > .005 && water_temp > return_temp && Number.isFinite(expected)
                && Math.abs(power_kw - expected) <= Math.max(2, .3 * expected))) power_kw = undefined;
        }
        add('cycle_' + cycle + '_water_temps', {water_temp, return_temp}, meters.last_updated, 180);
        add('cycle_' + cycle + '_heat_delivery', {flow_m3h, power_kw}, meters.last_updated, 180);
    }
    const pumps = state.pumps;
    add('pumps_power', Object.fromEntries([1,2,3,4].map(cycle =>
        ['pump_' + cycle + '_power', livePlotNumber(pumps?.power?.[cycle], 0)])), pumps?.last_updated, 180);
    const probes = state.radiator_probes;
    if (probes?.devices) {
        const values = {};
        Object.entries(probes.devices).forEach(([device, readings]) => Object.entries(readings || {}).forEach(([probe, value]) => {
            values[device + '/' + probe] = livePlotNumber(value, -40, 125) ?? null;
        }));
        if (Object.values(values).some(Number.isFinite)) add('radiator_temps', {probes: values}, probes.timestamp, 300);
    }
    if (state.radiator_valves?.valves) add('radiator_valves', {valves: {...state.radiator_valves.valves}}, state.radiator_valves.timestamp, 600);
    Object.entries(state.boiler_plugs || {}).forEach(([source, reading]) => {
        if (reading?.reachable === true) add(source + '_power', {power_w: livePlotNumber(reading.power_w, 0)}, reading.timestamp, 180);
    });
    const weather = state.weather_station;
    if (weather && !['rain','direction'].includes(setting.metric)) {
        const fields = ['temperature_c','humidity_pct','dewpoint_c','wind_speed_m_s','gust_speed_m_s',
            'illuminance_lux','uv_index','pressure_hpa'];
        add('weather_station', Object.fromEntries(fields.map(key => [key, livePlotNumber(weather[key])])), weather.timestamp, 300);
        add('external_temp', {external_temp: livePlotNumber(weather.temperature_c)}, weather.timestamp, 300);
    }
    return result;
}

let mainPlotLivePayload;

// Live readings have already passed the source freshness/validity checks above.
// Extend only that final display tail; keep all archived gap boundaries intact.
function joinLivePlotTail(segments) {
    const tail = segments.at(-1);
    if (segments.length < 2 || tail[0]?.live !== true) return segments;
    const previous = segments.at(-2);
    if (!(tail[0].h_of_day_frac > previous.at(-1).h_of_day_frac)) return segments;
    return [...segments.slice(0, -2), [...previous, ...tail]];
}

function refreshMainPlotLiveEndpoint() {
    if (mainPlotLivePayload?.setting === mainGraphSetting)
        drawMainGraph(mainPlotLivePayload.data);
}
