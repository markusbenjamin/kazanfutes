// One chronological trajectory through valid observations, including across gaps.
function roomPhaseSegments(points, day, offsetK = 0) {
    const trajectory = [];
    for (const point of points) {
        const parts = point.timestamp?.split('-').map(Number);
        const hour = parts?.length === 6 ? parts[3] + parts[4] / 60 + parts[5] / 3600 : NaN;
        if (!point.timestamp?.startsWith(day + '-') || !Number.isFinite(hour) ||
            !Number.isFinite(point.error_k) || !Number.isFinite(point.intensity_k) ||
            !['measured', 'estimated'].includes(point.source)) continue;
        // Undo the payload's encoded reference shift for this zero-offset view.
        trajectory.push({...point, intensity_k: point.intensity_k + offsetK,
            deviation_k: -point.error_k, h_of_day_frac: hour});
    }
    return trajectory.length ? [trajectory] : [];
}

function roomPhaseTooltip(point) {
    return point.timestamp.slice(11,16).replace('-', ':');
}

function roomPhaseHourlyPoints(points) {
    if (!points.length) return [];
    const selected = [], seen = new Set();
    const latestHour = Math.floor(points.at(-1).h_of_day_frac);
    for (let hour = 0; hour <= latestHour; hour++) {
        const nearest = points.reduce((best, point) =>
            Math.abs(point.h_of_day_frac - hour) < Math.abs(best.h_of_day_frac - hour) ? point : best);
        if (seen.has(nearest.timestamp)) continue;
        seen.add(nearest.timestamp);
        selected.push(nearest);
    }
    return selected;
}

function roomPhaseSmoothedPoints(points, windowMinutes = 30) {
    const halfWindow = windowMinutes / 120;
    let left = 0, right = 0, errorSum = 0, intensitySum = 0;
    return points.map((point, index) => {
        while (right < points.length && points[right].h_of_day_frac <= point.h_of_day_frac + halfWindow) {
            errorSum += points[right].error_k;
            intensitySum += points[right].intensity_k;
            right++;
        }
        while (left < right && points[left].h_of_day_frac < point.h_of_day_frac - halfWindow) {
            errorSum -= points[left].error_k;
            intensitySum -= points[left].intensity_k;
            left++;
        }
        // Anchor the path to its actual first and current positions.
        if (index === 0 || index === points.length - 1) return {...point};
        const error = errorSum / (right - left);
        return {...point, error_k: error, deviation_k: -error, intensity_k: intensitySum / (right - left)};
    });
}

function roomPhasePointDirection(points, index, x, y) {
    const point = points[index];
    if (!point) return null;
    const end = [x(point.intensity_k), y(-point.error_k)];
    let previousIndex = null;
    const distinct = step => {
        for (let neighbour = index + step; neighbour >= 0 && neighbour < points.length; neighbour += step) {
            const position = [x(points[neighbour].intensity_k), y(-points[neighbour].error_k)];
            if (Math.hypot(position[0] - end[0], position[1] - end[1]) > .01) {
                if (step < 0) previousIndex = neighbour;
                return position;
            }
        }
        return null;
    };
    const previous = distinct(-1), next = distinct(1);
    if (!previous && !next) return null;
    let dx, dy;
    if (previous && next) {
        // Tangent of the same centripetal Catmull–Rom interpolation used below.
        const before = Math.sqrt(Math.hypot(end[0] - previous[0], end[1] - previous[1]));
        const after = Math.sqrt(Math.hypot(next[0] - end[0], next[1] - end[1]));
        dx = (end[0] - previous[0]) / before - (next[0] - previous[0]) / (before + after) + (next[0] - end[0]) / after;
        dy = (end[1] - previous[1]) / before - (next[1] - previous[1]) / (before + after) + (next[1] - end[1]) / after;
    }
    if (!previous || !next || Math.hypot(dx, dy) < .0001) {
        dx = next ? next[0] - end[0] : end[0] - previous[0];
        dy = next ? next[1] - end[1] : end[1] - previous[1];
    }
    const distance = Math.hypot(dx, dy);
    return {end, dx: dx / distance, dy: dy / distance, previousIndex};
}

function roomPhaseDirection(points, x, y) {
    return roomPhasePointDirection(points, points.length - 1, x, y);
}

function roomPhaseMovement(points, direction) {
    const movement = {room: null, radiator: null};
    if (!direction || direction.previousIndex === null) return movement;
    const last = points.at(-1), previous = points[direction.previousIndex];
    const elapsed = last.h_of_day_frac - previous.h_of_day_frac;
    // Use the arrow's exact incoming segment, expressed as K per ten minutes.
    // A long gap is not evidence for a current heating/cooling state.
    if (!(elapsed > 0) || elapsed > 10 / 60 + 1e-9) return movement;
    const roomChange = (previous.error_k - last.error_k) / elapsed / 6;
    const radiatorChange = (last.intensity_k - previous.intensity_k) / elapsed / 6;
    if (Math.abs(roomChange) >= .1 - 1e-9)
        movement.room = direction.dy < 0 ? 'melegszik' : 'hűl';
    if (Math.abs(radiatorChange) >= .5 - 1e-9)
        movement.radiator = direction.dx > 0 ? 'melegszik' : 'hűl';
    return movement;
}

// Plot-only classification band; independent of the real heating controller.
const ROOM_PHASE_ROOM_BAND_K = 1;

function roomPhaseDiagnosticText(points, direction) {
    const last = points.at(-1);
    if (!last) return '';
    const movement = roomPhaseMovement(points, direction);
    const roomState = Number.isFinite(last.error_k)
        ? last.error_k > ROOM_PHASE_ROOM_BAND_K ? 'hideg' : last.error_k < -ROOM_PHASE_ROOM_BAND_K ? 'meleg' : 'jó' : null;
    const excess = Number.isFinite(last.radiator_temp_c) && Number.isFinite(last.room_temp_c)
        ? last.radiator_temp_c - last.room_temp_c : last.intensity_k;
    const radiatorState = Number.isFinite(excess) ? excess > 15 ? 'meleg' : excess > 5 ? 'langyos' : 'hideg' : null;
    return [['szoba', roomState, movement.room], ['radiátor', radiatorState, movement.radiator]]
        .filter(([, state, motion]) => state || motion)
        .map(([name, state, motion]) => name + ' ' + [state, motion].filter(Boolean)
            .join(name === 'szoba' && state === 'jó' ? ' de ' : ' és ')).join(', ');
}

function drawRoomPhasePlot(data, setting) {
    const aggregate = setting.roomNumToPlot == null;
    const curves = roomControlPlotRooms(setting).map(room => {
        const payload = data[setting.day]?.['room_' + room + '_phase_points'];
        const offsetK = Number.isFinite(payload?.offset_k) ? payload.offset_k : 0;
        const points = payload?.schema_version === 1 ? roomPhaseSegments(payload.points || [], setting.day, offsetK).flat() : [];
        return {room, name: roomsDataAndState[room].name, color: roomsColorScale(roomsColorRemap[room - 1]),
            points, smoothedPoints: roomPhaseSmoothedPoints(points)};
    }).filter(curve => curve.points.length);
    const points = curves.flatMap(curve => curve.points);
    const legendRows = aggregate ? roomAnalyticLegendLayout(curves).rows : 0;
    const errors = points.map(point => point.deviation_k);
    const yBottom = Math.min(-1, Math.floor(Math.min(0, ...errors) * 2) / 2 - .5);
    const yTop = Math.max(1, Math.ceil(Math.max(0, ...errors) * 2) / 2 + .5);
    const xBottom = 0;
    const xTop = Math.max(20, Math.ceil(Math.max(0, ...points.map(point => point.intensity_k)) / 10) * 10);
    const common = {parentId: 'graph', margins: {top: (aggregate ? .13 : .17) + legendRows * .05, right: .04, bottom: .18, left: .12},
        domain: {bottom: [xBottom,xTop], left: [yBottom,yTop], niceLeft: false},
        dataKeys: {bottom: 'intensity_k', left: 'deviation_k'}, smoothing: {bottom: 0, left: 0},
        axesLabel: {bottom: 'radiátor - szoba hőmérséklet (K)', left: 'eltérés: mért − kért (K)'},
        plotStyle: {joined: false, startCap: false, endCap: false},
        segment: {do: false}, curveEndText: {show: false}, plotLabel: ''};
    const area = drawPlot([], {...common, plotLabelTabs: false,
        plotDateNavigation: {day: setting.day, onDayChange: navigateRoomControlDay},
        emptyMessage: points.length ? '' : 'Az adott napra nincs érvényes fázispont.'});
    const labelScale = isMobile ? mobileViewScaler : 1;
    let stateLabel;
    if (aggregate) drawRoomAnalyticHeading(area, setting, curves, 'room-phase');
    else {
        drawPlotTitleSelector(area.plotElement.append('g').attr('class', 'room-phase-title')
            .attr('transform', `translate(0,${-8.4 * labelScale})`), area.plotDims, roomAnalyticTabs(setting), 7 * labelScale);
        stateLabel = area.plotElement.append('text').attr('class', 'room-phase-state')
            .attr('x', area.plotDims.w / 2).attr('y', -2.5 * labelScale)
            .style('text-anchor', 'middle').style('font-family', dashboardFont)
            .style('font-size', 6 * labelScale + 'px').style('fill', '#777').style('pointer-events', 'none').text('');
    }
    const x = d3.scaleLinear().domain(common.domain.bottom).range([0,area.plotDims.w]);
    const y = d3.scaleLinear().domain(common.domain.left).range([area.plotDims.h,0]);
    area.plotElement.append('line').attr('class', 'room-phase-zero-line')
        .attr('x1', x(0)).attr('x2', x(0)).attr('y1', 0).attr('y2', area.plotDims.h)
        .attr('stroke', '#bbb').attr('stroke-width', .4).attr('stroke-dasharray', '2,2');
    area.plotElement.append('line').attr('class', 'room-phase-zero-line')
        .attr('x1', 0).attr('x2', area.plotDims.w).attr('y1', y(0)).attr('y2', y(0))
        .attr('stroke', '#bbb').attr('stroke-width', .4).attr('stroke-dasharray', '2,2');
    curves.forEach(curve => {
        const {smoothedPoints} = curve;
        const tooltip = point => (aggregate ? curve.name + ' · ' : '') + roomPhaseTooltip(point);
        const group = area.plotElement.append('g').attr('class', 'room-phase-room').attr('data-room', curve.room)
            .attr('data-emphasized', 'false').attr('tabindex', 0).attr('aria-label', curve.name);
        const thickness = isMobile ? 2.5 : 1.25;
        // Smooth both coordinates in time, then interpolate the resulting trajectory.
        const line = d3.line().x(point => x(point.intensity_k)).y(point => y(point.deviation_k))
            .curve(d3.curveCatmullRom.alpha(.5));
        const path = line(smoothedPoints);
        const halo = group.append('path').attr('class', 'room-phase-hover-halo').attr('d', path)
            .attr('fill', 'none').attr('stroke', 'rgba(255,255,255,0.5)').attr('stroke-width', thickness * 3)
            .attr('opacity', 0).attr('pointer-events', 'none');
        const trajectory = group.append('path').attr('class', 'room-phase-trajectory')
            .attr('data-room', curve.room).attr('d', path)
            .attr('fill', 'none').attr('stroke', curve.color).attr('stroke-width', thickness)
            .attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round').attr('pointer-events', 'none');
        const hitArea = group.append('path').attr('class', 'room-phase-hit-area').attr('d', path)
            .attr('fill', 'none').attr('stroke', 'transparent').attr('stroke-width', thickness * 4)
            .attr('pointer-events', 'stroke');
        bindPlotCurveTooltip(hitArea, curve.name, 6, false);
        const first = smoothedPoints[0];
        if (!aggregate) for (const point of roomPhaseHourlyPoints(smoothedPoints)) {
            // The existing large start/end markers already cover these positions.
            if (point === first || point === smoothedPoints.at(-1)) continue;
            const direction = roomPhasePointDirection(smoothedPoints, smoothedPoints.indexOf(point), x, y);
            if (!direction) continue;
            const angle = Math.atan2(direction.dy, direction.dx) * 180 / Math.PI;
            const hourly = group.append('path').attr('class', 'room-phase-time-point')
                .attr('data-room', curve.room).attr('data-timestamp', point.timestamp)
                .attr('transform', `translate(${x(point.intensity_k)},${y(point.deviation_k)}) rotate(${angle})`)
                .attr('d', 'M2,0L-1.5,-1.25L-1,0L-1.5,1.25Z').attr('fill', 'black');
            bindPlotCurveTooltip(hourly, tooltip(point), 6, false);
        }
        const startDirection = roomPhasePointDirection(smoothedPoints, 0, x, y);
        const startAngle = startDirection ? Math.atan2(startDirection.dy, startDirection.dx) * 180 / Math.PI : 0;
        const startTransform = `translate(${x(first.intensity_k)},${y(first.deviation_k)}) rotate(${startAngle})`;
        const start = group.append(startDirection ? 'path' : 'circle').attr('class', 'room-phase-start-marker')
            .attr('data-room', curve.room).attr('data-timestamp', first.timestamp)
            .attr('transform', startTransform).attr('d', startDirection ? 'M3.5,0L-2.5,-2L-2.5,2Z' : null)
            .attr('r', startDirection ? null : 2.5).attr('fill', 'black');
        bindPlotCurveTooltip(start, tooltip(first), 6, false);
        const last = curve.points.at(-1);
        const direction = roomPhaseDirection(smoothedPoints, x, y);
        if (!aggregate) stateLabel.text(roomPhaseDiagnosticText(smoothedPoints, direction));
        if (direction) {
            const {end: [cx, cy], dx, dy} = direction;
            const tipX = cx + dx * 11, tipY = cy + dy * 11;
            group.append('path').attr('class', 'room-phase-direction')
                .attr('data-room', curve.room)
                .attr('d', `M${cx + dx * 3},${cy + dy * 3}L${tipX},${tipY}`
                    + `M${tipX - dx * 3 - dy * 2},${tipY - dy * 3 + dx * 2}`
                    + `L${tipX},${tipY}L${tipX - dx * 3 + dy * 2},${tipY - dy * 3 - dx * 2}`)
                .attr('fill', 'none').attr('stroke', 'red').attr('stroke-width', .8)
                .attr('stroke-linecap', 'round').attr('stroke-linejoin', 'round').attr('pointer-events', 'none');
        }
        const marker = group.append('circle').attr('class', 'room-phase-latest-point')
            .attr('data-room', curve.room)
            .attr('cx', x(last.intensity_k)).attr('cy', y(last.deviation_k)).attr('r', 3)
            .attr('fill', curve.color).attr('stroke', 'white').attr('stroke-width', .4);
        bindPlotCurveTooltip(marker, tooltip(last), 6, false);
        // A single-room view keeps all geometry and styling fixed; only tooltips hover.
        if (!aggregate) return;
        const emphasize = () => {
            group.raise().attr('data-emphasized', 'true');
            trajectory.attr('stroke-width', thickness * 2);
            halo.attr('opacity', 1);
            start.attr('transform', startTransform + ' scale(1.5)');
            marker.attr('r', 6);
        };
        const restore = () => {
            group.attr('data-emphasized', 'false');
            trajectory.attr('stroke-width', thickness);
            halo.attr('opacity', 0);
            start.attr('transform', startTransform);
            marker.attr('r', 3);
        };
        group.on('mouseenter.phase-focus', emphasize).on('mouseleave.phase-focus', restore)
            .on('focusin.phase-focus', emphasize).on('focusout.phase-focus', restore);
    });
}
