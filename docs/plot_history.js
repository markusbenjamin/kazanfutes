// Display-only context for continuous time-series plots. Daily counters and
// analytics keep their own calendar boundaries and aggregation windows.
const PLOT_HISTORY_HOURS = 4;

function plotPreviousDay(day) {
    const date = new Date(day + 'T12:00:00Z');
    date.setUTCDate(date.getUTCDate() - 1);
    return date.toISOString().slice(0,10);
}

function plotHistoryTypesForSetting(setting) {
    const {title,metric} = setting;
    if (title === 'weather_metrics' && ['rain','direction'].includes(metric)) return [];
    if (title === 'room_metrics' && metric === 'occupancy') return [];
    if (title === 'boiler_metrics' && metric !== 'temperature') return [];
    if (title === 'cycle_water_temp' && metric === 'power') return [];
    if (!['room_plot','all_rooms','room_metrics','radiator','cycle_water_temp',
        'boiler_metrics','weather_metrics','external_temp','heating_state'].includes(title)) return [];
    return (setting.types || []).filter(type => /^room_\d+_(measurements|environment|valve_state|set_temps)$/.test(type)
        || /^cycle_\d+_water_temps$/.test(type) || ['external_temp','weather_station','pumps_power','radiator_temps','radiator_valves'].includes(type)
        || title === 'heating_state' && type === 'heating_state'
        || title === 'cycle_water_temp' && metric === 'flow' && type.endsWith('_heat_delivery'));
}

function addPlotHistory(rows, previous) {
    if (!Array.isArray(rows)) return rows;
    const history = (previous || []).filter(row => Number.isFinite(row.h_of_day_frac)
        && row.h_of_day_frac >= 24 - PLOT_HISTORY_HOURS && row.h_of_day_frac < 24)
        .map(row => ({...row,h_of_day_frac:row.h_of_day_frac - 24,plot_history:true}));
    return [...history,...rows.filter(row => !row.plot_history)];
}

function trimPlotHistory(rows, xKey, yKey, domain, replayHour = null) {
    if (xKey !== 'h_of_day_frac' || !rows.some(row => row[xKey] < domain[0])) return rows;
    const visible = rows.filter(row => row[xKey] >= domain[0] && row[xKey] <= domain[1]);
    const previous = rows.filter(row => row[xKey] < domain[0] && Number.isFinite(row[yKey])).at(-1);
    if (!previous || domain[0] - previous[xKey] > 2) return visible;
    const first = visible[0];
    if (first && first[xKey] > domain[0] && first[xKey] - previous[xKey] <= 2 && Number.isFinite(first[yKey])) {
        const fraction = (domain[0] - previous[xKey]) / (first[xKey] - previous[xKey]);
        return [{...previous,[xKey]:domain[0],[yKey]:previous[yKey] + (first[yKey]-previous[yKey])*fraction},...visible];
    }
    // A fresh preceding room reading can seed midnight before today's first
    // measurement arrives. Never show yesterday's curve for an empty live day.
    if (!first && yKey === 'temp' && Number.isFinite(replayHour) && replayHour - previous[xKey] <= 2)
        return [{...previous,[xKey]:domain[0]}];
    return visible;
}
