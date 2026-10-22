// Touch equivalents of the existing desktop modifier-click views.
let mobilePlotContext = null;

function mobilePlotViewsEnabled() {
    return isMobile || Boolean(window.matchMedia?.('(pointer: coarse)').matches);
}

function mobilePlotTarget(elementId) {
    const radiator = radiatorTargets.get(elementId);
    if (radiator) return {elementId, radiator, modes: ['alap', 'részletes']};
    const cycle = elementId.match(/^cycle([1-4])_infobox$/);
    let base = elementToMainGraphSettingMapping[elementId];
    if (elementId === 'general_infobox' || cycle) base = {...mainGraphDefaultSetting,
        roomNumsToPlot: cycle ? cyclesDataAndState[Number(cycle[1])].rooms : allMeasuredRooms,
        hoveredCycle: cycle ? Number(cycle[1]) : 0};
    if (!base) return null;
    const modes = ['alap'];
    if (['room_plot', 'cycle_water_temp', 'external_temp'].includes(base.title)) modes.push('részletes');
    if (base.title === 'room_plot' || elementId === 'boiler_body' || elementId === 'general_infobox' || cycle) modes.push('analitika');
    return modes.length > 1 ? {elementId, base, modes} : null;
}

function mobilePlotSetting(target, mode, day) {
    const {elementId, base, radiator} = target;
    if (radiator) return radiatorPlotSetting(radiator, mode === 'részletes', day);
    if (mode === 'alap') return {...base, day, types: base.types.slice(), conditionals: base.conditionals.slice()};
    if (mode === 'analitika') return elementId === 'boiler_body' ? createBoilerKPIPlotSetting(day)
        : createRoomControlPlotSetting(elementId, day);
    if (base.title === 'room_plot') return createRoomMetricPlotSetting({...base, day}, elementId);
    if (base.title === 'external_temp') return createWeatherMetricPlotSetting(day);
    if (base.title === 'cycle_water_temp') return createCycleHeatPlotSetting(base.cycleNum, elementId,
        cycleHeatSelections[base.cycleNum] || 'power', day, true);
    return null;
}

function openMobilePlotTarget(event, elementId) {
    if (!mobilePlotViewsEnabled() || event.ctrlKey || event.altKey || event.metaKey) return false;
    const target = mobilePlotTarget(elementId);
    if (!target) return false;
    event.preventDefault();
    mobilePlotContext = {...target, mode: 'alap'};
    mainGraphSetting = mobilePlotSetting(mobilePlotContext, 'alap', dayStamp());
    mainGraphContentLocked = true;
    drawMainGraph({[mainGraphSetting.day]: {}});
    drawMainGraph();
    return true;
}

function selectMobilePlotView(mode) {
    if (!mobilePlotContext || !mobilePlotContext.modes.includes(mode)) return;
    const setting = mobilePlotSetting(mobilePlotContext, mode, mainGraphSetting.day);
    if (!setting) return;
    mobilePlotContext = {...mobilePlotContext, mode};
    mainGraphSetting = setting;
    mainGraphContentLocked = true;
    drawMainGraph({[setting.day]: {}});
    drawMainGraph();
}

function clearMobilePlotContext() {
    mobilePlotContext = null;
}

function mobilePlotViewOptions() {
    return mobilePlotViewsEnabled() && mainGraphContentLocked && mobilePlotContext ? mobilePlotContext : null;
}

function drawMobilePlotViewSelector(container, dimensions, options) {
    const font = isMobile ? 10 : 7;
    const width = Math.min(dimensions.w / options.modes.length, font * 9);
    const start = (dimensions.w - width * options.modes.length) / 2;
    const selector = container.append('g').attr('class', 'mobile-plot-views').attr('role', 'tablist')
        .attr('aria-label', 'Grafikon nézete');
    options.modes.forEach((mode, index) => {
        const activate = event => {event.stopPropagation(); event.preventDefault(); selectMobilePlotView(mode);};
        const tab = selector.append('g').attr('role', 'tab').attr('tabindex', 0).attr('aria-label', mode)
            .attr('aria-selected', mode === options.mode ? 'true' : 'false').style('cursor', 'pointer')
            .on('mousedown', event => event.stopPropagation()).on('touchstart', event => event.stopPropagation())
            .on('click', activate).on('keydown', event => {if (event.key === 'Enter' || event.key === ' ') activate(event);});
        tab.append('rect').attr('x', start + index * width).attr('y', 0).attr('width', width)
            .attr('height', dimensions.h).attr('fill', 'transparent').style('pointer-events', 'all');
        tab.append('text').attr('x', start + (index + .5) * width).attr('y', dimensions.h / 2)
            .style('dominant-baseline', 'middle').style('text-anchor', 'middle').style('font-family', dashboardFont)
            .style('font-size', font + 'px').style('fill', 'black')
            .style('text-decoration', mode === options.mode ? 'underline' : 'none').text(mode);
    });
}
