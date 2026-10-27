// Physical unit ownership comes from system/radiator_mapping.json.
// Probe subsets and provisional TRV links belong exclusively to the SVG.
let radiatorUnitMapping = null;
let radiatorSystem = null;
let radiatorHistory = {probes: [], valves: []};
const radiatorTargets = new Map();
const radiatorMetricSelections = {};
const RADIATOR_SOURCE_GAP_HOURS = 5 / 60;

function radiatorMean(values) {
    const known = values.filter(Number.isFinite);
    return known.length ? known.reduce((sum, value) => sum + value, 0) / known.length : null;
}

function radiatorFresh(timestamp, seconds = 1200, now = new Date()) {
    if (typeof timestamp !== 'string') return false;
    const age = (now - dateFromTimestamp(timestamp)) / 1000;
    return Number.isFinite(age) && age >= -30 && age <= seconds;
}

function heatingTemperatureColor(value) {
    return Number.isFinite(value)
        ? d3.interpolateRgb('rgb(0,0,200)', 'rgb(255,0,0)')(Math.max(0, Math.min(1, (value - 22) / 28)))
        : 'rgb(255,0,0)';
}

function cycleSupplyTemperature(system, cycle) {
    const meters = system?.state?.heatmeters;
    return radiatorFresh(meters?.last_updated, 600) && Number.isFinite(meters?.[cycle]?.temp) ? meters[cycle].temp : null;
}

function cyclePipingColor(system, cycle) {
    return system?.state?.pump_states?.[cycle] === 1 ? heatingTemperatureColor(cycleSupplyTemperature(system, cycle)) : 'rgb(0,0,200)';
}

function radiatorElementColor(target, values, system) {
    if (Number.isFinite(values.temperature)) return heatingTemperatureColor(values.temperature);
    if (Number.isFinite(values.valve)) {
        return d3.interpolateRgb('rgb(0,0,200)', 'rgb(255,0,0)')(Math.max(0, Math.min(1, values.valve / 100)));
    }
    return cyclePipingColor(system, target.cycle);
}

function radiatorTargetFromElement(element, mapping) {
    const location = element.getAttribute('data-location-id') || element.id.replace(/_radiator_\d+$/, '');
    const unit = mapping.rooms.find(room => room.location_id === location);
    const unitProbes = (unit?.probes || []).map(probe => probe.device + '/' + probe.probe);
    const parse = key => {
        const raw = element.getAttribute(key);
        if (raw === null) return null;
        const values = JSON.parse(raw);
        if (!Array.isArray(values) || !values.every(value => typeof value === 'string')) throw new Error('Invalid radiator SVG attribute: ' + key);
        return [...new Set(values)];
    };
    const probes = parse('data-probes') ?? unitProbes;
    if (probes.some(probe => !unitProbes.includes(probe))) throw new Error('Radiator probe outside mapped unit: ' + element.id);
    const cycleGroup = element.closest('[id^="cycle"][id$="_radiators"]');
    const cycle = Number(cycleGroup?.id.match(/^cycle([1-4])_radiators$/)?.[1]) || null;
    return {id: element.id, location, label: element.getAttribute('data-display-label') || unit?.location_label || location,
        probes, trvs: parse('data-trvs') || [], cycle};
}

function radiatorLiveValues(target, now = new Date()) {
    const state = radiatorSystem?.state || {};
    const snapshot = state.radiator_probes;
    const fallbackProbeRow = radiatorHistory.probes.at(-1);
    const probeValues = target.probes.map(source => {
        const slash = source.indexOf('/'), device = source.slice(0, slash), probe = source.slice(slash + 1);
        if (snapshot) return radiatorFresh(snapshot.timestamp, 300, now) ? snapshot.devices?.[device]?.[probe] ?? null : null;
        return radiatorFresh(fallbackProbeRow?.timestamp, 1200, now) ? fallbackProbeRow.probes?.[source] ?? null : null;
    });
    const valveSnapshot = state.radiator_valves;
    const fallbackValveRow = radiatorHistory.valves.at(-1);
    const valveValues = target.trvs.map(id => {
        if (valveSnapshot) return radiatorFresh(valveSnapshot.timestamp, 600, now) ? valveSnapshot.valves?.[id] ?? null : null;
        if (radiatorFresh(fallbackValveRow?.timestamp, 1200, now)) return fallbackValveRow.valves?.[id] ?? null;
        // Existing Firebase state retains individual positions in setup order; do not use a room mean here.
        if (!radiatorFresh(state.last_updated, 180, now)) return null;
        for (const [room, info] of Object.entries(radiatorSystem?.setup?.rooms || {})) {
            if (typeof info.thermostats !== 'string') continue;
            const index = info.thermostats.split(';').indexOf(id);
            if (index >= 0) return state.valve_states?.[room]?.[index] ?? null;
        }
        return null;
    });
    return {temperature: radiatorMean(probeValues), valve: radiatorMean(valveValues)};
}

function radiatorHasData(target) {
    const live = radiatorLiveValues(target);
    return live.temperature !== null || live.valve !== null ||
        radiatorHistory.probes.some(row => target.probes.some(source => Number.isFinite(row.probes?.[source]))) ||
        radiatorHistory.valves.some(row => target.trvs.some(id => Number.isFinite(row.valves?.[id])));
}

function radiatorTooltipText(values) {
    return [Number.isFinite(values.temperature) ? Number(values.temperature.toFixed(1)) + ' °C' : '',
        Number.isFinite(values.valve) ? Math.round(values.valve) + '%' : ''].filter(Boolean).join(' · ');
}

function radiatorPlotSetting(target, detailed = false, day = dayStamp(), metric = null) {
    const selected = metric || radiatorMetricSelections[target.id] || (target.probes.length ? 'average' : 'valves');
    return {title: 'radiator', sourceElementId: target.id, day, detailed,
        metric: detailed ? selected : target.probes.length ? 'average' : 'valves',
        types: ['radiator_temps', 'radiator_valves'], conditionals: []};
}

function selectRadiatorMetric(metric) {
    if (mainGraphSetting.title !== 'radiator') return;
    const target = radiatorTargets.get(mainGraphSetting.sourceElementId);
    if (!target || !['average', 'probes', 'valves'].includes(metric)) return;
    radiatorMetricSelections[target.id] = metric;
    mainGraphSetting = radiatorPlotSetting(target, true, mainGraphSetting.day, metric);
    mainGraphContentLocked = true;
    drawMainGraph({[mainGraphSetting.day]: {}});
    drawMainGraph();
}

function refreshRadiatorElements() {
    radiatorTargets.forEach(target => {
        const values = radiatorLiveValues(target);
        const color = radiatorElementColor(target, values, radiatorSystem);
        const node = d3.select('#' + target.id);
        node.style('fill', color).style('fill-opacity', 1).style('stroke-opacity', 0);
        node.selectAll('*').style('fill', color).style('fill-opacity', 1).style('stroke-opacity', 0);
        const active = radiatorHasData(target);
        node.style('pointer-events', active ? 'all' : 'none').style('cursor', active ? 'pointer' : null);
        node.attr('data-radiator-active', active ? 'true' : 'false');
    });
}

function updateRadiatorLiveState(system) {
    radiatorSystem = system;
    refreshRadiatorElements();
}

async function initializeRadiators() {
    const local = ['localhost', '127.0.0.1'].includes(window.location.hostname);
    const url = local ? '/radiator-mapping.json' : 'https://raw.githubusercontent.com/markusbenjamin/kazanfutes/main/system/radiator_mapping.json';
    try {
        radiatorUnitMapping = await fetchJSONEndpoint(url + '?updated=' + Date.now());
        document.querySelectorAll('[id*="_radiator_"]').forEach(element => {
            if (!/_radiator_\d+$/.test(element.id)) return;
            try {
                const target = radiatorTargetFromElement(element, radiatorUnitMapping);
                radiatorTargets.set(target.id, target);
                const node = d3.select(element).attr('data-radiator-target', 'true');
                const showTooltip = event => {
                    const text = radiatorTooltipText(radiatorLiveValues(target));
                    d3.select('#tooltip').interrupt().attr('data-curve-tooltip', null)
                        .style('font-size', null).style('white-space', null).text(text)
                        .style('left', event.pageX + 10 + 'px').style('top', event.pageY + 12 + 'px')
                        .style('visibility', text ? 'visible' : 'hidden');
                };
                node.on('mouseover.radiator', event => {
                    event.stopPropagation();
                    if (!radiatorHasData(target)) return;
                    showTooltip(event);
                    if (!mainGraphContentLocked) {
                        mainGraphSetting = radiatorPlotSetting(target);
                        drawMainGraph();
                    }
                }).on('mousemove.radiator', showTooltip).on('mouseout.radiator', event => {
                    if (element.contains(event.relatedTarget)) return;
                    d3.select('#tooltip').style('visibility', 'hidden');
                    if (!mainGraphContentLocked) {mainGraphSetting = mainGraphDefaultSetting; drawMainGraph();}
                }).on('mousedown.radiator', event => event.stopPropagation()).on('click.radiator', event => {
                    event.stopPropagation();
                    if (!radiatorHasData(target)) return;
                    if (openMobilePlotTarget(event, target.id)) return;
                    if (event.ctrlKey) event.preventDefault();
                    mainGraphSetting = radiatorPlotSetting(target, event.ctrlKey);
                    mainGraphContentLocked = true;
                    drawMainGraph();
                });
            } catch (error) { console.error(error); }
        });
        refreshRadiatorElements();
        if (mainGraphSetting.title === 'room_metrics' && mainGraphSetting.metric === 'radiators') drawMainGraph();
        const load = () => collectDataFromGitHub(['radiator_temps', 'radiator_valves'].map(type => ({day: dayStamp(), type})), data => {
            radiatorHistory = {probes: data[dayStamp()]?.radiator_temps || [], valves: data[dayStamp()]?.radiator_valves || []};
            refreshRadiatorElements();
        });
        load(); setInterval(load, 5 * 60 * 1000);
    } catch (error) { console.error('Could not initialize radiator mapping:', error); }
}

function radiatorSeries(rows, field, sources) {
    // Hold each probe independently through brief dropouts, never change the average's membership.
    const sorted = rows.filter(row => Number.isFinite(row.h_of_day_frac)).slice().sort((a,b) => a.h_of_day_frac - b.h_of_day_frac);
    if (!sorted.length) return [];
    const start = sorted[0].h_of_day_frac, end = sorted.at(-1).h_of_day_frac;
    const times = [...new Set([start, end, ...Array.from({length: 1441}, (_, i) => i / 60).filter(time => time >= start && time <= end),
        ...sorted.map(row => row.h_of_day_frac)])].sort((a,b) => a-b);
    let index = -1;
    const latest = new Map();
    return times.map(time => {
        while (index + 1 < sorted.length && sorted[index + 1].h_of_day_frac <= time + 1e-10) {
            const row = sorted[++index];
            sources.forEach(source => {
                const value = row[field]?.[source];
                if (Number.isFinite(value)) latest.set(source, {value, time: row.h_of_day_frac});
                else if (field !== 'probes') latest.delete(source);
            });
        }
        const readings = sources.map(source => {
            const sample = latest.get(source);
            return sample && time - sample.time <= RADIATOR_SOURCE_GAP_HOURS + 1e-10 ? sample.value : null;
        });
        const value = readings.length && readings.every(Number.isFinite) ? radiatorMean(readings) : null;
        return {h_of_day_frac: time, value};
    });
}

function roomRadiatorSources(roomNumber) {
    return [...new Set((radiatorUnitMapping?.rooms || [])
        .filter(unit => unit.legacy_room_numbers?.includes(Number(roomNumber)))
        .flatMap(unit => unit.probes.map(probe => probe.device + '/' + probe.probe)))];
}

function drawRoomRadiatorPlot(data, setting) {
    const target = {label: roomsDataAndState[setting.roomNumToPlot].name,
        probes: roomRadiatorSources(setting.roomNumToPlot), trvs: []};
    const emptyMessage = !radiatorUnitMapping ? 'Adatok betöltése.' : target.probes.length
        ? 'Az adott napra nincs adat.' : 'A szobához nincs radiátor-hőmérő rendelve.';
    drawRadiatorPlot(data, {...setting, metric: 'probes', detailed: true}, target, roomMetricPlotTabs(setting), emptyMessage);
}

function drawRadiatorPlot(data, setting, target = radiatorTargets.get(setting.sourceElementId), tabs = null,
    emptyMessage = 'Az adott napra nincs adat.') {
    if (!target) return;
    const metric = setting.metric;
    const colors = ['rgb(200,0,0)', 'rgb(0,40,150)', 'rgb(0,120,0)', 'rgb(190,155,0)'];
    const curves = metric === 'valves' ? target.trvs.map((id, index) => ({label: 'TRV ' + id, color: index ? colors[index % colors.length] : 'black',
        rows: radiatorSeries(data.radiator_valves || [], 'valves', [id])})) : metric === 'probes'
        ? target.probes.map((source, index) => ({label: source, color: colors[index % colors.length],
            rows: radiatorSeries(data.radiator_temps || [], 'probes', [source])}))
        : [{label: 'radiátor hőmérséklet', color: colors[0], rows: radiatorSeries(data.radiator_temps || [], 'probes', target.probes)}];
    curves.forEach(curve => {curve.segments = splitRoomMetricReadings(curve.rows, 'value', RADIATOR_SOURCE_GAP_HOURS);});
    const values = curves.flatMap(curve => curve.segments.flat().map(row => row.value));
    const range = metric === 'valves' ? [0, 100] : values.length ? [Math.floor(Math.min(...values)) - 2, Math.ceil(Math.max(...values)) + 2] : [15, 75];
    const common = {parentId:'graph', margins:{top:.1,right:.03,bottom:.15,left:.1}, domain:{bottom:[0,24],left:range},
        dataKeys:{bottom:'h_of_day_frac',left:'value'}, axesLabel:{bottom:'óra',left:metric === 'valves' ? '%' : '°C'},
        smoothing:{bottom:0,left:0}, plotStyle:{joined:true,thickness:metric === 'valves' ? '.75' : '2',monotone:metric !== 'valves',stepAfter:metric === 'valves',startCap:false,endCap:false},
        segment:{do:false}, curveEndText:{show:false}, plotLabel:setting.detailed ? '' : target.label + ' — radiátor ' + (metric === 'valves' ? 'nyitás' : 'hőmérséklet')};
    const choices = [];
    if (target.probes.length) choices.push({key:'average',label:'átlag hőm.',color:colors[0]},{key:'probes',label:'hőm. próbánként',color:colors[1]});
    if (target.trvs.length) choices.push({key:'valves',label:'szelepnyitás',color:'black'});
    drawPlot([], {...common, emptyMessage: values.length ? '' : emptyMessage, plotLabelTabs:tabs || (setting.detailed ? {
        prefix:target.label + ' — ',selected:metric,day:setting.day,onDayChange:navigateMainPlotDay,choices,onSelect:selectRadiatorMetric} : false)});
    curves.forEach(curve => curve.segments.forEach((segment, index) => drawPlot(segment, {...common, background:{show:false},
        axes:{left:false,bottom:false},showLockLabel:false,plotLabel:'',curveTooltip:curve.label,
        curveEndText:{show:index === curve.segments.length - 1,
            text:Number(segment.at(-1).value.toFixed(metric === 'valves' ? 0 : 1)) + (metric === 'valves' ? '%' : ' °C'),
            col:curve.color,fontSize:6,xOffset:3,yOffset:1.75},
        plotStyle:{...common.plotStyle,col:curve.color,endCap:metric !== 'valves' && index === curve.segments.length - 1}})));
}
