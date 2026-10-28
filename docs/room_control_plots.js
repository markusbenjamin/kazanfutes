// Alt+click analytics: room summaries or daily errors, plus phase trajectories.
const ROOM_CONTROL_WINDOW_DAYS = 7;
const ROOM_CONTROL_QUADRANTS = [
    {key: 'below_on', label: 'fűtés be, kért alatt'}, {key: 'above_on', label: 'fűtés be, kért felett'},
    {key: 'below_off', label: 'fűtés ki, kért alatt'}, {key: 'above_off', label: 'fűtés ki, kért felett'}
];
let roomControlOverviewSelection = 'below_on';
const roomAnalyticSelections = {};

function roomAnalyticKey(setting) {
    return setting.roomNumToPlot ?? (setting.cycleNum ? 'cycle_' + setting.cycleNum : 'all');
}

function roomControlPlotRooms(setting) {
    return setting.roomNumToPlot != null ? [setting.roomNumToPlot]
        : allControlledRooms.filter(room => !setting.cycleNum || Number(roomsDataAndState[room].cycle) === setting.cycleNum);
}

function roomPhaseDataTypes(setting) {
    return roomControlPlotRooms(setting).map(room => 'room_' + room + '_phase_points');
}

function roomControlDays(day, count = ROOM_CONTROL_WINDOW_DAYS) {
    return Array.from({length: count + 1}, (_, index) => shiftedSelectorDay(day, index - count));
}

function isRoomControlView(setting) {
    return ['room_control_daily', 'room_control_overview', 'room_control_diagnostic', 'room_control_phase'].includes(setting.title);
}

function createRoomControlPlotSetting(elementId, day = dayStamp()) {
    const base = elementToMainGraphSettingMapping[elementId];
    const cycleMatch = elementId.match(/^cycle([1-4])_infobox$/);
    const overview = elementId === 'general_infobox' || Boolean(cycleMatch);
    const diagnostic = base?.title === 'room_plot';
    if (!overview && !diagnostic) return null;
    const scope = {roomNumToPlot: diagnostic ? base.roomNumToPlot : null, cycleNum: cycleMatch ? Number(cycleMatch[1]) : null};
    const phase = (roomAnalyticSelections[roomAnalyticKey(scope)] || 'phase') === 'phase';
    return {title: phase ? 'room_control_phase' : overview ? 'room_control_daily' : 'room_control_diagnostic',
        roomNumToPlot: diagnostic ? base.roomNumToPlot : null, day,
        cycleNum: cycleMatch ? Number(cycleMatch[1]) : null,
        overviewState: roomControlOverviewSelection,
        windowDays: ROOM_CONTROL_WINDOW_DAYS,
        types: phase ? roomPhaseDataTypes(scope) : [overview ? 'room_control_errors' : 'room_control_kpis'], conditionals: []};
}

function selectRoomAnalyticView(metric) {
    if (!['room_control_diagnostic', 'room_control_daily', 'room_control_phase'].includes(mainGraphSetting.title) || !['summary', 'phase'].includes(metric)) return;
    const room = mainGraphSetting.roomNumToPlot;
    roomAnalyticSelections[roomAnalyticKey(mainGraphSetting)] = metric;
    mainGraphSetting = {...mainGraphSetting, title: metric === 'phase' ? 'room_control_phase' : room != null ? 'room_control_diagnostic' : 'room_control_daily',
        types: metric === 'phase' ? roomPhaseDataTypes(mainGraphSetting) : [room != null ? 'room_control_kpis' : 'room_control_errors']};
    mainGraphContentLocked = true;
    drawMainGraph({});
    drawMainGraph();
}

function roomAnalyticTabs(setting) {
    const room = setting.roomNumToPlot;
    const name = room != null ? roomsDataAndState[room].name : setting.cycleNum ? setting.cycleNum + '. kör' : 'szobák';
    return {prefix: name + ' — ',
        selected: setting.title === 'room_control_phase' ? 'phase' : 'summary',
        choices: [{key: 'phase', label: 'fázissík', color: 'black'}, {key: 'summary', label: room != null ? 'összegzés' : 'napi hiba', color: 'black'}],
        onSelect: selectRoomAnalyticView};
}

function openRoomControlPlot(event, elementId) {
    if (!event.altKey) return false;
    if (elementId === 'boiler_body') return openBoilerKPIPlot(event);
    const setting = createRoomControlPlotSetting(elementId);
    if (!setting) return false;
    event.preventDefault();
    mainGraphSetting = setting;
    mainGraphContentLocked = true;
    drawMainGraph({});
    drawMainGraph();
    return true;
}

function selectRoomControlOverviewState(state) {
    if (mainGraphSetting.title !== 'room_control_overview' || !ROOM_CONTROL_QUADRANTS.some(item => item.key === state)) return;
    roomControlOverviewSelection = state;
    mainGraphSetting = {...mainGraphSetting, overviewState: state};
    mainGraphContentLocked = true;
    drawMainGraph({});
    drawMainGraph();
}

function navigateRoomControlDay(delta) {
    if (!isRoomControlView(mainGraphSetting)) return;
    const day = shiftedSelectorDay(mainGraphSetting.day, delta);
    if (day > dayStamp()) return;
    mainGraphSetting = {...mainGraphSetting, day};
    drawMainGraph({});
    drawMainGraph();
}

function aggregateRoomControlKPIs(rows) {
    const sums = {valid_seconds: 0, heating_seconds: 0, occupied_seconds: 0, comfort_seconds: 0,
        absolute_error_on_kh: 0, signed_error_on_kh: 0, quadrant_seconds: {}};
    ROOM_CONTROL_QUADRANTS.forEach(({key}) => sums.quadrant_seconds[key] = 0);
    const validRows = rows.filter(row => row && row.valid_seconds > 0 &&
        ['valid_seconds', 'heating_seconds', 'absolute_error_on_kh', 'signed_error_on_kh']
            .every(key => Number.isFinite(row[key])));
    validRows.forEach(row => {
        for (const key of ['valid_seconds', 'heating_seconds', 'absolute_error_on_kh', 'signed_error_on_kh']) {
            if (Number.isFinite(row[key])) sums[key] += row[key];
        }
        ROOM_CONTROL_QUADRANTS.forEach(({key}) => {
            if (Number.isFinite(row.quadrant_seconds?.[key])) sums.quadrant_seconds[key] += row.quadrant_seconds[key];
        });
    });
    rows.filter(row => row && Number.isFinite(row.occupied_seconds) && row.occupied_seconds >= 0 &&
        Number.isFinite(row.comfort_seconds) && row.comfort_seconds >= 0 && row.comfort_seconds <= row.occupied_seconds).forEach(row => {
        sums.occupied_seconds += row.occupied_seconds;
        sums.comfort_seconds += row.comfort_seconds;
    });
    const hours = sums.heating_seconds / 3600;
    return {...sums, observed_days: validRows.length, mae_on_c: hours ? sums.absolute_error_on_kh / hours : null,
        bias_on_c: hours ? sums.signed_error_on_kh / hours : null,
        comfort_pct: sums.occupied_seconds ? sums.comfort_seconds / sums.occupied_seconds * 100 : null};
}

function roomControlNumber(value, precision = 1) {
    return Number.isFinite(value) ? value.toFixed(precision).replace('.', ',') : '—';
}

function roomControlText(parent, text, x, y, size = 5, anchor = 'middle', color = 'black') {
    return parent.append('text').attr('x', x).attr('y', y).style('font-family', dashboardFont)
        .style('font-size', size + 'px').style('text-anchor', anchor).style('fill', color).text(text);
}

function drawRoomControlHeader(area, setting, title, titleY = -13) {
    roomControlText(area.plotElement, title, area.plotDims.w / 2, titleY, 6);
}

function drawRoomControlView(data = null) {
    const setting = mainGraphSetting;
    if (data === null) {
        if (setting.title === 'room_control_phase') {
            collectDataFromGitHub(roomPhaseDataTypes(setting).map(type => ({day: setting.day, type})), loaded => {
                if (mainGraphSetting === setting) drawRoomControlView(loaded);
            });
            return;
        }
        if (setting.title === 'room_control_daily') {
            collectDataFromGitHub([{day: setting.day, type: 'room_control_errors'}], loaded => {
                if (mainGraphSetting === setting) drawRoomControlView(loaded);
            });
            return;
        }
        collectDataFromGitHub(roomControlDays(setting.day, setting.windowDays).map(day => ({day, type: 'room_control_kpis'})),
            loaded => {
                if (mainGraphSetting !== setting) return;
                const currentSchema = Object.fromEntries(Object.entries(loaded).map(([day, record]) =>
                    [day, record.room_control_kpis?.schema_version === 3 ? record : {}]));
                drawRoomControlView(currentSchema);
            });
        return;
    }
    clearMainGraphs();
    if (setting.title === 'room_control_phase') drawRoomPhasePlot(data, setting);
    else if (setting.title === 'room_control_daily') drawRoomControlDaily(data, setting);
    else if (setting.title === 'room_control_overview') drawRoomControlOverview(data, setting);
    else drawRoomControlDiagnostic(data, setting);
}

function roomControlErrorSegments(readings, room) {
    return splitRoomMetricReadings(readings.map(row => ({h_of_day_frac: row.h_of_day_frac,
        error_k: row.errors?.[room] ?? null})), 'error_k', 3 / 60);
}

function roomAnalyticLegendLayout(curves) {
    const rows = curves.length > 6 ? 2 : curves.length ? 1 : 0;
    return {rows, columns: Math.ceil(curves.length / (rows || 1))};
}

function drawRoomAnalyticHeading(area, setting, curves, className) {
    const {rows, columns} = roomAnalyticLegendLayout(curves);
    const fontSize = isMobile ? 7 * 1.8 : 7;
    const legendFontSize = fontSize * 4.5 / 7, lineHeight = legendFontSize * 1.4;
    drawPlotTitleSelector(area.plotElement.append('g').attr('class', className + '-title')
        .attr('transform', 'translate(0,' + (-rows * lineHeight - fontSize * .65) + ')'),
        area.plotDims, roomAnalyticTabs(setting), fontSize);
    for (let row = 0; row < rows; row++) {
        const legend = roomControlText(area.plotElement, '', area.plotDims.w / 2,
            -(rows - row - 1) * lineHeight - fontSize, legendFontSize).attr('class', className + '-legend');
        curves.slice(row * columns, (row + 1) * columns).forEach((curve, index) => {
            if (index) legend.append('tspan').text(' · ');
            legend.append('tspan').attr('data-room', curve.room).style('fill', curve.color).text(curve.name);
        });
    }
}

function drawRoomControlDaily(data, setting) {
    const readings = (data[setting.day]?.room_control_errors || []).slice()
        .filter(row => Number.isFinite(row.h_of_day_frac) && row.h_of_day_frac >= 0 && row.h_of_day_frac <= 24)
        .sort((a,b) => a.h_of_day_frac - b.h_of_day_frac);
    const rooms = roomControlPlotRooms(setting);
    const curves = rooms.map(room => ({room, name: roomsDataAndState[room].name,
        color: roomsColorScale(roomsColorRemap[room - 1]), segments: roomControlErrorSegments(readings, room)}));
    const legendRows = roomAnalyticLegendLayout(curves).rows;
    const errors = curves.flatMap(curve => curve.segments.flat().map(row => row.error_k));
    const top = Math.max(1, Math.ceil(Math.max(0, ...errors.map(Math.abs)) * 2) / 2);
    const common = {parentId: 'graph', margins: {top: .12 + legendRows * .05, right: .03, bottom: .15, left: .1},
        domain: {bottom: [0,24], left: [-top,top], niceLeft: false}, dataKeys: {bottom: 'h_of_day_frac', left: 'error_k'},
        axesLabel: {bottom: 'óra', left: 'szabályozási hiba (K)'}, smoothing: {bottom: 0, left: 0},
        plotStyle: {joined: true, thickness: '1.25', stepAfter: true, startCap: false, endCap: false},
        segment: {do: false}, plotLabel: '', curveEndText: {show: false}};
    const area = drawPlot([], {...common,
        plotDateNavigation: {day: setting.day, onDayChange: navigateRoomControlDay},
        emptyMessage: errors.length ? '' : 'Az adott napra nincs szabályozási adat.'});
    drawRoomAnalyticHeading(area, setting, curves, 'room-control-daily');
    const watermarkFontSize = isMobile ? 8 * 1.8 : 8;
    [['alulfűtés', watermarkFontSize + 3, 'rgba(200,0,0,0.06)'],
        ['túlfűtés', area.plotDims.h - 3, 'rgba(0,40,180,0.06)']].forEach(([text, y, color]) => {
        roomControlText(area.plotElement, text, 3, y, watermarkFontSize, 'start', color)
            .attr('class', 'room-control-error-watermark').style('pointer-events', 'none');
    });
    area.plotElement.append('line').attr('x1',0).attr('x2',area.plotDims.w)
        .attr('y1',area.plotDims.h / 2).attr('y2',area.plotDims.h / 2).attr('stroke','#aaa').attr('stroke-width',.3);
    curves.forEach(curve => {
        curve.segments.forEach((segment, part) => drawPlot(segment, {...common, background: {show: false},
            axes: {left: false, bottom: false}, showLockLabel: false, curveTooltip: curve.name,
            plotStyle: {...common.plotStyle, col: curve.color, endCap: part === curve.segments.length - 1}}));
    });
}

function roomControlDailyRow(data, day, room, state = 'below_on') {
    const row = data[day]?.room_control_kpis?.rooms?.[room];
    const seconds = row?.quadrant_seconds?.[state], integral = row?.quadrant_error_kh?.[state];
    const basis = state.endsWith('_on') ? row?.heating_seconds : row?.valid_seconds - row?.heating_seconds;
    if (!(seconds > 0) || !Number.isFinite(seconds) || !Number.isFinite(integral) || integral < 0 || !Number.isFinite(basis) || !(basis > 0) || seconds > basis + 1e-6) return null;
    return {...row, state_seconds: seconds, state_error_k: integral / (seconds / 3600), state_share_pct: 100 * seconds / basis};
}

function drawRoomControlOverview(data, setting) {
    const days = roomControlDays(setting.day, setting.windowDays).slice(1);
    const state = ROOM_CONTROL_QUADRANTS.find(item => item.key === setting.overviewState) || ROOM_CONTROL_QUADRANTS[0];
    const rows = allControlledRooms.map(room => ({room, values: days.map(day => roomControlDailyRow(data, day, room, state.key))}));
    const max = Math.max(1, ...rows.flatMap(item => item.values.filter(Boolean).map(row => row.state_error_k)));
    const area = drawPlot([], {parentId: 'graph', margins: {top: .23, right: .03, bottom: .08, left: .03},
        domain: {bottom: [0, days.length], left: [0, Math.max(1, rows.length)]},
        dataKeys: {bottom: 'day_index', left: 'error'}, axes: {left: false, bottom: false},
        plotLabel: '', curveEndText: {show: false}, plotLabelTabs: {prefix: 'eltérés (K) — ', columns: 2,
            selected: state.key, day: setting.day, onDayChange: navigateRoomControlDay,
            choices: ROOM_CONTROL_QUADRANTS.map(item => ({...item, color: 'black'})), onSelect: selectRoomControlOverviewState}});
    const {plotElement: plot, plotDims: dims} = area;
    const tableTop = 9, rowHeight = (dims.h - tableTop) / Math.max(1, rows.length), labelFont = Math.min(4.8, rowHeight * .65);
    const roomLabels = rows.map(({room}, index) => roomControlText(plot, roomsDataAndState[room].name,
        0, tableTop + (index + .7) * rowHeight, labelFont, 'start').attr('class', 'room-kpi-room-label'));
    const labelWidths = roomLabels.map(label => label.node().getComputedTextLength());
    const nameWidth = Math.min(dims.w * .35, Math.max(0, ...labelWidths) + 6);
    roomLabels.forEach((label, index) => {
        if (labelWidths[index] > nameWidth - 6) label.style('font-size', labelFont * (nameWidth - 6) / labelWidths[index] + 'px');
    });
    const cellWidth = (dims.w - nameWidth) / days.length;
    const font = Math.min(labelFont, cellWidth / 4);
    days.forEach((day, index) => roomControlText(plot, day.slice(5).replace('-', '.'),
        nameWidth + (index + .5) * cellWidth, 5, 4.5));
    rows.forEach(({room, values}, roomIndex) => {
        const name = roomsDataAndState[room].name;
        const y = tableTop + roomIndex * rowHeight;
        const baseline = y + rowHeight * .7;
        plot.append('line').attr('x1', 0).attr('x2', dims.w).attr('y1', y + rowHeight).attr('y2', y + rowHeight)
            .attr('stroke', '#ddd').attr('stroke-width', .25);
        values.forEach((row, index) => {
            const x = nameWidth + index * cellWidth;
            const cell = plot.append('g').attr('class', 'room-kpi-cell').attr('data-room', room).attr('data-day', days[index]);
            cell.append('rect').attr('x', x + 1).attr('y', y + .5).attr('width', cellWidth - 2).attr('height', rowHeight - 1)
                .attr('fill', 'transparent');
            if (row) cell.append('rect').attr('x', x + 1).attr('y', y + 1).attr('width', (cellWidth - 2) * row.state_error_k / max)
                .attr('height', rowHeight - 2).attr('fill', '#e7e7e7');
            roomControlText(cell, roomControlNumber(row?.state_error_k), x + cellWidth / 2, baseline, font, 'middle', row ? 'black' : '#aaa');
            const label = name + ' · ' + days[index] + '\n' + state.label + (row ? '\nátlagos absz. eltérés: ' + roomControlNumber(row.state_error_k) + ' K'
                + '\nnyitással súlyozott állapotidő: ' + roomControlNumber(row.state_seconds / 3600) + ' h'
                + '\nrészarány a fűtés ' + (state.key.endsWith('_on') ? 'be' : 'ki') + ' idején: ' + roomControlNumber(row.state_share_pct, 0) + '%'
                + '\nadatlefedettség: ' + roomControlNumber(row.coverage_pct, 0) + '%' : '\nNincs megfigyelt állapotidő.');
            // A group is a full rectangular hit target; cloning it would duplicate cell labels.
            bindPlotCurveTooltip(cell, label, 6, false);
        });
    });
    roomControlText(plot, 'az adott állapot átlagos abszolút eltérése', dims.w / 2, dims.h + 7, 4);
}

function roomControlStateDistribution(row, heating) {
    if (!(row?.valid_seconds > 0) || !Number.isFinite(row.heating_seconds)) return null;
    const seconds = heating ? row.heating_seconds : row.valid_seconds - row.heating_seconds;
    const side = heating ? '_on' : '_off';
    const below = row.quadrant_seconds?.['below' + side], above = row.quadrant_seconds?.['above' + side];
    if (!(seconds > 0) || ![below, above].every(value => Number.isFinite(value) && value >= 0) || below + above > seconds + 1e-6) return null;
    return {seconds, below: 100 * below / seconds, within: 100 * Math.max(0, seconds - below - above) / seconds, above: 100 * above / seconds};
}

function roomControlStateHours(row, heating, dailyAverage = false) {
    if (!(row?.valid_seconds > 0) || !Number.isFinite(row.heating_seconds) || row.heating_seconds < 0 || row.heating_seconds > row.valid_seconds) return null;
    const days = dailyAverage ? row.observed_days : 1;
    if (!(days > 0)) return null;
    return (heating ? row.heating_seconds : row.valid_seconds - row.heating_seconds) / 3600 / days;
}

function roomControlStateParts(heating) {
    const green = '#8fbc79', red = '#e58d8d';
    return [{key: 'below', label: 'kért alatt', fill: heating ? green : red},
        {key: 'within', label: '±0,5 K', fill: 'white'}, {key: 'above', label: 'kért felett', fill: heating ? red : green}];
}

function drawRoomControlDiagnostic(data, setting) {
    const room = setting.roomNumToPlot;
    const days = roomControlDays(setting.day, setting.windowDays);
    const today = data[setting.day]?.room_control_kpis?.rooms?.[room];
    const previous = aggregateRoomControlKPIs(days.slice(0, -1).map(day => data[day]?.room_control_kpis?.rooms?.[room]));
    const area = drawPlot([], {parentId: 'graph', margins: {top: .22, right: .03, bottom: .05, left: .03},
        domain: {bottom: [0, 1], left: [0, 1]}, dataKeys: {bottom: 'x', left: 'y'}, axes: {left: false, bottom: false},
        plotLabel: '', curveEndText: {show: false}, plotDateNavigation: {day: setting.day, onDayChange: navigateRoomControlDay}});
    drawPlotTitleSelector(area.plotElement.append('g').attr('transform', 'translate(0,-18)'),
        area.plotDims, roomAnalyticTabs(setting), isMobile ? 10 : 7);
    const {plotElement: plot, plotDims: dims} = area;
    roomControlText(plot, 'átl. absz. eltérés (fűtés): ' + roomControlNumber(today?.mae_on_c) + ' K  |  7 nap: ' + roomControlNumber(previous.mae_on_c) + ' K', dims.w / 2, -12, 5);
    roomControlText(plot, 'komfortidő jelenlétkor: ' + roomControlNumber(today?.comfort_pct, 0) + '%  |  7 nap: ' + roomControlNumber(previous.comfort_pct, 0) + '%  (±0,5 K)', dims.w / 2, -5, 5);
    const currentDay = setting.day === dayStamp() ? 'ma' : setting.day.slice(5).replace('-', '.');
    if (!(today?.valid_seconds > 0) && !previous.valid_seconds) {
        roomControlText(plot, 'Nincs elegendő szabályozási adat.', dims.w / 2, dims.h / 2);
        return;
    }
    const left = 28, width = dims.w - left - 31, blockHeight = dims.h / 2, barHeight = blockHeight * .2;
    [true, false].forEach((heating, index) => {
        const y = index * blockHeight;
        const parts = roomControlStateParts(heating);
        plot.append('rect').attr('class', 'room-kpi-state-background').attr('data-state', heating ? 'on' : 'off')
            .attr('x', 0).attr('y', y).attr('width', dims.w).attr('height', blockHeight - 1)
            .attr('fill', heating ? '#fff0f3' : '#eef5ff');
        const current = roomControlStateDistribution(today, heating), reference = roomControlStateDistribution(previous, heating);
        roomControlText(plot, heating ? 'fűtés be' : 'fűtés ki', dims.w / 2, y + 7, 5);
        [[current, today, currentDay], [reference, previous, '7 nap']].forEach(([distribution, row, label], rowIndex) => {
            const barY = y + 12 + rowIndex * (barHeight + 3);
            const group = plot.append('g').attr('class', 'room-kpi-state-bar').attr('data-state', heating ? 'on' : 'off')
                .attr('data-period', rowIndex ? 'week' : 'day');
            const hours = roomControlStateHours(row, heating, Boolean(rowIndex));
            const duration = Number.isFinite(hours) ? (hours > 0 && hours < .1 ? '<0,1' : roomControlNumber(hours)) + (rowIndex ? ' h/nap' : ' h') : '—';
            roomControlText(group, label, left - 3, barY + barHeight * .72, 4.5, 'end');
            roomControlText(group, duration, left + width + 3, barY + barHeight * .72, 4.5, 'start');
            let offset = 0;
            if (distribution) parts.forEach(part => {
                const percentage = distribution[part.key], partWidth = width * percentage / 100;
                group.append('rect').attr('x', left + offset).attr('y', barY).attr('width', partWidth).attr('height', barHeight)
                    .attr('fill', part.fill).attr('stroke', '#aaa').attr('stroke-width', .2);
                if (partWidth >= 12) roomControlText(group, roomControlNumber(percentage, 0) + '%', left + offset + partWidth / 2, barY + barHeight * .72, 4);
                offset += partWidth;
            });
            group.append('rect').attr('x', left).attr('y', barY).attr('width', width).attr('height', barHeight)
                .attr('class', 'room-kpi-bar-outline').attr('fill', 'none').attr('stroke', '#888').attr('stroke-width', .4);
            if (!distribution) roomControlText(group, '—', left + width / 2, barY + barHeight * .72, 4, 'middle', '#aaa');
            bindPlotCurveTooltip(group, label + (rowIndex ? ' — napi átlag, ' + previous.observed_days + ' megfigyelt nap' : '')
                + (distribution ? parts.map(part => '\n' + part.label + ': ' + roomControlNumber(distribution[part.key]) + '%').join('') : '\nNincs megfigyelt adat.'), 6, false);
        });
        parts.forEach((part, partIndex) => {
            const x = left + width * (partIndex + .5) / 3;
            plot.append('rect').attr('x', x - 17).attr('y', y + blockHeight - 7).attr('width', 4).attr('height', 4)
                .attr('fill', part.fill).attr('stroke', '#aaa').attr('stroke-width', .3);
            roomControlText(plot, part.label, x - 11, y + blockHeight - 3.5, 3.8, 'start');
        });
    });
}
