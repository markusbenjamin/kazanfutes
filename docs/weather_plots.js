const WEATHER_PLOT_METRICS = {
    temperature: { label: 'hőm.', key: 'temperature_c', unit: '°C', color: 'rgb(28, 3, 252)', precision: 1 },
    humidity: { label: 'páratart.', key: 'humidity_pct', unit: '%', color: 'rgb(100, 180, 255)', precision: 0 },
    dewpoint: { label: 'harmatp.', key: 'dewpoint_c', unit: '°C', color: 'rgb(0, 130, 150)', precision: 1 },
    wind: { label: 'szél', key: 'wind_speed_m_s', unit: 'm/s', color: 'rgb(0, 100, 0)', precision: 1 },
    gust: { label: 'széllökés', key: 'gust_speed_m_s', unit: 'm/s', color: 'rgb(100, 150, 0)', precision: 1 },
    direction: { label: 'szélirány', key: 'wind_direction_deg', color: 'rgb(0, 100, 0)' },
    light: { label: 'fény', key: 'illuminance_lux', unit: 'klux', displayFactor: .001, color: 'rgb(190, 155, 0)', precision: 1 },
    uv: { label: 'UV', key: 'uv_index', unit: 'UV', color: 'rgb(150, 50, 150)', precision: 1 },
    rain: { label: 'csapadék össz.', key: 'precipitation_mm', unit: 'mm', color: 'rgb(40, 80, 180)', precision: 1 },
    rainStatus: { label: 'esőjel', key: 'rain_status', unit: '0/1', color: 'rgb(60, 100, 180)', precision: 0 },
    pressure: { label: 'légnyomás', key: 'pressure_hpa', unit: 'hPa', color: 'rgb(70, 70, 70)', precision: 1 }
};
let weatherMetricSelection = 'temperature';

function createWeatherMetricPlotSetting(day, metric = weatherMetricSelection) {
    if (!WEATHER_PLOT_METRICS[metric]) metric = 'temperature';
    return { title: 'weather_metrics', sourceElementId: 'external_thermometer', day, metric, types: ['weather_station'], conditionals: [] };
}

function openWeatherMetricPlot(event, elementId) {
    if (!event.ctrlKey || elementId !== 'external_thermometer') return false;
    event.preventDefault();
    mainGraphSetting = createWeatherMetricPlotSetting(elementToMainGraphSettingMapping[elementId].day);
    mainGraphContentLocked = true;
    drawMainGraph({ [mainGraphSetting.day]: {} });
    drawMainGraph();
    return true;
}

function selectWeatherMetricPlot(metric) {
    if (mainGraphSetting.title !== 'weather_metrics' || !WEATHER_PLOT_METRICS[metric]) return;
    weatherMetricSelection = metric;
    mainGraphSetting = createWeatherMetricPlotSetting(mainGraphSetting.day, metric);
    mainGraphContentLocked = true;
    drawMainGraph({ [mainGraphSetting.day]: {} });
    drawMainGraph();
}

function windDirectionHistogram(readings, binCount = 16) {
    const bins = Array.from({length: binCount}, (_, index) => ({angle: index * 360 / binCount, count: 0}));
    readings.forEach(row => {
        if (!Number.isFinite(row.wind_direction_deg) || !Number.isFinite(row.wind_speed_m_s) || row.wind_speed_m_s <= 0) return;
        const angle = ((row.wind_direction_deg % 360) + 360 + 180 / binCount) % 360;
        bins[Math.floor(angle / (360 / binCount))].count++;
    });
    return bins;
}

function windDirectionDisplayAngle(degrees) {
    // The building on the dashboard is west-up; retain geographic bin values.
    return ((degrees + 90) % 360) * Math.PI / 180;
}

function drawWindDirectionHistogram(plotElement, plotDims, readings) {
    const bins = windDirectionHistogram(readings);
    const total = bins.reduce((sum, bin) => sum + bin.count, 0);
    const radius = Math.max(1, Math.min(plotDims.w, plotDims.h) * .36);
    const centre = plotElement.append('g').attr('class', 'wind-direction-histogram')
        .attr('transform', `translate(${plotDims.w / 2},${plotDims.h / 2})`);
    const max = Math.max(1, ...bins.map(bin => bin.count));
    const scale = d3.scaleSqrt().domain([0, max]).range([0, radius]);
    [.25, .5, .75, 1].forEach(fraction => {
        centre.append('circle').attr('r', radius * fraction).attr('fill', 'none').attr('stroke', '#ddd').attr('stroke-width', .3);
    });
    const step = Math.PI * 2 / bins.length;
    const rotation = windDirectionDisplayAngle(0);
    bins.forEach((bin, index) => {
        if (!bin.count) return;
        centre.append('path').attr('d', d3.arc().innerRadius(0).outerRadius(scale(bin.count))
            .startAngle(index * step + rotation - step / 2).endAngle(index * step + rotation + step / 2).padAngle(.015)())
            .attr('fill', 'rgb(0, 100, 0)').attr('stroke', 'white').attr('stroke-width', .3);
    });
    [['Ny', 0, -radius - 5], ['É', radius + 6, 0], ['K', 0, radius + 7], ['D', -radius - 7, 0]].forEach(([label, x, y]) => {
        centre.append('text').attr('x', x).attr('y', y).style('font-family', dashboardFont).style('font-size', '6px')
            .style('text-anchor', 'middle').style('dominant-baseline', 'middle').text(label);
    });
    if (!total) centre.append('text').attr('x', 0).attr('y', radius + 15).style('text-anchor', 'middle')
        .style('font-family', dashboardFont).style('font-size', '5px')
        .text('Nincs szélirányadat.');
}

function drawWeatherMetricPlot(data, setting) {
    const metric = WEATHER_PLOT_METRICS[setting.metric] || WEATHER_PLOT_METRICS.temperature;
    const rawReadings = data.weather_station || [];
    const readings = metric.displayFactor ? rawReadings.map(row => ({...row,
        [metric.key]: Number.isFinite(row[metric.key]) ? row[metric.key] * metric.displayFactor : row[metric.key]})) : rawReadings;
    const direction = setting.metric === 'direction';
    const smoothWind = setting.metric === 'wind' || setting.metric === 'gust';
    const segments = direction ? [] : splitRoomMetricReadings(readings, metric.key, 15 / 60);
    const values = segments.flat().map(row => row[metric.key]);
    let range = [0, 1];
    if (metric.key === 'humidity_pct') range = [0, 100];
    else if (values.length) {
        const low = Math.min(...values), high = Math.max(...values), pad = Math.max((high - low) * .1, 1);
        range = ['temperature_c', 'dewpoint_c', 'pressure_hpa'].includes(metric.key) ? [low - pad, high + pad] : [0, Math.max(1, high * 1.1)];
    }
    const common = { parentId: 'graph', margins: {top: .3, right: .03, bottom: .15, left: .1},
        domain: {bottom: [0, 24], left: range}, dataKeys: {bottom: 'h_of_day_frac', left: metric.key},
        axesLabel: {bottom: direction ? '' : 'óra', left: direction ? '' : metric.unit},
        axes: {left: !direction, bottom: !direction}, smoothing: {bottom: 0, left: smoothWind ? 5 : 0},
        plotStyle: {joined: true, col: metric.color, thickness: '2', monotone: !smoothWind, smoothCurve: smoothWind, startCap: false, endCap: true},
        segment: {do: false}, plotLabel: '', curveEndText: {show: false} };
    const area = drawPlot([], {...common, plotLabelTabs: {prefix: 'WS90 — ', day: setting.day, onDayChange: navigateSelectorPlotDay,
        columns: 4, selected: setting.metric, choices: Object.entries(WEATHER_PLOT_METRICS).map(([key, value]) => ({key, label: value.label, color: value.color})),
        onSelect: selectWeatherMetricPlot}});
    if (direction) { drawWindDirectionHistogram(area.plotElement, area.plotDims, readings); return; }
    segments.forEach((segment, index) => drawPlot(segment, {...common, background: {show: false}, axes: {left: false, bottom: false},
        showLockLabel: false, curveEndText: {show: index === segments.length - 1,
            text: Number(segment.at(-1)[metric.key].toFixed(metric.precision)) + ' ' + metric.unit,
            col: metric.color, fontSize: 6, xOffset: 3, yOffset: 1.75}}));
}
