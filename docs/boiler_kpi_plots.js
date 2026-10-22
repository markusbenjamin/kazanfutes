// MVM Hálózat's typical lower heating value, retrieved 2026-10-21.
// https://www.mvmhalozat.hu/gaz/oldalak/2376
const BOILER_GAS_HEATING_VALUE_MJ_M3 = 34;
const BOILER_KPI_TYPES = ['gas_usage', ...[1, 2, 3, 4].map(cycle => 'cycle_' + cycle + '_heat_delivery')];

function openBoilerKPIPlot(event) {
    event.preventDefault();
    mainGraphSetting = {title: 'boiler_kpi', day: dayStamp(), windowDays: 7, types: BOILER_KPI_TYPES, conditionals: []};
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
    roomControlText(area.plotElement, 'kazán — hőhasznosítás', area.plotDims.w / 2, -25, 7);
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
