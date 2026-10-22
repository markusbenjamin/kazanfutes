// Cycle piping and numbered energy dials share a simple hover and Ctrl+click selector.
const CYCLE_HEAT_METRICS = {
    temperature: { label: 'fűtővíz hőm.', key: 'water_temp', unit: '°C', axis: '°C', precision: 0, color: 'rgb(200, 0, 0)' },
    power: { label: 'fűtőtelj.', key: 'power_kw', unit: 'kW', axis: 'fűtőteljesítmény (kW)', precision: 2, color: 'rgb(230, 130, 0)' },
    flow: { label: 'átfolyás', key: 'flow_m3h', unit: 'm³/h', axis: 'térfogatáram (m³/h)', precision: 3, color: 'rgb(28, 3, 252)' },
    pump: { label: 'szivattyú telj.', unit: 'W', axis: 'szivattyú teljesítmény (W)', precision: 0, color: 'rgb(0, 0, 0)' }
};
const cycleHeatSelections = {};

function createCycleHeatPlotSetting(cycle, elementId, metric = 'power', day = dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), detailed = false) {
    if (!CYCLE_HEAT_METRICS[metric]) metric = 'power';
    return {
        title: 'cycle_water_temp', cycleNum: cycle, sourceElementId: elementId, metric, day, detailed,
        types: [metric === 'pump' ? 'pumps_power' : 'cycle_' + cycle + (metric === 'temperature' ? '_water_temps' : '_heat_delivery'), 'heating_state'],
        conditionals: []
    };
}

function openCycleHeatPlot(event, elementId) {
    const base = elementToMainGraphSettingMapping[elementId];
    if (!event.ctrlKey || base?.title !== 'cycle_water_temp') return false;
    event.preventDefault();
    mainGraphSetting = createCycleHeatPlotSetting(base.cycleNum, elementId,
        cycleHeatSelections[base.cycleNum] || 'power', base.day, true);
    mainGraphContentLocked = true;
    drawMainGraph({ [mainGraphSetting.day]: {} });
    drawMainGraph();
    return true;
}

function selectCycleHeatPlot(metric) {
    if (mainGraphSetting.title !== 'cycle_water_temp' || !mainGraphSetting.detailed || !CYCLE_HEAT_METRICS[metric]) return;
    const current = mainGraphSetting;
    const elementId = current.sourceElementId || 'cycle' + current.cycleNum;
    const next = createCycleHeatPlotSetting(current.cycleNum, elementId, metric, current.day, true);
    // A new setting object also invalidates in-flight responses for the previous metric.
    cycleHeatSelections[current.cycleNum] = metric;
    mainGraphSetting = next;
    mainGraphContentLocked = true;
    drawMainGraph({ [next.day]: {} });
    drawMainGraph();
}

function selectorWeekday(day, adjective = false) {
    const parts = day.split('-').map(Number);
    const index = new Date(parts[0], parts[1] - 1, parts[2], 12).getDay();
    return (adjective ? ['vasárnapi', 'hétfői', 'keddi', 'szerdai', 'csütörtöki', 'pénteki', 'szombati']
        : ['vasárnap', 'hétfő', 'kedd', 'szerda', 'csütörtök', 'péntek', 'szombat'])[index];
}

function shiftedSelectorDay(day, delta) {
    const parts = day.split('-').map(Number);
    const date = new Date(parts[0], parts[1] - 1, parts[2] + delta, 12);
    return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
}

function navigateSelectorPlotDay(delta) {
    const current = mainGraphSetting;
    if (!['room_metrics', 'weather_metrics'].includes(current.title) && !(current.title === 'cycle_water_temp' && current.detailed)) return;
    const day = shiftedSelectorDay(current.day, delta);
    if (day > dayStamp()) return;
    mainGraphSetting = { ...current, day };
    mainGraphContentLocked = true;
    drawMainGraph({ [day]: {} });
    drawMainGraph();
}

function navigateMainPlotDay(delta) {
    const day = shiftedSelectorDay(mainGraphSetting.day, delta);
    if (day > dayStamp()) return;
    mainGraphSetting = {...mainGraphSetting, day};
    mainGraphContentLocked = true;
    clearMainGraphs();
    drawPlot(undefined, {parentId: 'graph', domain: {bottom: [0, 24], left: [0, 1]},
        dataKeys: {bottom: 'x', left: 'y'}, axes: {left: false, bottom: false},
        plotLabel: '', curveEndText: {show: false}});
    drawMainGraph();
}

function drawPlotDateNavigation(container, dimensions, options, fontSize, locked) {
        const date = container.append('g').attr('class', 'selector-plot-date')
            .attr('data-day', options.day)
            .style('text-anchor', 'middle').style('font-family', dashboardFont).style('font-size', fontSize + 'px');
        const dateY = fontSize * 1.15;
        const labelY = -fontSize * .7;
        const padding = fontSize * .75;
        const arrow = (text, label, delta, enabled) => {
            const activate = event => { event.stopPropagation(); if (enabled) options.onDayChange(delta); };
            date.append('text').attr('x', delta < 0 ? padding : dimensions.w - padding).attr('y', dateY)
                .attr('role', 'button').attr('aria-label', label)
                .attr('aria-disabled', enabled ? 'false' : 'true').attr('tabindex', enabled ? 0 : -1)
                .style('font-size', fontSize * 1.3 + 'px')
                .style('cursor', enabled ? 'pointer' : 'default').style('fill', enabled ? 'black' : '#bbb').text(text)
                .on('mousedown', event => event.stopPropagation()).on('touchstart', event => event.stopPropagation())
                .on('click', activate).on('keydown', event => {
                    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(event); }
                });
        };
        arrow('‹', 'Előző nap', -1, true);
        let labelX = padding;
        if (locked) {
            const lock = date.append('text').attr('class', 'plot-lock-label').attr('x', labelX).attr('y', labelY)
                .style('text-anchor', 'start').style('fill', 'rgba(230,230,230,1)').text('rögzítve');
            labelX += lock.node().getComputedTextLength() + fontSize;
        }
        if (options.day !== dayStamp()) {
            const dateLabel = date.append('text').attr('class', 'selector-date-label')
                .attr('x', labelX).attr('y', labelY).style('text-anchor', 'start').style('fill', '#777')
                .text(options.day + ' (' + selectorWeekday(options.day) + ')');
            const dateWidth = dateLabel.node().getComputedTextLength();
            const availableDateWidth = Math.max(fontSize, dimensions.w - padding - fontSize - labelX);
            if (dateWidth > availableDateWidth) dateLabel.style('font-size', fontSize * availableDateWidth / dateWidth + 'px');
        }
        arrow('›', 'Következő nap', 1, options.day < dayStamp());
}

function drawPlotTitleSelector(plotElement, plotDims, options, fontSize) {
    const columns = options.columns || options.choices.length || 1;
    const rows = Math.ceil(options.choices.length / columns);
    const lineHeight = fontSize * 1.4;
    for (let row = 0; row < rows; row++) {
      const heading = plotElement.append('text')
        .attr('class', 'cycle-heat-selector').attr('role', 'tablist')
        .attr('aria-label', options.prefix + 'grafikon választása')
        .attr('x', plotDims.w / 2).attr('y', -(rows - row - 1) * lineHeight - fontSize * .35)
        .style('text-anchor', 'middle').style('font-family', dashboardFont)
        .style('font-size', fontSize + 'px');
      if (!row) heading.append('tspan').text(options.prefix);
      options.choices.slice(row * columns, (row + 1) * columns).forEach((choice, index) => {
        if (index) heading.append('tspan').attr('aria-hidden', 'true').text(' · ');
        const active = choice.key === options.selected;
        const activate = event => {
            event.stopPropagation();
            options.onSelect(choice.key);
        };
        heading.append('tspan').attr('role', 'tab').attr('tabindex', '0')
            .attr('aria-selected', active ? 'true' : 'false')
            .attr('data-cycle-metric', choice.key)
            .style('fill', active ? choice.color : '#777')
            .style('text-decoration', active ? 'underline' : 'none')
            .style('cursor', 'pointer').text(choice.label)
            .on('mousedown', event => event.stopPropagation())
            .on('touchstart', event => event.stopPropagation())
            .on('click', activate)
            .on('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    activate(event);
                }
            });
    });
      const width = heading.node().getComputedTextLength();
      if (width > plotDims.w) heading.style('font-size', fontSize * plotDims.w / width + 'px');
    }
}

function splitCycleHeatReadings(readings, key, maxGapHours = 3 / 60) {
    const segments = [];
    let segment = [];
    const finish = () => { if (segment.length) segments.push(segment); segment = []; };
    readings.forEach(reading => {
        if (!Number.isFinite(reading[key]) || !Number.isFinite(reading.h_of_day_frac)) {
            finish();
            return;
        }
        if (segment.length && reading.h_of_day_frac - segment.at(-1).h_of_day_frac > maxGapHours) finish();
        segment.push(reading);
    });
    finish();
    return segments;
}

function drawCycleHeatPlot(data, setting) {
    const metricName = CYCLE_HEAT_METRICS[setting.metric] ? setting.metric : 'power';
    const metric = { ...CYCLE_HEAT_METRICS[metricName] };
    if (metricName === 'pump') metric.key = 'pump_' + setting.cycleNum + '_power';
    const type = metricName === 'pump' ? 'pumps_power' : 'cycle_' + setting.cycleNum + (metricName === 'temperature' ? '_water_temps' : '_heat_delivery');
    const segments = splitCycleHeatReadings(data[type] || [], metric.key, metricName === 'pump' ? Infinity : 3 / 60);
    const measured = segments.flat();
    let range, tickStep;
    if (metricName === 'temperature') {
        const extent = d3.extent(measured, reading => reading[metric.key]);
        range = measured.length ? [Math.floor(extent[0] / 5) * 5 - 5, Math.ceil(extent[1] / 5) * 5 + 5] : [0, 80];
        tickStep = 5;
    } else {
        const top = Math.max(0, ...measured.map(reading => reading[metric.key]));
        const roughStep = (top > 0 ? top * 1.05 : 1) / 5;
        const magnitude = 10 ** Math.floor(Math.log10(roughStep));
        const fraction = roughStep / magnitude;
        tickStep = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * magnitude;
        range = [0, Math.ceil((top > 0 ? top * 1.05 : 1) / tickStep) * tickStep];
    }
    const end = setting.day === dayStamp() ? getFractionalHourOfDay() : 24;
    const periods = extractCyclePumpOnPeriods(setting.cycleNum, data.heating_state, end)
        .map(period => ({ ...period, y1: range[0], y2: range[1],
            fill: 'rgba(255,0,0,0.025)', stroke: 'none',
            strokeWeight: 0, dashed: false }));
    const common = {
        parentId: 'graph', smoothing: { bottom: 0, left: 0 },
        margins: { top: .1, right: .03, bottom: .15, left: .1 },
        domain: { bottom: [0, 24], left: range },
        dataKeys: { bottom: 'h_of_day_frac', left: metric.key },
        axesLabel: { bottom: 'óra', left: metric.axis },
        tickVals: { left: d3.range(range[0], range[1] + tickStep / 2, tickStep) },
        plotStyle: { joined: true, col: metric.color, thickness: '1', startCap: false, endCap: true,
            smoothCurve: metricName !== 'pump', stepAfter: metricName === 'pump' },
        segment: { do: false }, plotLabel: setting.detailed ? '' : setting.cycleNum + '. kör ' + (setting.day === dayStamp() ? 'mai ' : 'napi ') + 'fűtőteljesítménye', curveEndText: { show: false }
    };
    drawPlot([], { ...common, rects: { when: 'before', list: periods },
        plotLabelTabs: setting.detailed ? { prefix: setting.cycleNum + '. kör — ', selected: metricName,
            day: setting.day, onDayChange: navigateSelectorPlotDay,
            choices: Object.entries(CYCLE_HEAT_METRICS).map(([key, value]) => ({key, label: value.label, color: value.color})),
            onSelect: selectCycleHeatPlot } : false
    });
    segments.forEach((segment, index) => {
        const last = segment.at(-1);
        const value = Number(last[metric.key].toFixed(metric.precision));
        const endText = value + (metricName === 'temperature' ? '' : ' ') + metric.unit;
        drawPlot(segment, { ...common, plotLabel: '', showLockLabel: false, background: { show: false }, axes: { left: false, bottom: false },
            curveEndText: { show: index === segments.length - 1, fontSize: 6,
                text: endText, col: metric.color, xOffset: 3, yOffset: 1.75 }
        });
    });
}

function formatCycleEnergyDisplay(readings) {
    const latest = Array.isArray(readings) ? readings.at(-1) : null;
    if (!Number.isFinite(latest?.energy_kwh)) return { text: '—' };
    return { text: String(Math.round(latest.energy_kwh)) };
}

function writeCycleEnergyToMarkers(data = null) {
    const day = dayStamp(new Date(), dayDataNotAvailable, dataWaitTime);
    if (data === null) {
        collectDataFromGitHub([1, 2, 3, 4].map(cycle => ({ day, type: 'cycle_' + cycle + '_heat_delivery' })), writeCycleEnergyToMarkers);
        return;
    }
    for (let cycle = 1; cycle <= 4; cycle++) {
        const display = formatCycleEnergyDisplay(data[day]?.['cycle_' + cycle + '_heat_delivery']);
        const markerBB = getBBoxDrawingDimensions('cycle' + cycle + '_marker');
        d3.selectAll('.cycle' + cycle + '_marker_text').remove();
        const baseline = markerBB.y + markerBB.height * .8;
        const numberSize = markerBB.height * .85;
        const unitSize = markerBB.height * .55;
        const unit = d3.select('#drawing').append('text')
            .attr('class', 'cycle' + cycle + '_marker_text clickthrough')
            .attr('x', markerBB.x + markerBB.width * .96).attr('y', baseline)
            .style('text-anchor', 'end').style('font-family', dashboardFont)
            .style('font-size', unitSize + 'px').style('fill', 'black').text('kWh');
        const unitWidth = unit.node().getComputedTextLength();
        const fittedUnitWidth = Math.min(unitWidth, markerBB.width * .3);
        if (unitWidth > fittedUnitWidth) unit.style('font-size', unitSize * fittedUnitWidth / unitWidth + 'px');
        const number = d3.select('#drawing').append('text')
            .attr('class', 'cycle' + cycle + '_marker_text clickthrough')
            .attr('x', markerBB.x + markerBB.width * .34).attr('y', baseline)
            .style('font-family', dashboardFont).style('font-size', numberSize + 'px').style('fill', 'black').text(display.text);
        const width = number.node().getComputedTextLength();
        // Reserve the measured unit width and a small gap before fitting long totals.
        const available = markerBB.width * (.96 - .34 - .035) - fittedUnitWidth;
        if (width > available) number.style('font-size', numberSize * available / width + 'px');
    }
}
