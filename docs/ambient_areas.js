// SVG-only areas: no room registration, control vote or independent plot series.
let ambientAreaTargets = [];

function ambientAreaTemperature(target, system, now = new Date()) {
    const state = system?.state || {};
    if (target.source === 'ws90') {
        const weather = state.weather_station;
        return Number.isFinite(weather?.temperature_c) && livePlotFresh(weather.timestamp, 300, now)
            ? weather.temperature_c : null;
    }
    const values = target.rooms.map(id => livePlotFresh(state.sensor_last_updated?.[id], 7200, now)
        ? state.measured_temps?.[id] : null).filter(Number.isFinite);
    return values.length ? values.reduce((sum,value)=>sum+value,0)/values.length : null;
}

function initializeAmbientAreas(drawing) {
    ambientAreaTargets = [];
    const background = Array.from(drawing.children).find(node => node.id === 'background');
    const foreground = background ? background.nextElementSibling : drawing.firstElementChild;
    drawing.querySelectorAll('[data-temperature-source], [data-temperature-rooms]').forEach(node => {
        try {
            const source = node.getAttribute('data-temperature-source');
            const assigned = JSON.parse(node.getAttribute('data-temperature-rooms') || '[]');
            if ((source && source !== 'ws90') || !Array.isArray(assigned)
                || assigned.some(id => !/^[1-9]\d*$/.test(String(id)))
                || (source === 'ws90' && assigned.length)) throw Error('Invalid area temperature source');
            const rooms = [...new Set(assigned.map(String))];
            if (source !== 'ws90' && !rooms.length) throw Error('Area has no temperature sources');
            const shapes = [node,...node.querySelectorAll('path,rect,circle,ellipse,polygon,polyline')];
            const interactive = node.id === 'kisudvar' && source === 'ws90';
            [node,...node.querySelectorAll('*')].forEach(child => child.style.pointerEvents = interactive ? 'visiblePainted' : 'none');
            ambientAreaTargets.push({node,shapes,source,rooms});
            // Background areas must never obscure building objects or piping.
            if (node.parentNode === drawing && node !== foreground) drawing.insertBefore(node,foreground);
        } catch (error) { console.warn('Ignoring area colour mapping:',node.id,error.message); }
    });
    updateAmbientAreas(null);
}

function updateAmbientAreas(system) {
    const color = d3.scaleSequential(d3.interpolateRgb('rgba(0,0,200,1)','red')).domain([14,26]).clamp(true);
    ambientAreaTargets.forEach(target => {
        const temperature = ambientAreaTemperature(target,system);
        const fill = temperature === null ? 'rgb(230,230,230)' : color(temperature);
        target.shapes.forEach(node => {node.style.fill=fill;node.style.fillOpacity='1';});
    });
}
