const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const draws=[], markers=[], tooltips=[], loads=[];
const curves=[], headings=[];
function line(){let x,y,curve;const f=rows=>{curves.push({rows:rows.map(row=>[x(row),y(row)]),curve});return 'M0,0C1,1,2,2,3,3';};
    f.x=value=>(x=value,f);f.y=value=>(y=value,f);f.curve=value=>(curve=value,f);return f;}
function selection(){const node={attrs:{},styles:{},events:{},raises:0,append(tag){const child=selection();child.tag=tag;markers.push(child);return child;},
    attr(key,value){this.attrs[key]=value;return this;},style(key,value){this.styles[key]=value;return this;},text(value){this.value=value;return this;},
    on(key,handler){this.events[key]=handler;return this;},raise(){this.raises++;return this;}};return node;}
function scale(){let domain=[0,1],range=[0,1];const f=value=>range[0]+(value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
    f.domain=value=>(domain=value,f);f.range=value=>(range=value,f);return f;}
const context=vm.createContext({Number,Math,Date,Object,Array,dayStamp:()=> '2026-10-27',isMobile:false,
    dashboardFont:'Consolas',allControlledRooms:[1,2,3],roomsColorRemap:[1,2,3],roomsColorScale:value=>'room-color-'+value,
    mainGraphSetting:{},mainGraphContentLocked:false,ROOM_CONTROL_WINDOW_DAYS:7,
    elementToMainGraphSettingMapping:{PK:{title:'room_plot',roomNumToPlot:3}},
    roomsDataAndState:{1:{name:'Szita',cycle:1},2:{name:'Fészek',cycle:2},3:{name:'PK',cycle:2}},
    d3:{scaleLinear:scale,line,curveCatmullRom:{alpha:value=>({kind:'catmull-rom',alpha:value})}},drawMainGraph(){},clearMainGraphs(){},
    collectDataFromGitHub:(requests,callback)=>loads.push({requests,callback}),
    drawPlot:(rows,options)=>{draws.push({rows,options});return{plotElement:selection(),plotDims:{w:200,h:120}};},
    bindPlotCurveTooltip:(node,label)=>tooltips.push(label)});
for(const file of ['cycle_heat_plots','room_control_plots','room_phase_plots'])
    vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../docs/'+file+'.js'),'utf8'),context);
context.drawPlotTitleSelector=(node,dims,options,font)=>headings.push({node,options,font});
const evaluate=code=>JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.event={altKey:true,preventDefault(){}};
assert.equal(evaluate("openRoomControlPlot(event,'PK')"),true);
assert.equal(context.mainGraphSetting.title,'room_control_phase','room analytics defaults to the phase plane');
context.mainGraphSetting.day='2026-10-26';
vm.runInContext("selectRoomAnalyticView('phase')",context);
assert.equal(context.mainGraphSetting.title,'room_control_phase');
assert.equal(context.mainGraphSetting.day,'2026-10-26');
assert.deepEqual(evaluate('mainGraphSetting.types'),['room_3_phase_points']);
vm.runInContext('navigateRoomControlDay(-1)',context);
assert.equal(context.mainGraphSetting.day,'2026-10-25');
vm.runInContext('drawRoomControlView()',context);
assert.equal(loads.at(-1).requests.length,1);
assert.equal(loads.at(-1).requests[0].type,'room_3_phase_points');
const point=(time,error,intensity,source='measured')=>({timestamp:'2026-10-26-'+time,error_k:error,intensity_k:intensity,
    source,model_quality:'default',room_temp_c:20,set_temp_c:22});
context.points=[point('10-00-00',2,5),point('10-01-00',1,7),point('10-02-00',2,6),
    point('10-03-00',null,null,'unavailable'),point('10-04-00',2,8,'estimated'),point('10-10-00',1,9,'estimated')];
const segments=evaluate("roomPhaseSegments(points,'2026-10-26')");
assert.equal(segments.length,1,'all valid observations join across unavailable records, source changes and long gaps');
assert.deepEqual(segments[0].map(point=>point.error_k),[2,1,2,2,1],'phase trajectory preserves chronological loops, not X sorting');
assert.deepEqual(segments[0].map(point=>point.deviation_k),[-2,-1,-2,-2,-1]);
assert.equal(context.points[0].error_k,2,'published error is not mutated by the display convention');
context.offsetPoints=[point('10-00-00',0,-20),point('10-01-00',0,-9.79)];
assert.deepEqual(evaluate("roomPhaseSegments(offsetPoints,'2026-10-26',20)[0].map(point=>point.intensity_k)"),[0,10.21],
    'encoded offset is undone: radiator at room temperature is zero and warmer radiators are positive');
assert.equal(context.offsetPoints[1].intensity_k,-9.79,'display offset removal never mutates published points');
assert.equal(evaluate("roomPhaseSegments(offsetPoints,'2026-10-26',0)[0][1].intensity_k"),-9.79,
    'zero-offset payloads are not shifted again');
context.payload={schema_version:1,offset_k:20,points:context.points};
context.data={'2026-10-26':{room_3_phase_points:context.payload}};
context.setting={title:'room_control_phase',roomNumToPlot:3,day:'2026-10-26'};
vm.runInContext('drawRoomPhasePlot(data,setting)',context);
assert.equal(draws[0].options.plotLabelTabs,false,'phase heading is drawn above its own state row');
assert.deepEqual(Array.from(headings[0].options.choices,choice=>choice.label),['fázissík','összegzés']);
const initialState=markers.find(node=>node.attrs.class==='room-phase-state');
assert.equal(initialState.value,'szoba jó de melegszik, radiátor meleg és melegszik');
assert.equal(initialState.styles['font-family'],'Consolas');
assert.equal(initialState.styles['font-size'],'6px','state uses the axis-label font size');
assert.equal(initialState.styles.fill,'#777','state matches unselected selector text');
assert.equal(initialState.styles['text-anchor'],'middle');
assert.ok(initialState.attrs.y<0,'state remains above the axes, not over the trajectory');
assert.equal(draws[0].options.domain.bottom[0],0);
assert.equal(draws[0].options.domain.bottom[1],30);
assert.equal(draws[0].options.axesLabel.bottom,'radiátor hőmérséklet (K)');
assert.equal(draws[0].options.axesLabel.left,'eltérés: mért − kért (K)');
assert.equal(draws[0].options.dataKeys.bottom,'intensity_k');
assert.equal(draws[0].options.dataKeys.left,'deviation_k');
assert.deepEqual(curves[0].curve,{kind:'catmull-rom',alpha:.5});
assert.equal(curves[0].rows.length,5);
const zeroLines=markers.filter(node=>node.attrs.class==='room-phase-zero-line');
assert.equal(zeroLines.length,2);
assert.ok(zeroLines.every(node=>node.attrs['stroke-dasharray']==='2,2'));
const trajectory=markers.find(node=>node.attrs.class==='room-phase-trajectory');
assert.equal(trajectory.attrs.stroke,'room-color-3');
assert.equal(trajectory.attrs['stroke-width'],1.25);
const timeMarkers=markers.filter(node=>node.attrs.class==='room-phase-time-point');
assert.equal(timeMarkers.length,0,'a short trajectory has no interior hourly markers');
const start=markers.filter(node=>node.attrs.class==='room-phase-start-marker');
assert.equal(start.length,1);
assert.equal(start[0].attrs.fill,'black');
assert.equal(start[0].tag,'path');
assert.ok(start[0].attrs.d&&start[0].attrs.transform.includes('rotate('));
assert.equal(start[0].attrs['data-timestamp'],'2026-10-26-10-00-00');
const latest=markers.filter(node=>node.attrs.class==='room-phase-latest-point');
assert.equal(latest.length,1);
assert.equal(latest[0].attrs.fill,'room-color-3');
assert.equal(latest[0].attrs.r,3);
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-direction').length,1);
assert.ok(tooltips.filter(text=>text!=='PK').every(text=>/^\d{2}:\d{2}$/.test(text)));
assert.equal(tooltips.at(-1),'10:10');
context.repeated=[point('10-00-00',2,5),point('10-01-00',1,7),point('10-02-00',1,7)];
const direction=evaluate('roomPhaseDirection(repeated, value=>value, value=>-value)');
assert.ok(direction.dx>0&&direction.dy<0,'arrow follows the incoming direction with overheating upward, skipping repeated points');
context.signPoints=[point('10-00-00',2,-10),point('10-01-00',-2,10)];
const signDirection=evaluate('roomPhaseDirection(signPoints, value=>value, value=>-value)');
assert.ok(signDirection.dx>0&&signDirection.dy<0,'overheating moves up and hotter radiators move right');
assert.equal(evaluate('roomPhaseDirection([repeated[1],repeated[2]], value=>value, value=>value)'),null);
function movement(rows) {
    context.movementRows=rows;
    return evaluate("(() => {const points=roomPhaseSegments(movementRows,'2026-10-26')[0] || []; const motion=roomPhaseMovement(points,roomPhaseDirection(points,value=>value,value=>-value)); return [['szoba',motion.room],['radiátor',motion.radiator]].filter(([,motion])=>motion).map(([name,motion])=>name+' '+motion).join(', ');})()");
}
assert.equal(movement([]),'');
assert.equal(movement([point('10-00-00',0,2)]),'');
assert.equal(movement([point('10-00-00',0,2),point('10-10-00',-.1,2.5)]),'szoba melegszik, radiátor melegszik');
assert.equal(movement([point('10-00-00',0,2),point('10-10-00',.1,1.5)]),'szoba hűl, radiátor hűl');
assert.equal(movement([point('10-00-00',0,2),point('10-10-00',-.09,2.49)]),'','independent deadbands omit both small components');
assert.equal(movement([point('10-00-00',0,2),point('10-10-00',-.2,2.1)]),'szoba melegszik');
assert.equal(movement([point('10-00-00',0,2),point('10-10-00',.02,3)]),'radiátor melegszik');
assert.equal(movement([point('10-00-00',0,2),point('10-05-00',.2,3)]),'szoba hűl, radiátor melegszik');
assert.equal(movement([point('10-00-00',0,2),point('10-10-00',-1,5),point('10-11-00',-.8,4)]),
    'szoba hűl, radiátor hűl','use the final arrow direction, not the opposite ten-minute trend');
assert.equal(movement([point('10-05-00',0,2),point('10-10-00',-1,5),point('10-11-00',-1,5)]),
    'szoba melegszik, radiátor melegszik','repeated endpoint uses the same previous distinct point as the arrow');
assert.equal(movement([point('10-00-00',0,2),point('10-11-00',-1,5)]),'','long incoming gaps do not imply a current state');
assert.equal(movement([point('10-00-00',0,2),point('10-00-00',-1,5)]),'','duplicate timestamps have no valid rate');
assert.equal(movement([point('10-00-00',0,2),point('10-10-00',0,2)]),'','stationary trajectories have no state');
function diagnostic(rows) {
    context.diagnosticRows=rows;
    return evaluate("(() => {const points=roomPhaseSegments(diagnosticRows,'2026-10-26')[0] || []; return roomPhaseDiagnosticText(points,roomPhaseDirection(points,value=>value,value=>-value));})()");
}
assert.equal(diagnostic([]),'');
assert.equal(evaluate('ROOM_PHASE_ROOM_BAND_K'),1);
assert.equal(diagnostic([point('10-00-00',1.01,16)]),'szoba hideg, radiátor meleg');
assert.equal(diagnostic([point('10-00-00',-1.01,5)]),'szoba meleg, radiátor hideg');
assert.equal(diagnostic([point('10-00-00',1,15)]),'szoba jó, radiátor langyos','both exact upper boundaries are inclusive');
assert.equal(diagnostic([point('10-00-00',-1,5)]),'szoba jó, radiátor hideg','exact lower boundaries are inclusive');
assert.equal(diagnostic([point('10-00-00',.9,15.01)]),'szoba jó, radiátor meleg','the full plus/minus one K band is good');
assert.equal(diagnostic([point('10-00-00',0,5.01)]),'szoba jó, radiátor langyos');
assert.equal(diagnostic([{...point('10-00-00',1.3,99),radiator_temp_c:30,room_temp_c:20}]),
    'szoba hideg, radiátor langyos','actual radiator-minus-room temperatures take precedence over X fallback');
assert.equal(diagnostic([{...point('10-00-00',1.3,20),radiator_temp_c:null}]),'szoba hideg, radiátor meleg','older payloads retain the zero-offset axis fallback');
assert.equal(diagnostic([point('10-00-00',.9,16),point('10-05-00',1.1,17)]),
    'szoba hideg és hűl, radiátor meleg és melegszik');
assert.equal(diagnostic([point('10-00-00',0,10),point('10-10-00',-.02,9)]),
    'szoba jó, radiátor langyos és hűl','quiet component keeps its state without a conjunction');
assert.equal(diagnostic([point('10-00-00',0,10),point('10-10-00',.2,10)]),
    'szoba jó de hűl, radiátor langyos');
assert.equal(diagnostic([point('10-00-00',0,10),point('10-10-00',-.2,10)]),
    'szoba jó de melegszik, radiátor langyos');
assert.equal(diagnostic([point('10-00-00',-1.2,10),point('10-10-00',-1.4,9)]),
    'szoba meleg és melegszik, radiátor langyos és hűl','other room states and radiator retain és');
assert.equal(diagnostic([point('10-00-00',1.2,20),point('11-00-00',1.4,10)]),
    'szoba hideg, radiátor langyos','long gaps suppress motion, not the latest valid states');
context.corner=[point('10-00-00',0,0),point('10-01-00',0,1),point('10-02-00',-1,1)];
const tangent=evaluate('roomPhasePointDirection(corner,1,value=>value,value=>value)');
assert.ok(Math.abs(tangent.dx-Math.SQRT1_2)<1e-12&&Math.abs(tangent.dy-Math.SQRT1_2)<1e-12,
    'direction follows the forward Catmull–Rom tangent, not just the incoming leg');
assert.deepEqual(evaluate("roomPhaseSegments([], '2026-10-26')"),[]);
assert.deepEqual(evaluate('roomPhaseHourlyPoints([])'),[]);
context.hourlyPoints=[point('00-00-20',1,2),point('00-59-40',1,3),point('01-03-00',1,4),
    point('01-58-00',1,5),point('02-00-00',1,6),point('02-59-40',1,7),point('03-00-20',1,8),point('03-10-00',1,9)];
assert.deepEqual(evaluate("roomPhaseHourlyPoints(roomPhaseSegments(hourlyPoints, '2026-10-26')[0]).map(point=>point.timestamp.slice(11))"),
    ['00-00-20','00-59-40','02-00-00','02-59-40'], 'hourly markers use the closest observation on either side, with earlier ties');
context.gapPoints=[point('00-00-00',1,2),point('04-00-00',1,3)];
assert.equal(evaluate("roomPhaseHourlyPoints(roomPhaseSegments(gapPoints,'2026-10-26')[0]).length"),2,
    'long gaps never duplicate an observation');
assert.deepEqual(evaluate('roomPhaseSmoothedPoints([])'),[]);
context.noisyPoints=[point('10-00-00',0,0),point('10-01-00',0,0),point('10-02-00',10,20),
    point('10-03-00',0,0),point('10-04-00',0,0),point('10-20-00',30,40)];
const smoothed=evaluate("roomPhaseSmoothedPoints(roomPhaseSegments(noisyPoints, '2026-10-26')[0], 5)");
assert.equal(smoothed[2].error_k,2,'five-minute window suppresses minute-level deviation spikes');
assert.equal(smoothed[2].intensity_k,4,'both phase coordinates use the same temporal window');
assert.equal(smoothed[2].deviation_k,-2);
assert.equal(smoothed[0].intensity_k,0,'first actual position anchors the trajectory');
assert.equal(smoothed.at(-1).intensity_k,40,'current actual position anchors the trajectory');
assert.equal(smoothed[4].error_k,10/3,'a distant point across a gap never enters the smoothing window');
assert.equal(context.noisyPoints[2].intensity_k,20,'smoothing never mutates raw observations');
assert.deepEqual(smoothed.map(point=>point.timestamp),context.noisyPoints.map(point=>point.timestamp));
context.halfHourPoints=[point('09-44-00',100,100),point('09-45-00',0,0),point('10-00-00',30,60),
    point('10-15-00',0,0),point('10-16-00',100,100)];
const halfHour=evaluate("roomPhaseSmoothedPoints(roomPhaseSegments(halfHourPoints, '2026-10-26')[0])");
assert.equal(halfHour[2].error_k,10,'default rolling window includes precisely 15 minutes on either side');
assert.equal(halfHour[2].intensity_k,20);
assert.equal(halfHour[2].deviation_k,-10);
assert.equal(halfHour[0].intensity_k,100);
assert.equal(halfHour.at(-1).intensity_k,100);
markers.length=0;
curves.length=0;
context.data={'2026-10-26':{room_3_phase_points:{schema_version:1,offset_k:20,points:context.halfHourPoints}}};
vm.runInContext('drawRoomPhasePlot(data,setting)',context);
const startArrow=markers.find(node=>node.attrs.class==='room-phase-start-marker');
const position=startArrow.attrs.transform.match(/^translate\(([^,]+),([^\)]+)\)/).slice(1).map(Number);
assert.deepEqual(position,curves[0].rows[0],'start arrow lies at the first curve vertex');
assert.equal(startArrow.tag,'path');
const roomGroup=markers.find(node=>node.attrs.class==='room-phase-room');
const roomPath=markers.find(node=>node.attrs.class==='room-phase-trajectory');
const roomHalo=markers.find(node=>node.attrs.class==='room-phase-hover-halo');
const roomEnd=markers.find(node=>node.attrs.class==='room-phase-latest-point');
for (const event of ['mouseenter','mouseleave','focusin','focusout']) {
    // Simulate the event even if no emphasis handler is attached.
    roomGroup.events[event+'.phase-focus']?.();
    assert.equal(roomGroup.events[event+'.phase-focus'],undefined,'single-room views attach no emphasis handlers');
    assert.equal(roomGroup.attrs['data-emphasized'],'false');
    assert.equal(roomGroup.raises,0,'single-room stacking stays fixed');
    assert.equal(roomPath.attrs['stroke-width'],1.25);
    assert.equal(roomHalo.attrs.opacity,0);
    assert.equal(roomEnd.attrs.r,3,'single-room end marker never grows');
    assert.ok(!startArrow.attrs.transform.includes('scale('),'single-room start marker never grows');
}

markers.length=0;curves.length=0;tooltips.length=0;
context.hourlyData={'2026-10-26':{room_3_phase_points:{schema_version:1,offset_k:0,points:context.hourlyPoints}}};
vm.runInContext('drawRoomPhasePlot(hourlyData,setting)',context);
const hourlyArrows=markers.filter(node=>node.attrs.class==='room-phase-time-point');
assert.deepEqual(hourlyArrows.map(node=>node.attrs['data-timestamp'].slice(11)),['00-59-40','02-00-00','02-59-40']);
assert.ok(hourlyArrows.every(node=>node.tag==='path'&&node.attrs.fill==='black'&&node.attrs.transform.includes('rotate(')));
hourlyArrows.forEach(node=>{
    const index=context.hourlyPoints.findIndex(point=>point.timestamp===node.attrs['data-timestamp']);
    const pos=node.attrs.transform.match(/^translate\(([^,]+),([^\)]+)\)/).slice(1).map(Number);
    assert.deepEqual(pos,curves[0].rows[index],'hourly arrowheads lie on the smoothed curve, not the raw observations');
});
assert.ok(['00:59','02:00','02:59'].every(time=>tooltips.includes(time)));
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-start-marker').length,1);
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-latest-point').length,1);
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-direction').length,1);
draws.length=0;
vm.runInContext('drawRoomPhasePlot({},setting)',context);
assert.equal(draws.length,1);
assert.ok(draws[0].options.emptyMessage);
vm.runInContext("selectRoomAnalyticView('summary')",context);
assert.equal(context.mainGraphSetting.title,'room_control_diagnostic');
vm.runInContext("openRoomControlPlot(event,'PK')",context);
assert.equal(context.mainGraphSetting.title,'room_control_diagnostic','explicit room summary choice remains available and remembered');
vm.runInContext("selectRoomAnalyticView('phase'); openRoomControlPlot(event,'PK')",context);
assert.equal(context.mainGraphSetting.title,'room_control_phase','room analytics remembers its selected view');

vm.runInContext("openRoomControlPlot(event,'general_infobox'); selectRoomAnalyticView('phase'); navigateRoomControlDay(-1)",context);
assert.equal(context.mainGraphSetting.roomNumToPlot,null);
assert.equal(context.mainGraphSetting.cycleNum,null);
assert.equal(context.mainGraphSetting.day,'2026-10-26');
assert.deepEqual(evaluate('mainGraphSetting.types'),['room_1_phase_points','room_2_phase_points','room_3_phase_points']);
vm.runInContext('drawRoomControlView()',context);
assert.equal(loads.at(-1).requests.length,3);
assert.deepEqual(loads.at(-1).requests.map(request=>request.day),['2026-10-26','2026-10-26','2026-10-26']);
context.aggregateData={'2026-10-26':{room_1_phase_points:{schema_version:1,offset_k:20,points:context.points},
    room_3_phase_points:{schema_version:1,offset_k:0,points:context.halfHourPoints}}};
markers.length=0;curves.length=0;tooltips.length=0;
vm.runInContext('drawRoomPhasePlot(aggregateData,mainGraphSetting)',context);
const aggregatePaths=markers.filter(node=>node.attrs.class==='room-phase-trajectory');
assert.deepEqual(aggregatePaths.map(node=>node.attrs['data-room']),[1,3],'no curve is fabricated for a room without phase data');
assert.deepEqual(aggregatePaths.map(node=>node.attrs.stroke),['room-color-1','room-color-3']);
assert.equal(curves.length,2,'each room keeps a separate trajectory, never an average or joined inter-room path');
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-latest-point').length,2);
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-start-marker').length,2);
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-time-point').length,0);
assert.deepEqual(markers.filter(node=>node.attrs.class==='room-phase-latest-point').map(node=>node.attrs.fill),['room-color-1','room-color-3']);
const aggregateGroups=markers.filter(node=>node.attrs.class==='room-phase-room');
const aggregateStarts=markers.filter(node=>node.attrs.class==='room-phase-start-marker');
const aggregateEnds=markers.filter(node=>node.attrs.class==='room-phase-latest-point');
const aggregateState=markers.find(node=>node.attrs.class==='room-phase-state');
assert.equal(aggregateState,undefined,'multi-room plots have no movement state');
assert.equal(draws.at(-1).options.margins.top,.18,'aggregate heading does not reserve a state row');
aggregateGroups[0].events['mouseenter.phase-focus']();
assert.equal(aggregatePaths[0].attrs['stroke-width'],2.5);
assert.equal(aggregatePaths[1].attrs['stroke-width'],1.25,'hover affects only its own room');
assert.ok(aggregateStarts[0].attrs.transform.endsWith('scale(1.5)'));
assert.equal(aggregateEnds[0].attrs.r,6);
assert.equal(aggregateEnds[1].attrs.r,3);
aggregateGroups[0].events['mouseleave.phase-focus']();
aggregateGroups[1].events['focusin.phase-focus']();
aggregateGroups[1].events['focusout.phase-focus']();
assert.ok(!aggregateStarts[0].attrs.transform.includes('scale('));
assert.equal(aggregateEnds[0].attrs.r,3);
assert.equal(headings.at(-1).options.prefix,'szobák — ');
assert.ok(tooltips.some(label=>label.startsWith('Szita · ')));
assert.ok(tooltips.some(label=>label.startsWith('PK · ')));
assert.equal(draws.at(-1).options.domain.bottom[0],0);
vm.runInContext("openRoomControlPlot(event,'general_infobox')",context);
assert.equal(context.mainGraphSetting.title,'room_control_phase','main box remembers phase selection');
vm.runInContext("openRoomControlPlot(event,'cycle2_infobox')",context);
assert.equal(context.mainGraphSetting.title,'room_control_phase','cycle infobox analytics defaults to phase independently of the main box');
vm.runInContext("selectRoomAnalyticView('phase'); navigateRoomControlDay(-1)",context);
assert.equal(context.mainGraphSetting.cycleNum,2);
assert.deepEqual(evaluate('mainGraphSetting.types'),['room_2_phase_points','room_3_phase_points']);
vm.runInContext('drawRoomControlView()',context);
assert.deepEqual(loads.at(-1).requests.map(request=>request.type),['room_2_phase_points','room_3_phase_points']);
markers.length=0;
vm.runInContext('drawRoomPhasePlot(aggregateData,mainGraphSetting)',context);
assert.deepEqual(markers.filter(node=>node.attrs.class==='room-phase-trajectory').map(node=>node.attrs['data-room']),[3]);
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-time-point').length,0,'cycle plots remain free of intermittent markers');
assert.equal(markers.filter(node=>node.attrs.class==='room-phase-state').length,0,'cycle plots have no movement state');
assert.equal(headings.at(-1).options.prefix,'2. kör — ');
vm.runInContext("selectRoomAnalyticView('summary')",context);
assert.equal(context.mainGraphSetting.title,'room_control_daily');
assert.equal(context.mainGraphSetting.day,'2026-10-26');
assert.equal(context.mainGraphSetting.cycleNum,2);
assert.deepEqual(evaluate('mainGraphSetting.types'),['room_control_errors']);
const stalePhase=loads.at(-1),beforeStale=draws.length;
stalePhase.callback(context.aggregateData);
assert.equal(draws.length,beforeStale,'late phase responses cannot replace the selected daily view');
vm.runInContext("selectRoomAnalyticView('phase'); openRoomControlPlot(event,'cycle2_infobox')",context);
assert.equal(context.mainGraphSetting.title,'room_control_phase','cycle box remembers phase selection');
assert.deepEqual(evaluate("roomControlPlotRooms({cycleNum:1})"),[1]);
assert.deepEqual(evaluate("roomControlPlotRooms({cycleNum:2})"),[2,3]);
assert.deepEqual(evaluate("roomControlPlotRooms({cycleNum:3})"),[]);
assert.deepEqual(evaluate("roomControlPlotRooms({cycleNum:4})"),[]);
assert.equal(evaluate("createRoomControlPlotSetting('cycle1_infobox').title"),'room_control_phase');
assert.equal(evaluate("createRoomControlPlotSetting('cycle3_infobox').title"),'room_control_phase');
assert.equal(evaluate("createRoomControlPlotSetting('cycle4_infobox').title"),'room_control_phase');
assert.deepEqual(evaluate("roomAnalyticTabs({title:'room_control_phase',cycleNum:1}).choices.map(choice=>choice.label)"),['fázissík','napi hiba']);
context.fetchJSONEndpoint=()=>{throw new Error('Plot-only state must not fetch control config');};
vm.runInContext('drawRoomPhasePlot(data,setting)',context);
assert.equal(evaluate('typeof loadRoomPhaseHysteresis'),'undefined','plot band has no config-loading dependency');
console.log('Room phase views passed: fixed plot-only +/-1 K room band, diagnostic states and arrow-consistent motion, single-room-only text, hourly tooltips, unchanged aggregate/cycle markers, dates, smoothing and hover emphasis.');
