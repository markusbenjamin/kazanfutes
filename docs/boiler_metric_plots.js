// Ctrl+click boiler details; the ordinary hover and Alt+click KPI stay separate.
const BOILER_METRICS = {
    demand: {label: 'instant hőigény', key: 'demand_kw', axis: 'hőigény (kW)', unit: ' kW', color: 'rgb(230,130,0)'},
    temperature: {label: 'átlagos fűtővíz hőm.', key: 'water_temp', axis: '°C', unit: '°C', color: 'rgb(200,0,0)'}
};
let boilerMetricSelection = 'demand';

function createBoilerMetricPlotSetting(day = dayStamp(), metric = boilerMetricSelection) {
    if (!BOILER_METRICS[metric]) metric = 'demand';
    return {title: 'boiler_metrics', day, metric, conditionals: [],
        types: ['heating_state', ...(metric === 'demand' ? ['heating_demand'] : [1,2,3,4].map(cycle => 'cycle_' + cycle + '_water_temps'))]};
}

function openBoilerMetricPlot(event, elementId) {
    if (!event.ctrlKey || event.altKey || elementId !== 'boiler_body') return false;
    event.preventDefault();
    mainGraphSetting = createBoilerMetricPlotSetting(elementToMainGraphSettingMapping[elementId]?.day || dayStamp());
    mainGraphContentLocked = true;
    drawMainGraph({[mainGraphSetting.day]: {}});
    drawMainGraph();
    return true;
}

function selectBoilerMetricPlot(metric) {
    if (mainGraphSetting.title !== 'boiler_metrics' || !BOILER_METRICS[metric]) return;
    boilerMetricSelection = metric;
    mainGraphSetting = createBoilerMetricPlotSetting(mainGraphSetting.day, metric);
    mainGraphContentLocked = true;
    drawMainGraph({[mainGraphSetting.day]: {}});
    drawMainGraph();
}

function boilerEnabledCycles(heatingState) {
    const readings = (heatingState || []).filter(row => row.cycle_states);
    if (!readings.length) return null;
    // Day-level membership: one pump-on command includes the cycle all day.
    return [1,2,3,4].filter(cycle => readings.some(row => row.cycle_states[cycle] === 1));
}

function boilerAverageWaterTemperatures(data, cycles) {
    if (!cycles?.length) return [];
    const events = new Map();
    cycles.forEach(cycle => (data['cycle_' + cycle + '_water_temps'] || []).forEach(row => {
        const hour = row.h_of_day_frac;
        if (!Number.isFinite(hour) || hour < 0 || hour > 24) return;
        if (!events.has(hour)) events.set(hour, new Map());
        events.get(hour).set(cycle, row);
    }));
    const latest = new Map();
    return [...events].sort((a,b) => a[0] - b[0]).map(([hour, updates]) => {
        updates.forEach((row, cycle) => latest.set(cycle, row));
        const average = key => {
            const rows = cycles.map(cycle => latest.get(cycle));
            if (rows.some(row => !row || hour - row.h_of_day_frac > 3 / 60 || !Number.isFinite(row[key]))) return null;
            return rows.reduce((sum, row) => sum + row[key], 0) / cycles.length;
        };
        return {h_of_day_frac: hour, water_temp: average('water_temp'), return_temp: average('return_temp')};
    });
}

function boilerHeatingPeriodRects(heatingState, day, range) {
    // Match the gas plot: one pale-red rectangle per cycle-on period.
    // Overlapping cycles intentionally stack to show stronger shading.
    return [1,2,3,4].flatMap(cycle => extractHeatingPeriodsFromHeatingState(cycle, heatingState, day))
        .map(period => ({...period, y1: Math.floor(range[0]), y2: Math.ceil(range[1]),
            fill: 'rgba(255,0,0,0.05)', stroke: 'rgba(255,0,0,0)',
            strokeWeight: .25, dashed: false, dashing: '0.5,1'}));
}

function drawBoilerMetricPlot(data, setting) {
    const metric = BOILER_METRICS[setting.metric];
    const isTemperature = setting.metric === 'temperature';
    const cycles = isTemperature ? boilerEnabledCycles(data.heating_state) : null;
    const readings = isTemperature ? boilerAverageWaterTemperatures(data, cycles) : (data.heating_demand || []);
    const curves = [{key: metric.key, color: metric.color, tooltip: isTemperature ? 'előremenő' : 'hőigény'}];
    if (isTemperature) curves.push({key: 'return_temp', color: 'rgb(0,40,150)', tooltip: 'visszatérő'});
    curves.forEach(curve => curve.segments = splitCycleHeatReadings(readings.slice()
        .sort((a,b) => a.h_of_day_frac - b.h_of_day_frac), curve.key, 3 / 60));
    const values = curves.flatMap(curve => curve.segments.flat().map(row => row[curve.key]));
    let range, step;
    if (isTemperature) {
        step = 5;
        range = values.length ? [Math.floor(Math.min(...values) / 5) * 5 - 5, Math.ceil(Math.max(...values) / 5) * 5 + 5] : [0,80];
    } else {
        const top = Math.max(1, ...values) * 1.05;
        const magnitude = 10 ** Math.floor(Math.log10(top / 5));
        step = [1,2,5,10].find(value => value * magnitude >= top / 5) * magnitude;
        range = [0, Math.ceil(top / step) * step];
    }
    let emptyMessage = values.length ? '' : 'Az adott napra nincs adat.';
    if (isTemperature && cycles === null) emptyMessage = 'Az adott napra nincs kapcsolási adat.';
    else if (isTemperature && !cycles.length) emptyMessage = 'Nincs engedélyezett fűtési kör.';
    const common = {parentId: 'graph', margins: {top: .1, right: .03, bottom: .15, left: .1},
        domain: {bottom: [0,24], left: range}, dataKeys: {bottom: 'h_of_day_frac', left: metric.key},
        axesLabel: {bottom: 'óra', left: metric.axis}, tickVals: {left: d3.range(range[0], range[1] + step / 2, step)},
        smoothing: {bottom: 0, left: 0}, segment: {do: false}, plotLabel: '', curveEndText: {show: false},
        plotStyle: {joined: true, thickness: '1', smoothCurve: true, startCap: false, endCap: false}};
    const area = drawPlot([], {...common, emptyMessage,
        rects: {when: 'before', list: boilerHeatingPeriodRects(data.heating_state, setting.day, range)},
        plotLabelTabs: {prefix: 'kazán — ', selected: setting.metric,
        choices: Object.entries(BOILER_METRICS).map(([key, value]) => ({key, label: value.label, color: value.color})),
        onSelect: selectBoilerMetricPlot},
        plotDateNavigation: {day: setting.day, onDayChange: navigateMainPlotDay}});
    if (!isTemperature) {
        drawLoggedPowerBars(area, readings, {...metric, unit: 'kW', precision: 2}, range);
        return;
    }
    curves.forEach(curve => curve.segments.forEach((segment, index) => {
        const last = index === curve.segments.length - 1;
        drawPlot(segment, {...common, background: {show: false}, axes: {left: false, bottom: false}, showLockLabel: false,
            dataKeys: {...common.dataKeys, left: curve.key}, curveTooltip: curve.tooltip,
            plotStyle: {...common.plotStyle, col: curve.color, endCap: last},
            curveEndText: {show: last, fontSize: 6, col: curve.color, xOffset: 3, yOffset: 1.75,
                text: Number(segment.at(-1)[curve.key].toFixed(isTemperature ? 1 : 2)) + metric.unit}});
    }));
}
