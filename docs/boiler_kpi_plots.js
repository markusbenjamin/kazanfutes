// MVM Hálózat's typical lower heating value, retrieved 2026-10-21.
// https://www.mvmhalozat.hu/gaz/oldalak/2376
const BOILER_GAS_HEATING_VALUE_MJ_M3 = 34;
const BOILER_KPI_TYPES = ['gas_usage', ...[1, 2, 3, 4].map(cycle => 'cycle_' + cycle + '_heat_delivery')];
let boilerKPISelection = 'ratio';

function createBoilerKPIPlotSetting(day = dayStamp()) {
    return {title: 'boiler_kpi', day, metric: boilerKPISelection, windowDays: 7, types: BOILER_KPI_TYPES, conditionals: []};
}

function selectBoilerKPIView(metric) {
    if (mainGraphSetting.title !== 'boiler_kpi' || !['ratio', 'scatter'].includes(metric)) return;
    boilerKPISelection = metric;
    mainGraphSetting = {...mainGraphSetting, metric};
    mainGraphContentLocked = true;
    drawMainGraph({});
    drawMainGraph();
}

function drawBoilerKPITabs(area, setting, y) {
    const scale = isMobile ? mobileViewScaler : 1;
    drawPlotTitleSelector(area.plotElement.append('g').attr('transform', `translate(0,${y * scale})`), area.plotDims,
        {prefix: 'kazán — ', selected: setting.metric || 'ratio', choices: [
            {key: 'ratio', label: 'hőhasznosítás', color: 'black'},
            {key: 'scatter', label: 'napi pontok', color: 'black'}
        ], onSelect: selectBoilerKPIView}, 7 * scale);
}

function openBoilerKPIPlot(event) {
    event.preventDefault();
    mainGraphSetting = createBoilerKPIPlotSetting();
    mainGraphContentLocked = true;
    drawMainGraph({});
    drawMainGraph();
    return true;
}

function boilerDailyKPI(data) {
    const cycles = BOILER_KPI_TYPES.slice(1).map(type => (data?.[type] || [])
        .filter(row => Number.isFinite(row.energy_kwh) && row.energy_kwh >= 0 && Number.isFinite(row.h_of_day_frac))
        .slice().sort((a, b) => a.h_of_day_frac - b.h_of_day_frac));
    if (cycles.some(rows => !rows.length)) return null;
    const cutoff = Math.min(...cycles.map(rows => rows.at(-1).h_of_day_frac));
    const readings = cycles.map(rows => rows.filter(row => row.h_of_day_frac <= cutoff).at(-1));
    if (readings.some(row => !row || cutoff - row.h_of_day_frac > 3 / 60)) return null;
    const gas = (data?.gas_usage || []).filter(row => Number.isFinite(row.burnt_volume) && row.burnt_volume >= 0 &&
        Number.isFinite(row.h_of_day_frac) && row.h_of_day_frac <= cutoff)
        .slice().sort((a, b) => a.h_of_day_frac - b.h_of_day_frac).at(-1);
    if (!gas) return null;
    const heat_kwh = readings.reduce((sum, row) => sum + row.energy_kwh, 0);
    const gas_m3 = gas.burnt_volume;
    const gas_kwh = gas_m3 * BOILER_GAS_HEATING_VALUE_MJ_M3 / 3.6;
    return {heat_kwh, gas_m3, gas_kwh, ratio_pct: gas_kwh > 0 ? 100 * heat_kwh / gas_kwh : null};
}

function aggregateBoilerKPIs(rows) {
    const valid = rows.filter(row => row && Number.isFinite(row.heat_kwh) && Number.isFinite(row.gas_kwh) && row.gas_kwh > 0);
    const heat = valid.reduce((sum, row) => sum + row.heat_kwh, 0);
    const gas = valid.reduce((sum, row) => sum + row.gas_kwh, 0);
    return gas > 0 ? 100 * heat / gas : null;
}

function drawBoilerKPIView(data = null) {
    const setting = mainGraphSetting;
    const days = roomControlDays(setting.day, setting.windowDays).slice(1);
    if (data === null) {
        collectDataFromGitHub(days.flatMap(day => BOILER_KPI_TYPES.map(type => ({day, type}))),
            loaded => {if (mainGraphSetting === setting) drawBoilerKPIView(loaded);});
        return;
    }
    clearMainGraphs();
    const rows = days.map((day, index) => ({day, day_index: index, ...boilerDailyKPI(data[day])}));
    if (setting.metric === 'scatter') {
        drawBoilerDailyScatter(rows, setting);
        return;
    }
    const last = rows.at(-1);
    const max = Math.max(100, ...rows.map(row => Number.isFinite(row.ratio_pct) ? row.ratio_pct : 0));
    const top = Math.ceil(max * 1.05 / 10) * 10;
    const common = {parentId: 'graph', margins: {top: .24, right: .04, bottom: .17, left: .12},
        domain: {bottom: [0, days.length - 1], left: [0, top]}, dataKeys: {bottom: 'day_index', left: 'ratio_pct'},
        axesLabel: {bottom: '', left: 'leadott hő / gázenergia (%)'},
        tickVals: {bottom: days.map((_, index) => index)},
        tickFormat: {bottom: index => days[index]?.slice(5).replace('-', '.') || ''},
        smoothing: {bottom: 0, left: 0}, segment: {do: false}, plotLabel: '', curveEndText: {show: false}};
    const area = drawPlot([], {...common, plotDateNavigation: {day: setting.day, onDayChange: navigateMainPlotDay}});
    drawBoilerKPITabs(area, setting, -22.5);
    roomControlText(area.plotElement, 'nap: ' + roomControlNumber(last.ratio_pct) + '%  |  7 nap: ' + roomControlNumber(aggregateBoilerKPIs(rows)) + '%', area.plotDims.w / 2, -16, 6);
    roomControlText(area.plotElement, 'leadott: ' + roomControlNumber(last.heat_kwh, 0) + ' kWh  ·  gáz: ' + roomControlNumber(last.gas_kwh, 0) + ' kWh', area.plotDims.w / 2, -7, 5);
    let segment = [];
    const segments = [];
    rows.forEach(row => {
        if (Number.isFinite(row.ratio_pct)) segment.push(row);
        else {if (segment.length) segments.push(segment); segment = [];}
    });
    if (segment.length) segments.push(segment);
    segments.forEach(points => drawPlot(points, {...common, background: {show: false}, showLockLabel: false,
        axes: {left: false, bottom: false}, plotStyle: {joined: true, linear: true, col: 'black', thickness: '1.5', startCap: true, endCap: true},
        curveTooltip: 'leadott hő / gázenergia'}));
    if (!segments.length) roomControlText(area.plotElement, 'Nincs elegendő energiaadat.', area.plotDims.w / 2, area.plotDims.h / 2);
}

function drawBoilerDailyScatter(rows, setting) {
    const points = rows.filter(row => Number.isFinite(row.heat_kwh) && row.heat_kwh >= 0
        && Number.isFinite(row.gas_kwh) && row.gas_kwh > 0 && Number.isFinite(row.ratio_pct));
    const xTop = Math.max(10, Math.ceil(Math.max(0, ...points.map(row => row.heat_kwh)) * 1.1 / 10) * 10);
    const yTop = Math.ceil(Math.max(100, ...points.map(row => row.ratio_pct)) * 1.05 / 10) * 10;
    const area = drawPlot([], {parentId: 'graph', margins: {top: .14, right: .05, bottom: .18, left: .14},
        domain: {bottom: [0,xTop], left: [0,yTop], niceLeft: false},
        dataKeys: {bottom: 'heat_kwh', left: 'ratio_pct'}, plotLabel: '', curveEndText: {show: false},
        axesLabel: {bottom: 'napi leadott hő (kWh)', left: 'leadott hő / gázenergia (%)'},
        plotDateNavigation: {day: setting.day, onDayChange: navigateMainPlotDay},
        emptyMessage: points.length ? '' : 'Nincs elegendő energiaadat.'});
    drawBoilerKPITabs(area, setting, -5);
    const scale = isMobile ? mobileViewScaler : 1;
    const x = d3.scaleLinear().domain([0,xTop]).range([0,area.plotDims.w]);
    const y = d3.scaleLinear().domain([0,yTop]).range([area.plotDims.h,0]);
    area.plotElement.append('line').attr('class','boiler-scatter-reference')
        .attr('x1',0).attr('x2',area.plotDims.w).attr('y1',y(100)).attr('y2',y(100))
        .attr('stroke','#bbb').attr('stroke-width',.35 * scale).attr('stroke-dasharray','2,2')
        .attr('pointer-events','none');
    // The selected day is drawn last, so identical observations do not hide it.
    points.slice().sort((a,b) => Number(a.day === setting.day) - Number(b.day === setting.day)).forEach(row => {
        const selected = row.day === setting.day;
        const group = area.plotElement.append('g').attr('class','boiler-scatter-point')
            .attr('data-day',row.day).attr('data-heat-kwh',row.heat_kwh).attr('data-ratio-pct',row.ratio_pct);
        group.append('circle').attr('cx',x(row.heat_kwh)).attr('cy',y(row.ratio_pct))
            .attr('r',(selected ? 2.6 : 1.8) * scale).attr('fill',selected ? 'red' : 'black')
            .attr('stroke','white').attr('stroke-width',.45 * scale);
        const hit = group.append('circle').attr('cx',x(row.heat_kwh)).attr('cy',y(row.ratio_pct))
            .attr('r',4 * scale).attr('fill','transparent');
        bindPlotCurveTooltip(hit, row.day + '\nleadott: ' + roomControlNumber(row.heat_kwh,1)
            + ' kWh\ngázenergia: ' + roomControlNumber(row.gas_kwh,1) + ' kWh\n'
            + roomControlNumber(row.ratio_pct,1) + '%', 6, false);
    });
}
