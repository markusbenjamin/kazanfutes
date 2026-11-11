// Replay-only estimates for SVG colours, flame strength and the gas dial.
// Never write these values into the
// recorded snapshot, chart streams, infobox calculations or boiler-fault input.
class ReplayTemperatureSeries {
    constructor(rows, maxGapSeconds) {
        const unique = new Map();
        for (const row of rows) {
            const date = livePlotDate(row.timestamp);
            if (date) unique.set(date.getTime(), {...row, time: date.getTime()});
        }
        this.rows = [...unique.values()].sort((a,b) => a.time - b.time);
        this.maxGap = maxGapSeconds * 1000;
    }
    at(time) {
        let low = 0, high = this.rows.length;
        while (low < high) {
            const middle = (low + high) >>> 1;
            if (this.rows[middle].time <= time) low = middle + 1;
            else high = middle;
        }
        const left = this.rows[low - 1], right = this.rows[low];
        if (!left || !Number.isFinite(left.value) || time - left.time > this.maxGap) return null;
        if (!right || !Number.isFinite(right.value) || right.breakBefore || right.time - left.time > this.maxGap) return left.value;
        return left.value + (right.value - left.value) * (time - left.time) / (right.time - left.time);
    }
}

function replayRoomObservations(control) {
    const rooms = new Map(), previous = new Map();
    for (const row of control) {
        const state = row.state || {}, observedAt = livePlotDate(row.timestamp);
        if (!observedAt) continue;
        for (const id of new Set([...previous.keys(), ...Object.keys(state.measured_temps || {})])) {
            const value = state.measured_temps?.[id], stamp = state.sensor_last_updated?.[id];
            const available = Number.isFinite(value) && livePlotFresh(stamp, 7200, observedAt);
            const key = available ? stamp + ':' + value : 'unavailable';
            if (previous.get(id) === key) continue;
            previous.set(id,key);
            if (!rooms.has(id)) rooms.set(id,[]);
            const readings = rooms.get(id), last = readings.at(-1);
            // Controller logs repeat a held sensor reading every minute. Use
            // actual observation times, not a one-minute ramp at its next poll.
            // An inconsistent/backwards source stamp is a discrete source change.
            const breakBefore = available && last && stamp <= last.timestamp;
            readings.push({timestamp: available && !breakBefore ? stamp : row.timestamp,
                value: available ? value : null, breakBefore: !!breakBefore});
        }
    }
    return rooms;
}

class ReplayTemperatureTimeline {
    constructor(control, streams) {
        this.rooms = new Map([...replayRoomObservations(control)]
            .map(([id,rows]) => [id,new ReplayTemperatureSeries(rows,7200)]));
        this.water = new Map([1,2,3,4].map(cycle => [cycle,new ReplayTemperatureSeries(
            (streams['cycle_' + cycle + '_water_temps'] || []).map(row => ({timestamp:row.timestamp,
                value:Number.isFinite(row.water_temp) && row.water_temp > 0 && row.water_temp < 100 ? row.water_temp : null})),600)]));
        const rows = streams.radiator_temps || [];
        const sources = [...new Set(rows.flatMap(row => Object.keys(row.probes || {})))];
        this.probes = new Map(sources.map(source => [source,new ReplayTemperatureSeries(rows.map(row =>
            ({timestamp:row.timestamp,value:row.probes?.[source] ?? null})),300)]));
        this.outdoor = new ReplayTemperatureSeries((streams.weather_station || []).map(row =>
            ({timestamp:row.timestamp,value:row.temperature_c})),300);
        this.gas = new ReplayTemperatureSeries((streams.gas_usage || []).map(row =>
            ({timestamp:row.timestamp,value:Number.isFinite(row.burn_rate_in_m3_per_h)
                && row.burn_rate_in_m3_per_h >= 0 ? row.burn_rate_in_m3_per_h : null})),180);
    }
}

function replayVisualGasUsageRate() {
    const value = dashboardReplayActive() ? replayDay?.temperatures?.gas.at(dashboardNow().getTime()) : null;
    return Number.isFinite(value) ? value : currentGasUsageRate;
}

function paintReplayTemperatureColours(timeline, system, date) {
    const time = date.getTime(), state = system.state;
    const visual = {...system,state:{...state,measured_temps:{...state.measured_temps},
        heatmeters:{...state.heatmeters},weather_station:state.weather_station ? {...state.weather_station} : null}};
    for (const [id,room] of Object.entries(roomsDataAndState)) {
        const value = timeline.rooms.get(id)?.at(time);
        if (Number.isFinite(state.measured_temps?.[id]) && livePlotFresh(state.sensor_last_updated?.[id],7200,date)
            && Number.isFinite(value)) visual.state.measured_temps[id] = value;
        updateRoomColor(room.roomID,visual.state.measured_temps[id],state.sensor_last_updated?.[id],{},room.occupancy);
    }
    for (const cycle of [1,2,3,4]) {
        const value = timeline.water.get(cycle)?.at(time), meter = state.heatmeters?.[cycle];
        if (Number.isFinite(meter?.temp) && Number.isFinite(value)) visual.state.heatmeters[cycle] = {...meter,temp:value};
        // Pump switches remain discrete; stopped pipes retain their usual blue.
        updateCycleColor(cycle,state.pump_states?.[cycle],cycleSupplyTemperature(visual,cycle));
    }
    const outdoor = timeline.outdoor.at(time);
    if (visual.state.weather_station && livePlotFresh(state.weather_station.timestamp,300,date) && Number.isFinite(outdoor))
        visual.state.weather_station.temperature_c = outdoor;
    updateAmbientAreas(visual);
    radiatorTargets.forEach(target => {
        const actual = radiatorLiveValues(target,date);
        const mean = Number.isFinite(actual.temperature)
            ? radiatorMean(target.probes.map(source => timeline.probes.get(source)?.at(time))) : null;
        const values = {...actual,temperature:Number.isFinite(mean) ? mean : actual.temperature};
        const colour = radiatorElementColor(target,values,visual), node = d3.select('#'+target.id);
        // Interaction/availability checks stay on the normal snapshot cadence.
        node.style('fill',colour);
        node.selectAll('*').style('fill',colour);
    });
}
