const WEATHER_PLOT_METRICS = {
    temperature: { label: 'hőm./harmatp.', key: 'temperature_c', unit: '°C', color: 'rgb(28, 3, 252)', precision: 1 },
    humidity: { label: 'páratart.', key: 'humidity_pct', unit: '%', color: 'rgb(100, 180, 255)', precision: 0 },
    wind: { label: 'szél', key: 'wind_speed_m_s', unit: 'm/s', color: 'rgb(0, 100, 0)', precision: 1 },
    gust: { label: 'széllökés', key: 'gust_speed_m_s', unit: 'm/s', color: 'rgb(100, 150, 0)', precision: 1 },
    direction: { label: 'szélirány', key: 'wind_direction_deg', color: 'rgb(0, 100, 0)' },
    light: { label: 'fény', key: 'illuminance_lux', unit: 'klux', displayFactor: .001, color: 'rgb(190, 155, 0)', precision: 1 },
    uv: { label: 'UV', key: 'uv_index', unit: 'UV', color: 'rgb(150, 50, 150)', precision: 1 },
    rain: { label: 'csapadék össz.', key: 'precipitation_mm', unit: 'mm', color: 'rgb(40, 80, 180)', precision: 1 },
    pressure: { label: 'légnyomás', key: 'pressure_hpa', unit: 'hPa', color: 'rgb(70, 70, 70)', precision: 1 }
};
let weatherMetricSelection = 'temperature';
// Local experiment: set false to restore the daily-total precipitation plot.
const WEATHER_RAIN_RATE_PREVIEW = true;

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

const WIND_DIAL_UP_AZIMUTH_DEG = 265;

function windDirectionDisplayAngle(degrees) {
    // Rotate the display only; histogram bins retain their geographic bearings.
    return (((degrees - WIND_DIAL_UP_AZIMUTH_DEG) % 360 + 360) % 360) * Math.PI / 180;
}

function windDirectionLabelPosition(degrees, radius) {
    const angle = windDirectionDisplayAngle(degrees);
    return {x: Math.sin(angle) * (radius + 6), y: -Math.cos(angle) * (radius + 6)};
}

function drawWindDirectionHistogram(plotElement, plotDims, readings) {
    const bins = windDirectionHistogram(readings);
    const total = bins.reduce((sum, bin) => sum + bin.count, 0);
    const radius = Math.max(1, Math.min(plotDims.w, plotDims.h) * .36);
    const centre = plotElement.append('g').attr('class', 'wind-direction-histogram')
        .attr('transform', `translate(${plotDims.w / 2},${plotDims.h * .62})`);
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
    [['Ny', 270], ['É', 0], ['K', 90], ['D', 180]].forEach(([label, degrees]) => {
        const {x, y} = windDirectionLabelPosition(degrees, radius);
        centre.append('text').attr('x', x).attr('y', y).style('font-family', dashboardFont).style('font-size', '6px')
            .style('text-anchor', 'middle').style('dominant-baseline', 'middle').text(label);
    });
    if (!total) centre.append('text').attr('x', 0).attr('y', radius + 15).style('text-anchor', 'middle')
        .style('font-family', dashboardFont).style('font-size', '5px')
        .text('Nincs szélirányadat.');
}

function weatherRainPeriods(readings, endHour) {
    // Reuse the bounded binary-period handling, with explicit unknowns breaking rain.
    return extractRoomOccupancyPeriods(readings.filter(row => Object.hasOwn(row, 'rain_status'))
        .map(row => ({...row, occupancy: row.rain_status})), endHour, 15 / 60);
}

function weatherDailyPrecipitation(readings) {
    const first = readings.filter(row => Number.isFinite(row.h_of_day_frac) && Number.isFinite(row.precipitation_mm))
        .reduce((earliest, row) => !earliest || row.h_of_day_frac < earliest.h_of_day_frac ? row : earliest, null);
    if (!first) return readings;
    return readings.map(row => ({...row, precipitation_mm: Number.isFinite(row.precipitation_mm)
        ? row.precipitation_mm - first.precipitation_mm : row.precipitation_mm}));
}

function weatherGaussianIntegral(z) {
    // Error-function approximation: Gaussian mass between two times is their difference.
    const x = Math.abs(z) / Math.SQRT2, t = 1 / (1 + .3275911 * x);
    const erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
        - .284496736) * t + .254829592) * t * Math.exp(-x * x);
    return (1 + Math.sign(z) * erf) / 2;
}

function weatherPrecipitationRate(readings) {
    const rates = [], sigma = 5 / 60, radius = 3 * sigma;
    let samples = [];
    const finish = () => {
        const intervals = samples.slice(1).map((row, index) => ({start: samples[index].h_of_day_frac,
            end: row.h_of_day_frac, rate: (row.precipitation_mm - samples[index].precipitation_mm)
                / (row.h_of_day_frac - samples[index].h_of_day_frac)}));
        samples.forEach((row, index) => {
            let weighted = 0, weights = 0;
            if (index) for (const interval of intervals) {
                const start = Math.max(interval.start, row.h_of_day_frac - radius);
                const end = Math.min(interval.end, row.h_of_day_frac + radius);
                if (end <= start) continue;
                const weight = weatherGaussianIntegral((end - row.h_of_day_frac) / sigma)
                    - weatherGaussianIntegral((start - row.h_of_day_frac) / sigma);
                weighted += interval.rate * weight; weights += weight;
            }
            rates.push({h_of_day_frac: row.h_of_day_frac, precipitation_rate_mm_h: weights ? weighted / weights : null});
        });
        samples = [];
    };
    readings.filter(row => Number.isFinite(row.h_of_day_frac)).slice()
        .sort((a, b) => a.h_of_day_frac - b.h_of_day_frac).forEach(row => {
            const previous = samples.at(-1);
            const hours = previous ? row.h_of_day_frac - previous.h_of_day_frac : 0;
            if (!Number.isFinite(row.precipitation_mm) || previous && (hours <= 0 || hours > 15 / 60
                || row.precipitation_mm < previous.precipitation_mm)) {
                finish();
            }
            if (Number.isFinite(row.precipitation_mm)) samples.push(row);
            else rates.push({h_of_day_frac: row.h_of_day_frac, precipitation_rate_mm_h: null});
        });
    finish();
    return rates;
}

function drawWeatherMetricPlot(data, setting) {
    const rainRate = setting.metric === 'rain' && WEATHER_RAIN_RATE_PREVIEW;
    const metric = rainRate ? {...WEATHER_PLOT_METRICS.rain, label: 'csapadék', key: 'precipitation_rate_mm_h', unit: 'mm/h'}
        : WEATHER_PLOT_METRICS[setting.metric] || WEATHER_PLOT_METRICS.temperature;
    const rawReadings = data.weather_station || [];
    const readings = rainRate ? weatherPrecipitationRate(rawReadings) : setting.metric === 'rain' ? weatherDailyPrecipitation(rawReadings) : metric.displayFactor ? rawReadings.map(row => ({...row,
        [metric.key]: Number.isFinite(row[metric.key]) ? row[metric.key] * metric.displayFactor : row[metric.key]})) : rawReadings;
    const direction = setting.metric === 'direction';
    const smoothWind = setting.metric === 'wind' || setting.metric === 'gust';
    const curves = [{metric, tooltip: setting.metric === 'temperature' ? 'hőmérséklet' : undefined}];
    if (setting.metric === 'temperature') curves.push({metric: {key: 'dewpoint_c', unit: '°C', color: 'rgb(0, 130, 150)', precision: 1}, tooltip: 'harmatpont'});
    curves.forEach(curve => { curve.segments = direction ? [] : splitRoomMetricReadings(readings, curve.metric.key, 15 / 60); });
    const values = curves.flatMap(curve => curve.segments.flat().map(row => row[curve.metric.key]));
    let range = [0, 1];
    if (metric.key === 'humidity_pct') range = [0, 100];
    else if (values.length) {
        const low = Math.min(...values), high = Math.max(...values), pad = Math.max((high - low) * .1, 1);
        range = ['temperature_c', 'dewpoint_c', 'pressure_hpa'].includes(metric.key) ? [low - pad, high + pad] : [0, Math.max(1, high * 1.1)];
    }
    // The axis-free dial has symmetric margins, preserving its size and vertical placement.
    const common = { parentId: 'graph', margins: {top: .24, right: direction ? .065 : .03, bottom: .15, left: direction ? .065 : .1},
        domain: {bottom: [0, 24], left: range}, dataKeys: {bottom: 'h_of_day_frac', left: metric.key},
        axesLabel: {bottom: direction ? '' : 'óra', left: direction ? '' : metric.unit},
        axes: {left: !direction, bottom: !direction}, smoothing: {bottom: 0, left: smoothWind ? 5 : 0},
        plotStyle: {joined: true, col: metric.color, thickness: '2', monotone: !smoothWind, smoothCurve: smoothWind, startCap: false, endCap: true},
        segment: {do: false}, plotLabel: '', curveEndText: {show: false} };
    const rainPeriods = setting.metric === 'rain' ? weatherRainPeriods(rawReadings, setting.day === dayStamp() ? getFractionalHourOfDay() : 24)
        .map(period => ({...period, y1: range[0], y2: range[1], fill: 'rgba(60,100,180,0.05)', stroke: 'none', strokeWeight: 0, dashed: false})) : [];
    const area = drawPlot([], {...common, rects: {when: 'before', list: rainPeriods},
        plotLabelTabs: {prefix: 'WS90 — ', day: setting.day, onDayChange: navigateSelectorPlotDay,
        columns: 3, selected: setting.metric, choices: Object.entries(WEATHER_PLOT_METRICS).map(([key, value]) => ({key, label: key === 'rain' && WEATHER_RAIN_RATE_PREVIEW ? 'csapadék' : value.label, color: value.color})),
        onSelect: selectWeatherMetricPlot}});
    if (direction) { drawWindDirectionHistogram(area.plotElement, area.plotDims, readings); return; }
    curves.forEach(curve => curve.segments.forEach((segment, index) => drawPlot(segment, {...common,
        dataKeys: {...common.dataKeys, left: curve.metric.key}, plotStyle: {...common.plotStyle, col: curve.metric.color},
        curveTooltip: curve.tooltip, background: {show: false}, axes: {left: false, bottom: false},
        showLockLabel: false, curveEndText: {show: index === curve.segments.length - 1,
            text: Number(segment.at(-1)[curve.metric.key].toFixed(curve.metric.precision)) + ' ' + curve.metric.unit,
            col: curve.metric.color, fontSize: 6, xOffset: 3, yOffset: 1.75}})));
}
