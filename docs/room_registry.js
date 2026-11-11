// Inactive v2 client support. The assembled candidate loads this before data.js.
class RoomRegistryModel {
    constructor(definitions, registry) {
        if (definitions?.schema_version !== 2 || !definitions.rooms) throw Error('Invalid room definitions');
        this.definitions = definitions.rooms;
        this.setRegistry(registry);
    }
    setRegistry(registry) {
        if (registry?.schema_version !== 1 || !registry.rooms) throw Error('Invalid room registry');
        const names = Object.fromEntries(Object.entries(registry.rooms).filter(([, row]) => row != null));
        if (Object.keys(names).length !== Object.keys(this.definitions).length) throw Error('Registry room IDs do not match');
        for (const id of Object.keys(this.definitions)) {
            if (!/^[1-9]\d*$/.test(id) || typeof names[id]?.display_name !== 'string' || !names[id].display_name.trim())
                throw Error('Invalid room identity or display name: ' + id);
        }
        const changed = JSON.stringify(this.names) !== JSON.stringify(names);
        this.names = names;
        return changed;
    }
    name(id) { return this.names[String(id)]?.display_name || ''; }
    ids(controlled = false) {
        return Object.keys(this.definitions).filter(id => this.definitions[id].included
            && (!controlled || this.definitions[id].controlled)).map(Number).sort((a,b) => a-b);
    }
    stateRows() {
        return Object.fromEntries(this.ids().map(id => {
            const definition = this.definitions[id];
            return [id, {roomID: 'room_' + id, name: this.name(id), controlled: definition.controlled,
                cycle: definition.cycle == null ? null : Number(definition.cycle),
                hasValve: definition.valve_mode === 'trv', presenceSensors: definition.presence_sensors || []}];
        }));
    }
}

let roomV2Model;
function roomV2Configure(definitions, registry) { roomV2Model = new RoomRegistryModel(definitions, registry); }
function roomV2RuntimeStates() { return roomV2Model.stateRows(); }
function roomV2IncludedRooms() { return roomV2Model.ids(); }
function roomV2ControlledRooms() { return roomV2Model.ids(true); }
function roomV2Name(id) { return roomV2Model.name(id); }
function roomV2Fresh(stamp, seconds = 180) {
    if (typeof stamp !== 'string') return false;
    const age = ((typeof dashboardNow === 'function' ? dashboardNow() : new Date()) - dateFromTimestamp(stamp)) / 1000;
    return Number.isFinite(age) && age >= -5 && age <= seconds;
}
function roomV2RefreshRegistry(registry) {
    if (!registry) return;
    try {
        if (roomV2Model.setRegistry(registry)) {
            for (const [id, room] of Object.entries(roomsDataAndState)) room.name = roomV2Name(id);
            drawMainGraph();
        }
    } catch (error) { console.warn('Retaining last valid room names:', error.message); }
}
function roomV2UpdateRooms(system) {
    roomV2RefreshRegistry(system.room_registry);
    const differences = {};
    for (const [id, room] of Object.entries(roomsDataAndState)) {
        const state = system.state || {};
        const temperature = state.measured_temps?.[id];
        const stamp = state.sensor_last_updated?.[id];
        room.lastUpdated = stamp;
        room.temp = Number.isFinite(temperature) && roomV2Fresh(stamp, 7200)
            ? temperature.toFixed(1).replace(/\.0$/, '') : 'szenzor hiba';
        const occupancy = roomV2Fresh(state.last_updated) && room.presenceSensors.length
            ? state.occupancy?.[id] : null;
        room.occupancy = typeof occupancy === 'boolean' ? occupancy : null;
        updateRoomColor(room.roomID, Number.isFinite(temperature) ? temperature : null, stamp, {}, room.occupancy);
        room.set = room.controlled && state.set_temps ? roomControlSetTemperature(state, id) : null;
        const control = room.controlled ? system.control?.rooms?.[id] : null;
        room.vote = control?.vote;
        room.reason = control ? reasonMapping[control.reason]?.message || '' : '';
        if (room.controlled) differences[id] = roomV2Fresh(stamp, 7200) && Number.isFinite(temperature)
            && Number.isFinite(room.set) ? temperature - room.set : 'missing';
    }
    return differences;
}
function roomV2PlotSettings() {
    return Object.fromEntries(roomV2IncludedRooms().map(id => {
        const controlled = roomsDataAndState[id].controlled;
        return ['room_' + id, {title:'room_plot', roomNumToPlot:id, day:dayStamp(), conditionals:[],
            types: controlled ? [`room_${id}_valve_state`, `room_${id}_measurements`, `room_${id}_set_temps`, 'heating_state', 'override_requests']
                : [`room_${id}_measurements`]}];
    }));
}
function roomColorValue(id) {
    const existing = [4,5,6,7,8,1,2,10,11,12,-1,9,3];
    return existing[Number(id)-1] ?? (Number(id)*7 % 12)+1;
}
function roomV2TextOffsets() {
    const known = {1:[.05,0],5:[.15,.15],6:[.05,.1],7:[-.05,0],8:[0,.12],9:[.05,.07],
        10:[-.05,.16],11:[.05,0],12:[0,.25],13:[-.1,0]};
    return Object.fromEntries(roomV2IncludedRooms().map(id => ['room_'+id,
        {x:known[id]?.[0] || 0, y:known[id]?.[1] || 0}]));
}
function roomV2Escape(value) {
    return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function roomV2CloneForEmphasis(node) {
    const copy = node.cloneNode(true);
    [copy, ...copy.querySelectorAll('[id]')].forEach(element => {
        element.removeAttribute('id'); element.removeAttribute('data-room-id');
    });
    return copy;
}
function setupRoomV2Tooltip() {
    const tooltip = d3.select('#tooltip');
    for (const room of Object.values(roomsDataAndState)) {
        d3.select('#'+room.roomID).on('mouseover.tooltip', event => {
            const lines = [roomV2Escape(room.name)];
            if (room.temp && room.temp !== 'szenzor hiba') lines.push(roomV2Escape(room.temp)+' °C'
                + (room.controlled && Number.isFinite(room.set) ? ' / ['+room.set.toFixed(1)+' °C]' : ''));
            if (room.controlled && room.reason) lines.push(roomV2Escape(dashboardText(room.reason)));
            tooltip.interrupt().html(lines.join('<br>')).style('visibility','visible')
                .style('left',(event.pageX+5)+'px').style('top',(event.pageY-28)+'px');
        }).on('mousemove.tooltip', event => tooltip.style('left',(event.pageX+5)+'px').style('top',(event.pageY-28)+'px'))
            .on('mouseout.tooltip',()=>tooltip.interrupt().style('visibility','hidden'));
    }
}
function drawRoomV2MeasuredPlot(data, setting) {
    const rows = prepareRoomTemperatureForDisplay(data[`room_${setting.roomNumToPlot}_measurements`] || []);
    const extent = rows.length ? d3.extent(rows, row=>row.temp) : [15,25];
    const result = drawPlot(rows, {parentId:'graph',background:{show:true},domain:{bottom:[0,24],
        left:[Math.floor(extent[0])-1,Math.ceil(extent[1])+1]},dataKeys:{bottom:'h_of_day_frac',left:'temp'},
        axesLabel:{bottom:'óra',left:'°C'},smoothing:{bottom:0,left:25},
        plotStyle:{joined:true,col:'rgba(255,0,0,1)',thickness:'2',startCap:false,endCap:true},
        curveTooltip:'mért hőmérséklet',plotLabel:roomV2Name(setting.roomNumToPlot)+' mért hőmérséklet',
        curveEndText:{show:rows.length>0,fontSize:6,text:rows.length?rows.at(-1).temp.toFixed(1)+' °C':'',
            col:'rgba(255,0,0,1)',xOffset:3,yOffset:1.75}});
    if (!rows.length && result?.plotElement) setPlotEmptyMessage(result.plotElement.append('text')
        .attr('x',40).attr('y',30).style('font-size',6),'Az adott napra nincs adat.');
}

async function startRoomV2Dashboard() {
    const read = async path => {
        const response = await fetch(path, {cache:'no-store'});
        if (!response.ok) throw Error('Cannot load '+path);
        return response.json();
    };
    const [definitions, registry] = await Promise.all([read('room_definitions.json'),read('room_registry.json')]);
    roomV2Configure(definitions, registry);
    const load = path => new Promise((resolve,reject)=>{
        const script=document.createElement('script'); script.src=path;
        script.onload=resolve; script.onerror=reject; document.body.append(script);
    });
    await load('data.js?v=room-id-v2');
    await load('draw.js?v=room-id-v2');
}
