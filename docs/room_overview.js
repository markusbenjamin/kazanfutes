// Presentation-only grouping. Stable room IDs and control remain independent.
function averageOverviewTemperatures(series, maxGapHours = 2) {
    const streams = series.map(rows => (rows || []).filter(row =>
        Number.isFinite(row?.h_of_day_frac) && Number.isFinite(row?.temp))
        .slice().sort((a,b) => a.h_of_day_frac-b.h_of_day_frac));
    const hours = [...new Set(streams.flatMap(rows => rows.map(row => row.h_of_day_frac)))].sort((a,b)=>a-b);
    const positions = streams.map(()=>0);
    return hours.flatMap(hour => {
        const values = [];
        let live = false;
        streams.forEach((rows,index) => {
            let position = positions[index];
            while (position < rows.length && rows[position].h_of_day_frac < hour) position++;
            positions[index] = position;
            const right = rows[position], left = rows[position-1];
            if (right?.h_of_day_frac === hour) {
                values.push(right.temp);
                live ||= right.live === true;
            } else if (left && right && right.h_of_day_frac-left.h_of_day_frac <= maxGapHours) {
                const fraction = (hour-left.h_of_day_frac)/(right.h_of_day_frac-left.h_of_day_frac);
                values.push(left.temp+(right.temp-left.temp)*fraction);
            }
        });
        return values.length ? [{h_of_day_frac:hour,
            temp:values.reduce((sum,value)=>sum+value,0)/values.length,
            ...(live ? {live:true} : {})}] : [];
    });
}

function roomOverviewGroups(graphData, roomIds, rooms, selectedIds, prepare) {
    const groups = new Map(), selected = new Set(selectedIds.map(String));
    roomIds.forEach(id => {
        const name = rooms[id].name;
        if (!groups.has(name)) groups.set(name,{name,roomIds:[]});
        groups.get(name).roomIds.push(id);
    });
    return [...groups.values()].map(group => {
        const selectedMembers = group.roomIds.filter(id => selected.has(String(id)));
        const members = selectedMembers.length ? selectedMembers : group.roomIds;
        const series = members.map(id => prepare(graphData[`room_${id}_measurements`] || []));
        return {...group, emphasis:selectedMembers.length>0, colorRoom:group.roomIds[0],
            data:series.length===1 ? series[0] : averageOverviewTemperatures(series)};
    });
}
