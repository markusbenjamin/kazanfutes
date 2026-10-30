// Seven-calendar-day dwell-time histogram. Never bin the interpolated trajectory.
function roomPhaseSummaryDays(setting) {
    const count = Number.isInteger(setting.windowDays) && setting.windowDays > 0 ? setting.windowDays : 7;
    return Array.from({length: count}, (_, index) => shiftedSelectorDay(setting.day, index - count + 1));
}

function selectRoomPhaseSummaryPresence(presenceMode) {
    if (mainGraphSetting.title !== 'room_control_diagnostic' || mainGraphSetting.roomNumToPlot == null
        || !['all', 'occupied', 'empty'].includes(presenceMode)) return;
    roomPhaseSummaryPresence[mainGraphSetting.roomNumToPlot] = presenceMode;
    mainGraphSetting = {...mainGraphSetting, presenceMode};
    mainGraphContentLocked = true;
    drawMainGraph({});
    drawMainGraph();
}

function roomPhaseSummaryHour(row, day) {
    if (typeof row?.timestamp !== 'string' || !row.timestamp.startsWith(day + '-')) return NaN;
    const parts = row.timestamp.split('-').map(Number);
    if (parts.length !== 6 || parts[3] < 0 || parts[3] > 23 || parts[4] < 0 || parts[4] > 59 || parts[5] < 0 || parts[5] > 59) return NaN;
    return parts[3] + parts[4] / 60 + parts[5] / 3600;
}

function roomPhaseSummaryData(data, setting) {
    const days = roomPhaseSummaryDays(setting), bins = new Map(), movements = new Map();
    const presenceMode = setting.presenceMode || 'occupied';
    const states = {cold: 0, good: 0, warm: 0};
    let seconds = 0, observedDays = 0;
    const valid = row => row && ['measured', 'estimated'].includes(row.source)
        && Number.isFinite(row.error_k) && Number.isFinite(row.intensity_k);
    for (const day of days) {
        const payload = data[day]?.['room_' + setting.roomNumToPlot + '_phase_points'];
        if (payload?.schema_version !== 1 || !Array.isArray(payload.points)) continue;
        const end = day === dayStamp() ? getFractionalHourOfDay() : 24;
        const offset = Number.isFinite(payload.offset_k) ? payload.offset_k : 0;
        // Last duplicate wins, including explicit unavailable records.
        const byHour = new Map();
        payload.points.forEach(row => {
            const hour = roomPhaseSummaryHour(row, day);
            if (Number.isFinite(hour) && hour <= end) byHour.set(hour, row);
        });
        const rows = [...byHour].sort((a,b) => a[0] - b[0]);
        const presence = ['occupied', 'empty'].includes(presenceMode) ? extractRoomOccupancyPeriods(
            (data[day]?.['room_' + setting.roomNumToPlot + '_environment'] || []).map(row => ({...row,
                // Absence must be explicitly observed; unknown is neither occupied nor empty.
                ...(presenceMode === 'empty' && Object.hasOwn(row, 'occupancy')
                    ? {occupancy: row.occupancy === 0 ? 1 : row.occupancy === 1 ? 0 : null} : {}),
                h_of_day_frac: Number.isFinite(row.h_of_day_frac) ? row.h_of_day_frac : roomPhaseSummaryHour(row, day)})), end) : null;
        let daySeconds = 0;
        for (let index = 0; index + 1 < rows.length; index++) {
            const [start, row] = rows[index], [stop, next] = rows[index + 1];
            if (!valid(row) || !valid(next) || !(stop > start) || stop - start > 3 / 60 + 1e-9) continue;
            const radiator = row.intensity_k + offset, deviation = -row.error_k;
            if (radiator < 0) continue;
            const hours = presence ? presence.reduce((sum, period) =>
                sum + Math.max(0, Math.min(stop, period.x2) - Math.max(start, period.x1)), 0) : stop - start;
            if (!(hours > 0)) continue;
            const duration = Math.round(hours * 3600 * 1000) / 1000;
            const x1 = Math.floor(radiator / 2) * 2, y1 = Math.floor(deviation / .5) * .5;
            const key = x1 + '/' + y1;
            const bin = bins.get(key) || {x1, x2: x1 + 2, y1, y2: y1 + .5, seconds: 0};
            bin.seconds += duration;
            bins.set(key, bin);
            // Coarser direction grid keeps the overlay readable. Average velocity,
            // not point counts, and never differentiate across a source fallback.
            if (row.source === next.source && next.intensity_k + offset >= 0) {
                const mx = Math.floor(radiator / 4) * 4, my = Math.floor(deviation);
                const movementKey = mx + '/' + my;
                const movement = movements.get(movementKey) || {x1: mx, y1: my, seconds: 0, dx: 0, dy: 0, travel: 0};
                const fraction = hours / (stop - start);
                const dx = (next.intensity_k - row.intensity_k) * fraction;
                const dy = (row.error_k - next.error_k) * fraction;
                movement.seconds += duration;
                movement.dx += dx;
                movement.dy += dy;
                movement.travel += Math.hypot(dx / 4, dy);
                movements.set(movementKey, movement);
            }
            const state = deviation < -ROOM_PHASE_ROOM_BAND_K ? 'cold' : deviation > ROOM_PHASE_ROOM_BAND_K ? 'warm' : 'good';
            states[state] += duration;
            seconds += duration;
            daySeconds += duration;
        }
        if (daySeconds > 0) observedDays++;
    }
    return {days, seconds, observedDays, states,
        cells: [...bins.values()].map(cell => ({...cell, percent: cell.seconds / seconds * 100})),
        arrows: [...movements.values()].flatMap(movement => {
            const net = Math.hypot(movement.dx / 4, movement.dy);
            const coherence = movement.travel ? net / movement.travel : 0;
            const vx = movement.dx * 3600 / movement.seconds, vy = movement.dy * 3600 / movement.seconds;
            // At least five observed minutes, a non-negligible drift, and no
            // misleading arrow where opposing movements mostly cancel out.
            return movement.seconds >= 300 && coherence >= .25 && Math.hypot(vx / 4, vy) / 6 >= .02
                ? [{...movement, vx, vy, coherence}] : [];
        })};
}

function drawRoomPhaseSummaryView(data = null, setting = mainGraphSetting) {
    if (data === null) {
        const types = roomPhaseSummaryTypes(setting.roomNumToPlot);
        collectDataFromGitHub(roomPhaseSummaryDays(setting).flatMap(day => types.map(type => ({day, type}))), loaded => {
            if (mainGraphSetting === setting) drawRoomControlView(loaded);
        });
        return;
    }
    clearMainGraphs();
    drawRoomPhaseSummary(data, setting);
}

function drawRoomPhaseSummary(data, setting) {
    const summary = roomPhaseSummaryData(data, setting), {cells, seconds} = summary;
    const presenceMode = setting.presenceMode || 'occupied';
    const xTop = Math.max(20, ...cells.map(cell => cell.x2));
    const yBottom = Math.min(-2, ...cells.map(cell => cell.y1)), yTop = Math.max(2, ...cells.map(cell => cell.y2));
    const area = drawPlot([], {parentId: 'graph', margins: {top: .18, right: .1, bottom: .18, left: .12},
        domain: {bottom: [0,xTop], left: [yBottom,yTop], niceLeft: false},
        dataKeys: {bottom: 'intensity_k', left: 'deviation_k'}, plotLabel: '', curveEndText: {show: false},
        axesLabel: {bottom: 'radiátor - szoba hőmérséklet (K)', left: 'eltérés: mért − kért (K)'},
        plotDateNavigation: {day: setting.day, onDayChange: navigateRoomControlDay},
        emptyMessage: seconds ? '' : presenceMode === 'occupied' ? 'Jelenlétkor nincs érvényes fázisadat.'
            : presenceMode === 'empty' ? 'Üresen nincs érvényes fázisadat.' : 'Nincs érvényes fázisadat erre az időszakra.'});
    const scale = isMobile ? mobileViewScaler : 1;
    drawPlotTitleSelector(area.plotElement.append('g').attr('transform', `translate(0,${-10 * scale})`),
        area.plotDims, roomAnalyticTabs(setting), 7 * scale);
    drawPlotTitleSelector(area.plotElement.append('g').attr('class', 'room-phase-summary-presence-selector'),
        area.plotDims, {prefix: '', selected: presenceMode, choices: [
            {key: 'occupied', label: 'jelenlét', color: 'black'},
            {key: 'empty', label: 'üres', color: 'black'},
            {key: 'all', label: 'össz', color: 'black'}
        ], onSelect: selectRoomPhaseSummaryPresence}, 5.5 * scale);
    const number = (value, precision = 1) => Number(value.toFixed(precision)).toString().replace('.', ',');
    const x = d3.scaleLinear().domain([0,xTop]).range([0,area.plotDims.w]);
    const y = d3.scaleLinear().domain([yBottom,yTop]).range([area.plotDims.h,0]);
    const peak = Math.max(0, ...cells.map(cell => cell.percent));
    const gray = fraction => {const value = Math.round(255 - 220 * Math.sqrt(fraction)); return `rgb(${value},${value},${value})`;};
    cells.forEach(cell => {
        const rect = area.plotElement.append('rect').attr('class', 'room-phase-summary-cell')
            .attr('data-seconds', cell.seconds).attr('data-percent', cell.percent)
            .attr('x', x(cell.x1)).attr('y', y(cell.y2))
            .attr('width', x(cell.x2) - x(cell.x1)).attr('height', y(cell.y1) - y(cell.y2))
            .attr('fill', gray(cell.percent / peak)).attr('stroke', 'none').attr('shape-rendering', 'crispEdges');
        bindPlotCurveTooltip(rect, 'radiátor: ' + number(cell.x1) + '–' + number(cell.x2) + ' K\neltérés: '
            + number(cell.y1) + '–' + number(cell.y2) + ' K\n' + number(cell.seconds / 3600, 2)
            + ' h · ' + number(cell.percent) + '%', 6, false);
    });
    const guide = (x1,y1,x2,y2) => area.plotElement.append('line').attr('class', 'room-phase-summary-guide')
        .attr('x1',x1).attr('y1',y1).attr('x2',x2).attr('y2',y2)
        .attr('stroke','#999').attr('stroke-width',.3).attr('stroke-dasharray','2,2').attr('pointer-events','none');
    [-1,0,1].forEach(value => guide(0,y(value),area.plotDims.w,y(value)));
    [5,15].forEach(value => guide(x(value),0,x(value),area.plotDims.h));
    summary.arrows.forEach(arrow => {
        const dx = x(arrow.vx) - x(0), dy = y(arrow.vy) - y(0), norm = Math.hypot(dx,dy);
        const length = Math.min(10 * scale, (x(4) - x(0)) * .7, (y(0) - y(1)) * .7);
        const angle = Math.atan2(dy,dx) * 180 / Math.PI;
        const cx = x(Math.min(arrow.x1 + 2, xTop - 1));
        const cy = y(Math.max(yBottom + .5, Math.min(arrow.y1 + .5, yTop - .5)));
        if (!(norm > 0 && length > 0)) return;
        const group = area.plotElement.append('g').attr('class', 'room-phase-summary-arrow')
            .attr('data-vx',arrow.vx).attr('data-vy',arrow.vy)
            .attr('transform',`translate(${cx},${cy}) rotate(${angle})`);
        const half = length / 2, wing = length * .28;
        const path = `M${-half},0 L${half},0 M${half-wing},${-wing} L${half},0 L${half-wing},${wing}`;
        group.append('path').attr('d',path).attr('fill','none').attr('stroke','white')
            .attr('stroke-width',2 * scale).attr('stroke-linejoin','round').attr('pointer-events','none');
        group.append('path').attr('d',path).attr('fill','none').attr('stroke','red')
            .attr('stroke-width',.65 * scale).attr('stroke-linejoin','round');
        // A wider invisible hit target keeps the small arrows easy to inspect.
        const hit = group.append('path').attr('d',path).attr('fill','none').attr('stroke','transparent')
            .attr('stroke-width',4 * scale);
        bindPlotCurveTooltip(hit, 'átlagos irány\nradiátor: ' + number(arrow.vx,2)
            + ' K/h\neltérés: ' + number(arrow.vy,2) + ' K/h', 6, false);
    });
    if (peak) {
        const height = area.plotDims.h * .4;
        for (let index = 0; index < 20; index++) area.plotElement.append('rect')
            .attr('class','room-phase-summary-color-key').attr('x',area.plotDims.w + 4)
            .attr('y',index * height / 20 + 6).attr('width',3).attr('height',height / 20 + .05)
            .attr('fill',gray(1 - index / 19)).attr('stroke','none');
        roomControlText(area.plotElement, number(peak) + '%', area.plotDims.w + 4, 3, 4, 'start', '#777');
        roomControlText(area.plotElement, '0%', area.plotDims.w + 4, height + 12, 4, 'start', '#777');
    }
}
