// Reserved SVG hooks. Missing elements are expected until the drawing is ready.
const BOILER_POWER_DISPLAYS = [
    { number: 1, source: 'boiler_1_plug', marker: 'boiler1_marker' },
    { number: 2, source: 'boiler_2_plug', marker: 'boiler2_marker' }
];
const BOILER_POWER_FRESH_SECONDS = 180;

function freshBoilerPower(reading, now = new Date()) {
    if (reading?.reachable !== true || !Number.isFinite(reading.power_w) || reading.power_w < 0) return null;
    if (typeof reading.timestamp !== 'string') return null;
    const observed = dateFromTimestamp(reading.timestamp);
    const age = (now - observed) / 1000;
    return Number.isFinite(age) && age >= -30 && age <= BOILER_POWER_FRESH_SECONDS ? reading.power_w : null;
}

function initializeBoilerPowerMarkers() {
    BOILER_POWER_DISPLAYS.forEach(display => {
        if (d3.select('#' + display.marker).empty()) return;
        d3.select('#' + display.marker).style('pointer-events', 'all');
        d3.select('#' + display.marker + '_border')
            .style('stroke', 'black').style('fill', 'black').style('fill-opacity', '1');
    });
    updateBoilerPowerMarkers();
}

function updateBoilerPowerMarkers(readings = {}) {
    BOILER_POWER_DISPLAYS.forEach(display => {
        if (d3.select('#' + display.marker).empty()) return;
        const box = getBBoxDrawingDimensions(display.marker);
        const power = freshBoilerPower(readings?.[display.source]);
        d3.selectAll('.' + display.marker + '-content').remove();
        const parts = [
            { text: display.number + '|', x: 0.05, size: 4.5 },
            { text: power === null ? '—' : String(Math.round(power)), x: 0.42, size: 4.5 },
            { text: 'W', x: 0.86, size: 2.25 }
        ];
        parts.forEach(part => {
            const text = d3.select('#drawing').append('text')
                .attr('class', display.marker + '-content clickthrough')
                .attr('x', box.x + box.w * part.x).attr('y', box.y + box.h * 0.8)
                .style('font-family', dashboardFont).style('font-size', part.size + 'px')
                .text(part.text);
            if (part.x === 0.42) {
                const width = text.node().getComputedTextLength();
                const available = box.w * 0.4;
                if (width > available) text.style('font-size', part.size * available / width + 'px');
            }
        });
    });
}

function registerBoilerPowerPlots(mapping) {
    BOILER_POWER_DISPLAYS.forEach(display => {
        mapping[display.marker] = {
            title: 'boiler_power', boilerNumber: display.number, boilerSource: display.source,
            types: [display.source + '_power', 'boiler_commands'],
            day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), conditionals: []
        };
    });
}

function splitBoilerPowerSegments(readings) {
    const segments = [];
    let segment = [];
    const finish = () => { if (segment.length) segments.push(segment); segment = []; };
    readings.forEach(reading => {
        if (!Number.isFinite(reading.power_w) || reading.power_w < 0 || !Number.isFinite(reading.h_of_day_frac)) {
            finish();
            return;
        }
        if (segment.length && reading.h_of_day_frac - segment.at(-1).h_of_day_frac > 3 / 60) finish();
        segment.push(reading);
    });
    finish();
    return segments;
}

function boilerCommandPeriods(commands, lower, upper) {
    const periods = [];
    for (let index = 0; index < commands.length - 1; index++) {
        const start = commands[index];
        const end = commands[index + 1];
        if (start.command_on !== 1 || !Number.isFinite(start.h_of_day_frac) || !Number.isFinite(end.h_of_day_frac)) continue;
        if (end.h_of_day_frac <= start.h_of_day_frac) continue;
        periods.push({ x1: start.h_of_day_frac, x2: end.h_of_day_frac, y1: lower, y2: upper,
            fill: 'rgba(255,0,0,0.05)', stroke: 'rgba(255,0,0,0)', strokeWeight: 0, dashed: false });
    }
    return periods;
}

function drawBoilerPowerPlot(data, setting) {
    const readings = data[setting.boilerSource + '_power'] || [];
    const segments = splitBoilerPowerSegments(readings);
    const measured = segments.flat();
    const maxPower = measured.length ? d3.max(measured, item => item.power_w) : 0;
    const step = maxPower < 10 ? 1 : maxPower < 100 ? 10 : Math.ceil(maxPower / 500) * 100;
    const upper = Math.max(step, Math.ceil(maxPower / step) * step);
    const common = {
        parentId: 'graph', smoothing: { bottom: 0, left: 0 },
        domain: { bottom: [0, 24], left: [0, upper] },
        dataKeys: { bottom: 'h_of_day_frac', left: 'power_w' },
        axesLabel: { bottom: 'óra', left: 'teljesítmény (W)' },
        tickVals: { left: d3.range(0, upper + step / 2, step) },
        plotStyle: { joined: true, col: 'rgb(40,40,40)', thickness: '1.5', smoothCurve: false, startCap: false, endCap: true },
        plotLabel: setting.boilerNumber + '. kazán mai villamos teljesítménye' + (measured.length ? '' : ' (nincs mért adat)')
    };
    drawPlot([], { ...common, rects: { when: 'before', list: boilerCommandPeriods(data.boiler_commands || [], 0, upper) } });
    segments.forEach((segment, index) => {
        const last = index === segments.length - 1;
        drawPlot(segment, { ...common,
            background: { show: false }, axes: { left: false, bottom: false }, plotLabel: '',
            curveEndText: { show: last, fontSize: 5, text: Math.round(segment.at(-1).power_w) + ' W',
                col: 'rgb(40,40,40)', xOffset: 1.5, yOffset: 1.75 }
        });
    });
}
