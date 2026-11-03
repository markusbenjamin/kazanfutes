// Per-cycle demand is signed; the formatter clamps only the net boiler demand.
const BOILER_DEMAND_CYCLES = [
    {cycle: 1, label: '1-es kör', color: 'rgb(200,0,0)'},
    {cycle: 2, label: '2-es kör', color: 'rgb(230,130,0)'},
    {cycle: 3, label: '3-as kör', color: 'rgb(28,3,252)'},
    {cycle: 4, label: '4-es kör', color: 'rgb(0,130,0)'}
];

function boilerDemandStack(row, binned = false) {
    if (!Number.isFinite(row.demand_kw) || row.demand_kw < 0) return null;
    const values = BOILER_DEMAND_CYCLES.map(({cycle}) => row.cycle_demand_kw?.[cycle]);
    if (!values.every(Number.isFinite)) return null;
    if (!binned && Math.abs(Math.max(0, values.reduce((sum, value) => sum + value, 0)) - row.demand_kw) > .0001) return null;
    let positive = 0, negative = 0;
    const parts = values.map((value, index) => {
        const start = value >= 0 ? positive : negative;
        if (value >= 0) positive += value; else negative += value;
        return {...BOILER_DEMAND_CYCLES[index], value, start, end: start + value};
    });
    return {parts, positive, negative};
}

function boilerDemandBins(readings, end = 24) {
    const keys = BOILER_DEMAND_CYCLES.map(({cycle}) => 'cycle_' + cycle);
    const samples = readings.map(row => {
        const sample = {h_of_day_frac: row.h_of_day_frac, demand_kw: Number.isFinite(row.demand_kw) && row.demand_kw >= 0 ? row.demand_kw : null};
        const stack = boilerDemandStack(row);
        if (stack) stack.parts.forEach(part => {sample['cycle_' + part.cycle] = part.value;});
        return sample;
    });
    return powerPlotBins(samples, ['demand_kw', ...keys], end).map(row => {
        // Validate before averaging. Mean(clamped net) need not equal clamped mean(components).
        if (keys.every(key => Number.isFinite(row[key]) && Math.abs(row.coverage[key] - row.coverage.demand_kw) < 1e-9))
            row.cycle_demand_kw = Object.fromEntries(keys.map((key, index) => [index + 1, row[key]]));
        return row;
    });
}

function boilerDemandExtent(readings, end = 24) {
    let minimum = 0, maximum = 1;
    boilerDemandBins(readings, end).forEach(row => {
        if (!Number.isFinite(row.h_of_day_frac) || row.h_of_day_frac < 0 || row.h_of_day_frac > 24) return;
        if (!Number.isFinite(row.demand_kw) || row.demand_kw < 0) return;
        const stack = boilerDemandStack(row, true);
        minimum = Math.min(minimum, stack?.negative ?? 0);
        maximum = Math.max(maximum, stack?.positive ?? 0, row.demand_kw);
    });
    return [minimum, maximum];
}

function drawBoilerDemandBars(area, readings, metric, range, end = 24) {
    const x = d3.scaleLinear().domain([0,24]).range([0,area.plotDims.w]);
    const y = d3.scaleLinear().domain(range).nice().range([area.plotDims.h,0]);
    const sorted = boilerDemandBins(readings, end);
    const text = value => Number(value.toFixed(2)) + ' kW';
    let last;
    sorted.forEach(row => {
        if (!Number.isFinite(row.demand_kw) || row.demand_kw < 0) return;
        const gap = (row.bin_end - row.bin_start) * .05;
        const left = x(row.bin_start + gap), right = x(row.bin_end - gap);
        const time = powerBinTimeLabel(row);
        const stack = boilerDemandStack(row, true);
        const parts = stack?.parts || [{color:metric.color, value:row.demand_kw, start:0, end:row.demand_kw}];
        parts.forEach(part => {
            const bar = area.plotElement.append('rect').attr('class', 'boiler-demand-bar')
                .attr('data-cycle', part.cycle ?? '').attr('data-value', part.value).attr('data-hour', row.h_of_day_frac)
                .attr('x', left).attr('width', right - left).attr('y', Math.min(y(part.start), y(part.end)))
                .attr('height', Math.abs(y(part.start) - y(part.end))).attr('fill', part.color).attr('stroke', 'none');
            bindPlotCurveTooltip(bar, time + (part.label ? '\n' + dashboardText(part.label) + ': ' + text(part.value) : '')
                + '\n' + dashboardText('hőigény') + ': ' + text(row.demand_kw), 6, false);
        });
        if (stack) area.plotElement.append('line').attr('class', 'boiler-demand-net')
            .attr('x1', left).attr('x2', right).attr('y1', y(row.demand_kw)).attr('y2', y(row.demand_kw))
            .attr('stroke', 'black').attr('stroke-width', .35).attr('pointer-events', 'none');
        last = row;
    });
    if (last) area.plotElement.append('text').attr('class', 'logged-power-end-label')
        .attr('x', x(last.h_of_day_frac) + 3).attr('y', y(last.demand_kw) + 1.75)
        .style('font-family', dashboardFont).style('font-size', '6px').style('fill', 'black').text(text(last.demand_kw));
    const legend = area.plotElement.append('text').attr('class', 'boiler-demand-legend')
        .attr('x', area.plotDims.w / 2).attr('y', -1).style('text-anchor', 'middle')
        .style('font-family', dashboardFont).style('font-size', '5px');
    BOILER_DEMAND_CYCLES.forEach((part, index) => legend.append('tspan').attr('fill', part.color).text((index ? ' · ' : '') + dashboardText(part.label)));
}
