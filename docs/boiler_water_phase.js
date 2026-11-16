// Both coordinates come from the same observation, never independently joined.
function boilerWaterPhaseCurves(data, setting) {
    const mode = setting.phaseMode || 'average';
    const average = mode === 'average';
    const cycles = average ? boilerEnabledCycles(data.heating_state) : [1,2,3,4];
    const curves = average
        ? [{label: 'átlagos fűtővíz hőm.', color: 'rgb(200,0,0)',
            readings: boilerAverageWaterTemperatures(data, cycles)}]
        : BOILER_DEMAND_CYCLES.filter(part => mode === 'all' || String(part.cycle) === mode).map(part => ({...part,
            readings: data['cycle_' + part.cycle + '_water_temps'] || []}));
    const powerReadings = (data.pumps_power || [])
        .filter(row => row.cp !== true && Number.isFinite(row.h_of_day_frac))
        .slice().sort((a,b) => a.h_of_day_frac - b.h_of_day_frac);
    return curves.map(curve => {
        // Pump watts are change-logged, so hold each actual measurement until
        // the next one. Ignore synthetic plotting changepoints and never use
        // future measurements, commanded states or heatmeter flow as evidence.
        // The mean is shown when at least one member pump draws positive power.
        const members = average ? cycles || [] : [curve.cycle];
        let powerIndex = -1;
        const pumping = point => {
            while (powerIndex + 1 < powerReadings.length
                && powerReadings[powerIndex + 1].h_of_day_frac <= point.h_of_day_frac) powerIndex++;
            const reading = powerReadings[powerIndex];
            return members.some(cycle => {
                const watts = reading?.['pump_' + cycle + '_power'];
                return Number.isFinite(watts) && watts > 0;
            });
        };
        // One chronological path through the retained observations, including
        // across idle periods and missing readings. No observations are filled
        // into those gaps; the dots and smoothing use precisely the same data.
        const scatter = curve.readings.slice().sort((a,b) => a.h_of_day_frac - b.h_of_day_frac)
            .filter(point => Number.isFinite(point.h_of_day_frac)
                && isValidCycleWaterTemperature(point.water_temp)
                && isValidCycleWaterTemperature(point.return_temp) && pumping(point));
        const segments = scatter.length ? [scatter] : [];
        return {...curve, segments, scatter};
    });
}

function selectBoilerWaterPhase(mode) {
    if (mainGraphSetting.title !== 'boiler_kpi' || mainGraphSetting.metric !== 'phase'
        || !['average', 'all', '1', '2', '3', '4'].includes(mode)) return;
    boilerWaterPhaseSelection = mode;
    mainGraphSetting = createBoilerKPIPlotSetting(mainGraphSetting.day, 'phase');
    mainGraphContentLocked = true;
    drawMainGraph({});
    drawMainGraph();
}

function boilerWaterPhaseTabs(setting) {
    return {prefix: '', selected: setting.phaseMode || 'average', choices: [
        {key: 'average', label: 'átlag', color: 'rgb(200,0,0)'},
        {key: 'all', label: 'összes', color: 'black'},
        ...BOILER_DEMAND_CYCLES.map(part => ({key: String(part.cycle), label: part.label, color: part.color}))
    ], onSelect: selectBoilerWaterPhase};
}

function boilerWaterPhaseSmooth(points, sigmaMinutes = 5) {
    // Smooth both coordinates against time with the same Gaussian weights.
    // Five-minute sigma, truncated at ±15 minutes; preserve chronological loops.
    // Distant observations remain connected by the drawn path, but do not enter
    // each other's averaging window. The raw scatter is never changed.
    const sigmaHours = sigmaMinutes / 60;
    let left = 0, right = 0;
    return points.map(point => {
        while (left < points.length && point.h_of_day_frac - points[left].h_of_day_frac > 3 * sigmaHours) left++;
        while (right < points.length && points[right].h_of_day_frac - point.h_of_day_frac <= 3 * sigmaHours) right++;
        let weight = 0, supply = 0, returned = 0;
        for (let index = left; index < right; index++) {
            const sample = points[index];
            const w = Math.exp(-.5 * ((sample.h_of_day_frac - point.h_of_day_frac) / sigmaHours) ** 2);
            weight += w;
            supply += w * sample.water_temp;
            returned += w * sample.return_temp;
        }
        return {...point, water_temp: supply / weight, return_temp: returned / weight};
    });
}

function boilerWaterPhaseRange(curves) {
    const values = curves.flatMap(curve => curve.segments.flat()
        .flatMap(point => [point.water_temp, point.return_temp]));
    if (!values.length) return [0,80];
    return [Math.max(0, Math.floor(Math.min(...values) / 5) * 5 - 5),
        Math.min(100, Math.ceil(Math.max(...values) / 5) * 5 + 5)];
}

function drawBoilerWaterPhasePlot(data, setting) {
    const curves = boilerWaterPhaseCurves(data, setting);
    const range = boilerWaterPhaseRange(curves);
    const points = curves.flatMap(curve => curve.segments.flat());
    const average = !setting.phaseMode || setting.phaseMode === 'average';
    let emptyMessage = points.length ? '' : 'Az adott napra nincs érvényes fázispont.';
    if (average && boilerEnabledCycles(data.heating_state) === null) emptyMessage = 'Az adott napra nincs kapcsolási adat.';
    else if (average && !boilerEnabledCycles(data.heating_state).length) emptyMessage = 'Nincs engedélyezett fűtési kör.';
    const area = drawPlot([], {parentId: 'graph', margins: {top: .26, right: .04, bottom: .18, left: .12},
        domain: {bottom: range, left: range, niceLeft: false},
        dataKeys: {bottom: 'return_temp', left: 'water_temp'},
        axesLabel: {bottom: 'visszatérő (°C)', left: 'előremenő (°C)'},
        tickVals: {bottom: d3.range(range[0], range[1] + 1, 5), left: d3.range(range[0], range[1] + 1, 5)},
        smoothing: {bottom: 0, left: 0}, segment: {do: false},
        plotStyle: {joined: false, startCap: false, endCap: false},
        curveEndText: {show: false}, plotLabel: '', plotLabelTabs: false, emptyMessage,
        plotDateNavigation: {day: setting.day, onDayChange: navigateMainPlotDay}});
    const scale = isMobile ? 1.8 : 1;
    drawBoilerKPITabs(area, setting, -18);
    drawPlotTitleSelector(area.plotElement.append('g').attr('transform', `translate(0,${-7 * scale})`),
        area.plotDims, boilerWaterPhaseTabs(setting), 7 * scale);
    const x = d3.scaleLinear().domain(range).range([0,area.plotDims.w]);
    const y = d3.scaleLinear().domain(range).range([area.plotDims.h,0]);
    area.plotElement.append('line').attr('class', 'boiler-water-equal-temperature')
        .attr('x1', x(range[0])).attr('y1', y(range[0])).attr('x2', x(range[1])).attr('y2', y(range[1]))
        .attr('stroke', '#ccc').attr('stroke-width', .35).attr('stroke-dasharray', '2,2').attr('pointer-events', 'none');
    curves.forEach(curve => {
        if (!curve.segments.length) return;
        const group = area.plotElement.append('g').attr('class', 'boiler-water-phase-curve').attr('data-cycle', curve.cycle || 'mean');
        for (const point of curve.scatter) group.append('circle').attr('class', 'boiler-water-phase-observation')
            .attr('cx', x(point.return_temp)).attr('cy', y(point.water_temp)).attr('r', .65 * scale)
            .attr('fill', curve.color).attr('fill-opacity', .2).attr('pointer-events', 'none');
        const line = d3.line().x(point => x(point.return_temp)).y(point => y(point.water_temp))
            .curve(d3.curveCatmullRom.alpha(.5));
        const smoothed = curve.segments.map(segment => boilerWaterPhaseSmooth(segment));
        const paths = [];
        for (const segment of smoothed) {
            const path = group.append('path').attr('class', 'boiler-water-phase-trajectory')
                .attr('d', line(segment)).attr('fill', 'none').attr('stroke', curve.color)
                .attr('stroke-width', 1 * scale).attr('stroke-linecap', 'round').attr('stroke-linejoin', 'round');
            paths.push(path);
            const hit = group.append('path').attr('d', line(segment)).attr('fill', 'none')
                .attr('stroke', 'transparent').attr('stroke-width', 5 * scale).attr('pointer-events', 'stroke');
            bindPlotCurveTooltip(hit, dashboardText(curve.label), 6, false);
        }
        const last = smoothed.at(-1).at(-1);
        const first = smoothed[0][0];
        const timeLabel = point => {
            const minute = Math.round(point.h_of_day_frac * 60);
            return String(Math.floor(minute / 60)).padStart(2, '0') + ':' + String(minute % 60).padStart(2, '0');
        };
        for (const [point, radius, fill, kind] of [[first, 1.5, 'black', 'start'], [last, 3, curve.color, 'end']]) {
            const marker = group.append('circle').attr('class', 'boiler-water-phase-' + kind)
                .attr('cx', x(point.return_temp)).attr('cy', y(point.water_temp)).attr('r', radius * scale).attr('fill', fill);
            bindPlotCurveTooltip(marker, dashboardText(curve.label) + ' · ' + timeLabel(point)
                + '\n' + dashboardText('előremenő') + ': ' + Number(point.water_temp.toFixed(1)) + '°C'
                + '\n' + dashboardText('visszatérő') + ': ' + Number(point.return_temp.toFixed(1)) + '°C', 6, false);
        }
        if (!average) group.on('mouseenter', () => {group.raise(); paths.forEach(path => path.attr('stroke-width', 1.4 * scale));})
            .on('mouseleave', () => paths.forEach(path => path.attr('stroke-width', 1 * scale)));
    });
    if (setting.phaseMode === 'all') {
        const legend = area.plotElement.append('text').attr('class', 'boiler-water-phase-legend')
            .attr('x', area.plotDims.w / 2).attr('y', -scale).style('text-anchor', 'middle')
            .style('font-family', dashboardFont).style('font-size', 5 * scale + 'px');
        BOILER_DEMAND_CYCLES.forEach((part, index) => legend.append('tspan').attr('fill', part.color)
            .text((index ? ' · ' : '') + dashboardText(part.label)));
    }
}
