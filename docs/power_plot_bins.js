// Display-only, time-weighted ten-minute means. Never alters energy integrals.
function powerPlotBins(readings, keys, end = 24) {
    const step = 1 / 6, maxHold = 3 / 60;
    const byHour = new Map();
    readings.forEach(row => {
        if (Number.isFinite(row.h_of_day_frac) && row.h_of_day_frac >= 0 && row.h_of_day_frac <= 24)
            byHour.set(row.h_of_day_frac, row);
    });
    const sorted = [...byHour.values()].sort((a,b) => a.h_of_day_frac - b.h_of_day_frac);
    const bins = new Map();
    sorted.forEach((row, index) => {
        const start = row.h_of_day_frac;
        // Unknown samples stop the preceding hold; long outages are not filled.
        const stop = Math.min(end, sorted[index + 1]?.h_of_day_frac ?? start + 1 / 60, start + maxHold);
        for (let bin = Math.floor((start + 1e-9) / step); bin * step < stop - 1e-9; bin++) {
            const duration = Math.min(stop, (bin + 1) * step) - Math.max(start, bin * step);
            if (duration <= 0) continue;
            keys.forEach(key => {
                if (!Number.isFinite(row[key])) return;
                if (!bins.has(bin)) bins.set(bin, {sums: {}, coverage: {}});
                const item = bins.get(bin);
                item.sums[key] = (item.sums[key] || 0) + row[key] * duration;
                item.coverage[key] = (item.coverage[key] || 0) + duration;
            });
        }
    });
    return [...bins].sort((a,b) => a[0] - b[0]).map(([bin, item]) => {
        const bin_start = bin * step, bin_end = Math.min(end, (bin + 1) * step);
        const row = {bin_start, bin_end, h_of_day_frac: (bin_start + bin_end) / 2, coverage: item.coverage};
        keys.forEach(key => {if (item.coverage[key]) row[key] = item.sums[key] / item.coverage[key];});
        return row;
    });
}

function powerBinTimeLabel(row) {
    const stamp = hour => {
        const minute = Math.floor(hour * 60 + 1e-7);
        return String(Math.floor(minute / 60)).padStart(2, '0') + ':' + String(minute % 60).padStart(2, '0');
    };
    return stamp(row.bin_start) + '–' + stamp(row.bin_end);
}
