// Ctrl+click opts into this view; ordinary room hover/click settings stay intact.
const ROOM_PLOT_METRICS = {
    temperature: { label: 'hőm.', key: 'temp', unit: '°C', color: 'rgba(255,0,0,1)', precision: 1 },
    humidity: { label: 'páratart.', key: 'hum', unit: '%', color: 'rgb(100, 180, 255)', precision: 1 },
    co2: { label: 'CO₂', key: 'co2', unit: 'ppm', color: 'rgb(80, 170, 0)', precision: 0 },
    lux: { label: 'lux', key: 'lux', unit: 'lux', color: 'rgb(190, 155, 0)', precision: 0 },
    occupancy: { label: 'jelenl.', key: 'occupancy_average', unit: '%', color: 'rgb(0, 0, 0)', precision: 0 }
};
const roomMetricSelections = {};

function hidePlotCurveTooltip() {
    const tooltip = d3.select('#tooltip');
    if (tooltip.attr('data-curve-tooltip') === 'true') {
        tooltip.interrupt().attr('data-curve-tooltip', null).style('visibility', 'hidden').style('font-size', null);
    }
}

function bindPlotCurveTooltip(curve, label, fontSize = 7) {
    const tooltip = d3.select('#tooltip');
    const position = event => {
        const matrix = curve.node().getScreenCTM();
        const scale = matrix ? Math.hypot(matrix.a, matrix.b) : 1;
        tooltip.style('font-size', fontSize * scale + 'px');
        const bounds = tooltip.node().getBoundingClientRect();
        const left = Math.max(window.scrollX + 4, Math.min(event.pageX + 10, window.scrollX + window.innerWidth - bounds.width - 4));
        const top = Math.max(window.scrollY + 4, Math.min(event.pageY + 12, window.scrollY + window.innerHeight - bounds.height - 4));
        tooltip.style('left', left + 'px').style('top', top + 'px');
    };
    curve.attr('aria-label', label);
    // A transparent hit area makes the thin valve curve practical to hover.
    const hit = curve.clone(true).attr('class', 'plot-curve-hitbox').attr('aria-label', null).attr('aria-hidden', 'true')
        .attr('stroke', 'transparent').attr('stroke-width', 3).attr('stroke-dasharray', null).style('pointer-events', 'stroke');
    [curve, hit].forEach(target => target
        .on('mouseover.curve-tooltip', event => {
            tooltip.interrupt().attr('data-curve-tooltip', 'true').text(label).style('visibility', 'visible');
            position(event);
        })
        .on('mousemove.curve-tooltip', position)
        .on('mouseout.curve-tooltip', hidePlotCurveTooltip));
}

function createRoomMetricPlotSetting(base, elementId, metric = roomMetricSelections[elementId] || 'temperature') {
    if (!ROOM_PLOT_METRICS[metric]) metric = 'temperature';
    return {
        title: 'room_metrics', roomNumToPlot: base.roomNumToPlot, sourceElementId: elementId,
        day: base.day, metric, conditionals: [],
        types: ['room_' + base.roomNumToPlot + (metric === 'temperature' || metric === 'humidity' ? '_measurements' : '_environment')]
    };
}

function openRoomMetricPlot(event, elementId) {
    const base = elementToMainGraphSettingMapping[elementId];
    if (!event.ctrlKey || base?.title !== 'room_plot') return false;
    event.preventDefault();
    mainGraphSetting = createRoomMetricPlotSetting(base, elementId);
    mainGraphContentLocked = true;
    drawMainGraph({ [mainGraphSetting.day]: {} });
    drawMainGraph();
    return true;
}

function selectRoomMetricPlot(metric) {
    if (mainGraphSetting.title !== 'room_metrics' || !ROOM_PLOT_METRICS[metric]) return;
    const current = mainGraphSetting;
    roomMetricSelections[current.sourceElementId] = metric;
    mainGraphSetting = createRoomMetricPlotSetting(current, current.sourceElementId, metric);
    mainGraphContentLocked = true;
    drawMainGraph({ [mainGraphSetting.day]: {} });
    drawMainGraph();
}

function splitRoomMetricReadings(readings, key, maxGapHours) {
    const segments = [];
    let segment = [];
    const finish = () => { if (segment.length) segments.push(segment); segment = []; };
    readings.filter(row => row && Object.hasOwn(row, key))
        .slice().sort((a, b) => a.h_of_day_frac - b.h_of_day_frac)
        .forEach(row => {
            if (!Number.isFinite(row[key]) || !Number.isFinite(row.h_of_day_frac)) {
                finish();
                return;
            }
            if (segment.length && row.h_of_day_frac - segment.at(-1).h_of_day_frac > maxGapHours) finish();
            segment.push(row);
        });
    finish();
    return segments;
}

function extractRoomOccupancyPeriods(readings, endHour, maxHoldHours = 15 / 60) {
    const samples = readings.filter(row => row && Object.hasOwn(row, 'occupancy') && Number.isFinite(row.h_of_day_frac)
        && row.h_of_day_frac >= 0 && row.h_of_day_frac <= endHour)
        .slice().sort((a, b) => a.h_of_day_frac - b.h_of_day_frac);
    const periods = [];
    let start = null, previous = null;
    const finish = end => { if (start !== null && end > start) periods.push({ x1: start, x2: end }); start = null; };
    samples.forEach(row => {
        if (previous && row.h_of_day_frac - previous.h_of_day_frac > maxHoldHours) finish(previous.h_of_day_frac + maxHoldHours);
        if (row.occupancy === 1) {
            if (start === null) start = row.h_of_day_frac;
        } else finish(row.h_of_day_frac);
        previous = row;
    });
    if (previous) finish(Math.min(endHour, previous.h_of_day_frac + maxHoldHours));
    return periods;
}

function drawRoomMetricPlot(data, setting) {
    const metricName = ROOM_PLOT_METRICS[setting.metric] ? setting.metric : 'temperature';
    const metric = ROOM_PLOT_METRICS[metricName];
    const isTemperature = metricName === 'temperature';
    const type = 'room_' + setting.roomNumToPlot + (isTemperature || metricName === 'humidity' ? '_measurements' : '_environment');
    const readings = data[type] || [];
    const isOccupancy = metricName === 'occupancy';
    // Exactly the same display-series preparation as the ordinary room plot.
    const temperatureSeries = isTemperature ? prepareRoomTemperatureForDisplay(readings) : [];
    const segments = (isTemperature ? (temperatureSeries.length ? [temperatureSeries] : [])
        : splitRoomMetricReadings(readings, metric.key, isOccupancy || metricName === 'humidity' ? 2 : 15 / 60))
        .map(segment => isOccupancy ? segment.map(row => ({ ...row, occupancy_average: row.occupancy_average * 100 })) : segment);
    const values = segments.flat().map(row => row[metric.key]);
    let range;
    if (isOccupancy) range = [0, 100];
    else if (metricName === 'humidity') range = [0, 100];
    else if (metricName === 'temperature') range = values.length ? [Math.floor(Math.min(...values)) - 1, Math.ceil(Math.max(...values)) + 1] : [10, 30];
    else range = [0, values.length ? Math.max(1, Math.max(...values) * 1.1) : metricName === 'co2' ? 2000 : 100];
    const common = {
        parentId: 'graph', smoothing: { bottom: 0, left: isTemperature ? 10 : 0 },
        margins: { top: .18, right: .03, bottom: .15, left: .1 },
        domain: { bottom: [0, 24], left: range },
        dataKeys: { bottom: 'h_of_day_frac', left: metric.key },
        axesLabel: { bottom: 'óra', left: isOccupancy ? 'átlagos ' + selectorWeekday(setting.day, true) + ' jelenlét (%)' : metric.unit },
        plotStyle: { joined: true, col: metric.color, thickness: '2', startCap: false, endCap: !isOccupancy,
            smoothCurve: isTemperature, monotone: !isTemperature },
        segment: { do: false }, plotLabel: '', curveEndText: { show: false },
        curveTooltip: isTemperature ? 'mért hőmérséklet' : ''
    };
    const roomName = roomsDataAndState[setting.roomNumToPlot].name;
    const endHour = setting.day === dayStamp() ? getFractionalHourOfDay() : 24;
    const periods = isOccupancy ? extractRoomOccupancyPeriods(readings, endHour)
        .map(period => ({ ...period, y1: 0, y2: 100, fill: 'rgba(180,180,180,0.3)' })) : [];
    drawPlot([], { ...common, rects: { when: 'before', list: periods },
        emptyMessage: isOccupancy && !segments.length ? 'Átlagos jelenlét nem elérhető.' : '', plotLabelTabs: {
        prefix: roomName + ' — ', selected: metricName, day: setting.day, onDayChange: navigateSelectorPlotDay,
        choices: Object.entries(ROOM_PLOT_METRICS).map(([key, value]) => ({ key, label: value.label, color: value.color })),
        onSelect: selectRoomMetricPlot
    }});
    segments.forEach((segment, index) => {
        const value = segment.at(-1)[metric.key];
        const text = Number(value.toFixed(metric.precision)) + ' ' + metric.unit;
        drawPlot(segment, { ...common, showLockLabel: false, background: { show: false }, axes: { left: false, bottom: false },
            curveEndText: { show: !isOccupancy && index === segments.length - 1, text, col: metric.color, fontSize: 6, xOffset: 3, yOffset: 1.75 }
        });
    });
}
