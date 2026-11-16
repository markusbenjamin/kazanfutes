// MVM Hálózat's typical lower heating value, retrieved 2026-10-21.
// https://www.mvmhalozat.hu/gaz/oldalak/2376
const BOILER_GAS_HEATING_VALUE_MJ_M3 = 34;
const BOILER_KPI_TYPES = ['gas_usage', ...[1, 2, 3, 4].map(cycle => 'cycle_' + cycle + '_heat_delivery')];
const BOILER_KPI_WINDOW_DAYS = 30;
let boilerKPISelection = 'ratio';
let boilerWaterPhaseSelection = 'average';

function createBoilerKPIPlotSetting(day = dayStamp(), metric = boilerKPISelection) {
    if (!['ratio', 'phase'].includes(metric)) metric = 'ratio';
    return {title: 'boiler_kpi', day, metric, phaseMode: boilerWaterPhaseSelection, windowDays: BOILER_KPI_WINDOW_DAYS,
        types: metric === 'phase' ? ['heating_state', 'pumps_power',
            ...[1,2,3,4].map(cycle => 'cycle_' + cycle + '_water_temps')]
            : BOILER_KPI_TYPES, conditionals: []};
}

function selectBoilerKPIView(metric) {
    if (mainGraphSetting.title !== 'boiler_kpi' || !['ratio', 'phase'].includes(metric)) return;
    boilerKPISelection = metric;
    mainGraphSetting = createBoilerKPIPlotSetting(mainGraphSetting.day, metric);
    mainGraphContentLocked = true;
    drawMainGraph({});
    drawMainGraph();
}

function drawBoilerKPITabs(area, setting, y) {
    const scale = isMobile ? mobileViewScaler : 1;
    area.plotElement.append('text').attr('class', 'boiler-analytics-title')
        .attr('x', area.plotDims.w / 2).attr('y', (y - 9.8) * scale)
        .style('text-anchor', 'middle').style('font-family', dashboardFont).style('font-size', 7 * scale + 'px')
        .text(dashboardText('kazán analitika'));
    drawPlotTitleSelector(area.plotElement.append('g').attr('transform', `translate(0,${y * scale})`), area.plotDims,
        {prefix: '', selected: setting.metric || 'ratio', choices: [
            {key: 'ratio', label: 'hatásfok', color: 'black'},
            {key: 'phase', label: 'előremenő / visszatérő fázissík', color: 'black'}
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

function collectBoilerKPIWindow(days, setting, callback) {
    // Bound concurrent daily loads: thirty days should not require a long
    // serial queue, or launch all 150 files at once. Reuse the existing cache.
    const collected = {};
    let cursor = 0, remaining = days.length;
    if (!remaining) {callback(collected); return;}
    const next = () => {
        if (mainGraphSetting !== setting || cursor >= days.length) return;
        const day = days[cursor++];
        collectDataFromGitHub(BOILER_KPI_TYPES.map(type => ({day,type})), loaded => {
            if (mainGraphSetting !== setting) return;
            Object.assign(collected,loaded);
            remaining--;
            if (!remaining) callback(collected);
            else next();
        });
    };
    for (let worker = 0; worker < Math.min(4,days.length); worker++) next();
}

function drawBoilerKPIView(data = null) {
    const setting = mainGraphSetting;
    if (typeof cacheDashboardPlotLanguage === 'function') cacheDashboardPlotLanguage(data, setting);
    if (setting.metric === 'phase') {
        if (data === null) {
            collectDataFromGitHub(setting.types.map(type => ({day: setting.day, type})),
                loaded => {if (mainGraphSetting === setting) drawBoilerKPIView(loaded);});
        } else {
            clearMainGraphs();
            drawBoilerWaterPhasePlot(data[setting.day] || {}, setting);
        }
        return;
    }
    const days = roomControlDays(setting.day, setting.windowDays).slice(1);
    if (data === null) {
        collectBoilerKPIWindow(days, setting,
            loaded => {if (mainGraphSetting === setting) drawBoilerKPIView(loaded);});
        return;
    }
    clearMainGraphs();
    const rows = days.map((day, index) => ({day, day_index: index, ...boilerDailyKPI(data[day])}));
    const last = rows.at(-1);
    const max = Math.max(100, ...rows.map(row => Number.isFinite(row.ratio_pct) ? row.ratio_pct : 0));
    const top = Math.ceil(max * 1.05 / 10) * 10;
    const common = {parentId: 'graph', margins: {top: .29, right: .04, bottom: .17, left: .12},
        domain: {bottom: [-.5, days.length - .5], left: [0, top], niceLeft: false}, dataKeys: {bottom: 'day_index', left: 'ratio_pct'},
        axesLabel: {bottom: '', left: 'hatásfok (%)'},
        tickVals: {bottom: days.map((_, index) => index).filter(index => index % 5 === 0 || index === days.length - 1)},
        tickFormat: {bottom: index => days[index]?.slice(5).replace('-', '.') || ''},
        smoothing: {bottom: 0, left: 0}, segment: {do: false}, plotLabel: '', curveEndText: {show: false}};
    const area = drawPlot([], {...common, plotDateNavigation: {day: setting.day, onDayChange: navigateMainPlotDay}});
    drawBoilerKPITabs(area, setting, -22.5);
    roomControlText(area.plotElement, 'nap: ' + roomControlNumber(last.ratio_pct) + '%  |  ' + days.length + ' nap: ' + roomControlNumber(aggregateBoilerKPIs(rows)) + '%', area.plotDims.w / 2, -16, 6);
    roomControlText(area.plotElement, 'leadott: ' + roomControlNumber(last.heat_kwh, 0) + ' kWh  ·  gázenergia: ' + roomControlNumber(last.gas_kwh, 0) + ' kWh', area.plotDims.w / 2, -7, 5);
    const valid = rows.filter(row => Number.isFinite(row.ratio_pct) && row.ratio_pct >= 0);
    const x = d3.scaleLinear().domain(common.domain.bottom).range([0,area.plotDims.w]);
    const y = d3.scaleLinear().domain(common.domain.left).range([area.plotDims.h,0]);
    valid.forEach(row => {
        const bar = area.plotElement.append('rect').attr('class','boiler-efficiency-bar')
            .attr('data-day',row.day).attr('data-ratio-pct',row.ratio_pct)
            .attr('x',x(row.day_index - .4)).attr('width',x(row.day_index + .4) - x(row.day_index - .4))
            .attr('y',y(row.ratio_pct)).attr('height',y(0) - y(row.ratio_pct)).attr('fill','black').attr('stroke','none');
        bindPlotCurveTooltip(bar,row.day + '\nhatásfok: ' + roomControlNumber(row.ratio_pct) + '%'
            + '\nleadott: ' + roomControlNumber(row.heat_kwh) + ' kWh\ngázenergia: ' + roomControlNumber(row.gas_kwh) + ' kWh',6,false);
    });
    if (!valid.length) setPlotEmptyMessage(roomControlText(area.plotElement, '', area.plotDims.w / 2, area.plotDims.h / 2), 'Nincs elegendő energiaadat.');
}
