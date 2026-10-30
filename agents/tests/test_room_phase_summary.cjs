const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const nodes=[],draws=[],tooltips=[],headings=[],loads=[],requests=[];
function selection(){return {attrs:{},styles:{},events:{},append(tag){const child=selection();child.tag=tag;nodes.push(child);return child;},
    attr(key,value){this.attrs[key]=value;return this;},style(key,value){this.styles[key]=value;return this;},
    text(value){this.value=value;return this;},on(key,value){this.events[key]=value;return this;}};}
function scale(){let domain=[0,1],range=[0,1];const f=value=>range[0]+(value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
    f.domain=value=>(domain=value,f);f.range=value=>(range=value,f);return f;}
const context=vm.createContext({Number,Math,Date,Object,Array,Map,isMobile:false,mobileViewScaler:1.8,
    dashboardFont:'Consolas',dayStamp:()=> '2026-10-30',getFractionalHourOfDay:()=>12,
    mainGraphSetting:{},mainGraphContentLocked:false,allControlledRooms:[1],roomsDataAndState:{1:{name:'Szita',cycle:1}},
    elementToMainGraphSettingMapping:{Oktopusz:{title:'room_plot',roomNumToPlot:1}},
    clearMainGraphs(){},drawMainGraph:data=>requests.push(data),
    drawPlot:(rows,options)=>{draws.push({rows,options});return{plotElement:selection(),plotDims:{w:200,h:120}};},
    collectDataFromGitHub:(requests,callback)=>loads.push({requests,callback}),
    bindPlotCurveTooltip:(node,label)=>tooltips.push(label),d3:{scaleLinear:scale}});
for(const file of ['cycle_heat_plots','room_metric_plots','room_control_plots','room_phase_plots','room_phase_summary'])
    vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../docs/'+file+'.js'),'utf8'),context);
context.drawPlotTitleSelector=(node,dims,options,font)=>headings.push({node,dims,options,font});
context.bindPlotCurveTooltip=(node,label)=>tooltips.push(label);
const evaluate=code=>JSON.parse(JSON.stringify(vm.runInContext(code,context)));
const point=(time,error,intensity,source='measured',day='2026-10-29')=>({timestamp:day+'-'+time,error_k:error,intensity_k:intensity,source});
const setting={title:'room_control_diagnostic',roomNumToPlot:1,day:'2026-10-30',windowDays:7,presenceMode:'all',
    types:['room_1_phase_points','room_1_environment']};
context.setting=setting;
assert.equal(evaluate("createRoomControlPlotSetting('Oktopusz').presenceMode"),'occupied','new rooms start on presence');
assert.deepEqual(evaluate('roomPhaseSummaryDays(setting)'),['2026-10-24','2026-10-25','2026-10-26','2026-10-27','2026-10-28','2026-10-29','2026-10-30']);
context.data={'2026-10-29':{room_1_phase_points:{schema_version:1,offset_k:0,points:[
    point('10-00-00',2,0),point('10-01-00',0,2),point('10-03-00',-2,16),point('10-04-00',-2,16)]}}};
const original=JSON.stringify(context.data);
let result=evaluate('roomPhaseSummaryData(data,setting)');
assert.equal(result.seconds,240);
assert.deepEqual(result.states,{cold:60,good:120,warm:60});
assert.equal(result.observedDays,1);
assert.deepEqual(result.cells.map(cell=>cell.percent),[25,50,25],'duration, not point counts, sets the percentages');
assert.deepEqual(result.cells.map(({x1,x2,y1,y2})=>({x1,x2,y1,y2})),[
    {x1:0,x2:2,y1:-2,y2:-1.5},{x1:2,x2:4,y1:0,y2:.5},{x1:16,x2:18,y1:2,y2:2.5}]);
vm.runInContext('drawRoomControlView(data)',Object.assign(context,{mainGraphSetting:setting}));
assert.equal(draws.length,1,'summary is one heatmap, with no trajectories or interpolated samples');
assert.equal(headings[0].options.selected,'summary');
assert.equal(headings.length,2,'analytics tabs and a compact occupancy selector');
assert.equal(headings[1].options.selected,'all');
assert.deepEqual(Array.from(headings[1].options.choices,choice=>choice.label),['jelenlét','üres','össz']);
assert.equal(draws[0].options.margins.top,.18);
assert.equal(draws[0].options.axesLabel.bottom,'radiátor - szoba hőmérséklet (K)');
assert.ok(nodes.every(node=>!String(node.value).includes('hideg')&&!String(node.value).includes('h adat')&&!String(node.value).includes('2026-10-24')),'state percentages and date-range text are removed');
assert.equal(nodes.filter(node=>node.attrs.class==='room-phase-summary-cell').length,3);
assert.equal(nodes.filter(node=>node.attrs.class==='room-phase-summary-guide').length,5);
assert.ok(nodes.filter(node=>node.attrs.class==='room-phase-summary-cell').every(node=>node.attrs.width>0&&node.attrs.height>0&&node.attrs.stroke==='none'));
assert.ok(tooltips.some(label=>label.includes('0,03 h · 50%')));
assert.equal(JSON.stringify(context.data),original,'cached payloads are never mutated');
// Same values with a higher sampling frequency must have the same dwell statistics.
context.data['2026-10-29'].room_1_phase_points.points.splice(2,0,point('10-02-00',0,2));
assert.deepEqual(evaluate('roomPhaseSummaryData(data,setting).states'),result.states);
// Presence is intersected in time, including changes between phase observations.
context.data['2026-10-29'].room_1_environment=[{h_of_day_frac:10+30/3600,occupancy:1},{h_of_day_frac:10+2/60,occupancy:0}];
context.setting={...setting,presenceMode:'occupied'};
result=evaluate('roomPhaseSummaryData(data,setting)');
assert.equal(Math.round(result.seconds),90);
assert.equal(Math.round(result.states.cold),30);
assert.equal(Math.round(result.states.good),60);
assert.equal(result.states.warm,0);
assert.equal(evaluate('roomPhaseSummaryData(data,{...setting,presenceMode:undefined}).seconds'),90,'implicit mode also filters for presence');
nodes.length=0;
vm.runInContext('drawRoomPhaseSummary(data,setting)',context);
assert.equal(headings.at(-1).options.selected,'occupied');
assert.equal(nodes.filter(node=>node.attrs.class==='room-phase-summary-presence-outline').length,0,'no red occupancy outline remains');
assert.equal(nodes.filter(node=>node.attrs.class==='room-phase-summary-cell').length,2,'presence selector shows only eligible cells');
assert.equal(nodes.filter(node=>node.attrs.class==='room-phase-summary-cell').reduce((sum,node)=>sum+node.attrs['data-seconds'],0),90);
assert.equal(evaluate("roomPhaseSummaryData(data,{...setting,presenceMode:'empty'}).seconds"),120,
    'only explicitly observed absence counts; the unknown first 30 seconds do not');
context.data['2026-10-29'].room_1_environment=[{h_of_day_frac:10,occupancy:0},
    {h_of_day_frac:10+1/60,co2:600},{h_of_day_frac:10+2/60,occupancy:null}];
assert.equal(evaluate("roomPhaseSummaryData(data,{...setting,presenceMode:'empty'}).seconds"),120,
    'unknown ends absence, but unrelated metric readings do not');
context.data['2026-10-29'].room_1_environment=[{h_of_day_frac:9.5,occupancy:0}];
assert.equal(evaluate("roomPhaseSummaryData(data,{...setting,presenceMode:'empty'}).seconds"),0,'stale absence is not extended');
context.data['2026-10-29'].room_1_environment=[{h_of_day_frac:10,occupancy_average:1}];
assert.equal(evaluate('roomPhaseSummaryData(data,setting).seconds'),0,'learned/weekly occupancy is not observed presence');
assert.equal(evaluate("roomPhaseSummaryData(data,{...setting,presenceMode:'empty'}).seconds"),0,'learned occupancy is not absence either');
delete context.data['2026-10-29'].room_1_environment;
nodes.length=0;
vm.runInContext('drawRoomPhaseSummary(data,setting)',context);
assert.equal(draws.at(-1).options.emptyMessage,'Jelenlétkor nincs érvényes fázisadat.');
assert.equal(nodes.filter(node=>node.attrs.class==='room-phase-summary-cell').length,0,'unknown presence draws no invented occupied cells');
vm.runInContext("drawRoomPhaseSummary(data,{...setting,presenceMode:'empty'})",context);
assert.equal(draws.at(-1).options.emptyMessage,'Üresen nincs érvényes fázisadat.');
vm.runInContext("drawRoomPhaseSummary(data,{...setting,presenceMode:'all'})",context);
assert.equal(draws.at(-1).options.emptyMessage,'','all-time mode remains available without presence');
context.setting=setting;
// Unavailable records, long gaps, last samples and unknown sources never accumulate time.
context.data={'2026-10-29':{room_1_phase_points:{schema_version:1,offset_k:20,points:[
    point('09-00-00',2,-20),point('10-00-00',2,-20),point('10-01-00',0,-18),
    point('10-02-00',null,null,'unavailable'),point('10-03-00',-2,-4),point('10-04-00',-2,-4)]}}};
result=evaluate('roomPhaseSummaryData(data,setting)');
assert.equal(Math.round(result.seconds),120);
assert.deepEqual(result.states,{cold:60,good:0,warm:60});
assert.equal(result.cells[0].x1,0,'encoded X offset is removed before binning');
context.data['2026-10-29'].room_1_phase_points.points.push(point('10-04-00',null,null,'unavailable'));
assert.equal(Math.round(evaluate('roomPhaseSummaryData(data,setting).seconds')),60,'explicit missing duplicate wins over an older valid value');
context.data={'2026-10-30':{room_1_phase_points:{schema_version:1,points:[
    point('11-59-00',1,5,'estimated','2026-10-30'),point('12-00-00',-1,15,'estimated','2026-10-30'),
    point('12-01-00',-2,20,'measured','2026-10-30')]}}};
assert.equal(Math.round(evaluate('roomPhaseSummaryData(data,setting).seconds')),60,'today stops at now');
assert.equal(Math.round(evaluate('roomPhaseSummaryData(data,setting).states.good')),60,'band boundary is good');
context.data['2026-10-30'].room_1_phase_points.schema_version=99;
assert.equal(evaluate('roomPhaseSummaryData(data,setting).seconds'),0);
// Dynamics use time-weighted velocities on the same eligible intervals.
context.data={'2026-10-29':{room_1_phase_points:{schema_version:1,offset_k:0,points:
    Array.from({length:11},(_,i)=>point('10-'+String(i).padStart(2,'0')+'-00',.1+i*.01,.2+i*.1))}}};
result=evaluate('roomPhaseSummaryData(data,setting)');
assert.equal(result.arrows.length,1);
assert.ok(Math.abs(result.arrows[0].vx-6)<1e-8);
assert.ok(Math.abs(result.arrows[0].vy+.6)<1e-8,'increasing set-minus-measured points downwards');
assert.ok(Math.abs(result.arrows[0].coherence-1)<1e-8);
nodes.length=0;
vm.runInContext('drawRoomPhaseSummary(data,setting)',context);
const arrowNode=nodes.find(node=>node.attrs.class==='room-phase-summary-arrow');
assert.ok(arrowNode);
assert.ok(nodes.some(node=>node.tag==='path'&&node.attrs.stroke==='red'),'trial arrows are red');
assert.ok(Number(arrowNode.attrs.transform.match(/rotate\(([^)]+)\)/)[1])>0,'cooling deviation points down on the SVG');
assert.ok(tooltips.some(text=>text.includes('radiátor: 6 K/h')&&text.includes('eltérés: -0,6 K/h')));
const sparse=context.data['2026-10-29'].room_1_phase_points.points.filter((_,i)=>i%2===0);
context.data['2026-10-29'].room_1_phase_points.points=sparse;
const sparseArrow=evaluate('roomPhaseSummaryData(data,setting).arrows[0]');
assert.ok(Math.abs(sparseArrow.vx-result.arrows[0].vx)<1e-8,'sampling cadence does not change drift');
context.data['2026-10-29'].room_1_environment=[{h_of_day_frac:10,occupancy:1},{h_of_day_frac:10+5/60,occupancy:0}];
assert.equal(evaluate("roomPhaseSummaryData(data,{...setting,presenceMode:'occupied'}).arrows[0].seconds"),300);
assert.equal(evaluate("roomPhaseSummaryData(data,{...setting,presenceMode:'empty'}).arrows[0].seconds"),300);
delete context.data['2026-10-29'].room_1_environment;
assert.deepEqual(evaluate("roomPhaseSummaryData(data,{...setting,presenceMode:'occupied'}).arrows"),[]);
context.data['2026-10-29'].room_1_phase_points.points=Array.from({length:11},(_,i)=>
    point('10-'+String(i).padStart(2,'0')+'-00',.2,i%2 ? .5 : .2));
assert.deepEqual(evaluate('roomPhaseSummaryData(data,setting).arrows'),[],'opposing drifts cancel');
context.data['2026-10-29'].room_1_phase_points.points=Array.from({length:11},(_,i)=>
    point('10-'+String(i).padStart(2,'0')+'-00',.2,.2));
assert.deepEqual(evaluate('roomPhaseSummaryData(data,setting).arrows'),[],'stationary cells have no arbitrary arrow');
context.data['2026-10-29'].room_1_phase_points.points=Array.from({length:11},(_,i)=>
    point('10-'+String(i).padStart(2,'0')+'-00',.1+i*.01,.2+i*.1,i%2?'estimated':'measured'));
assert.deepEqual(evaluate('roomPhaseSummaryData(data,setting).arrows'),[],'fallback transitions do not invent motion');
context.data['2026-10-29'].room_1_phase_points.points=[point('10-00-00',.1,.2),point('10-10-00',.2,1.2)];
assert.deepEqual(evaluate('roomPhaseSummaryData(data,setting).arrows'),[],'no drift across a logging gap');
// Calendar windows, stream selection and stale async response isolation.
context.mainGraphSetting=setting;
vm.runInContext('drawRoomControlView()',context);
assert.equal(loads.at(-1).requests.length,14);
assert.ok(loads.at(-1).requests.every(request=>['room_1_phase_points','room_1_environment'].includes(request.type)));
vm.runInContext("selectRoomPhaseSummaryPresence('occupied')",context);
assert.notEqual(context.mainGraphSetting,setting);
assert.equal(context.mainGraphSetting.presenceMode,'occupied');
assert.equal(context.mainGraphSetting.day,'2026-10-30');
vm.runInContext('navigateRoomControlDay(-1)',context);
assert.equal(context.mainGraphSetting.day,'2026-10-29');
assert.deepEqual(evaluate('mainGraphSetting.types'),['room_1_phase_points','room_1_environment']);
const before=draws.length;
loads.at(-1).callback({});
assert.equal(draws.length,before,'late response cannot overwrite a different date');
vm.runInContext('drawRoomControlView()',context);
assert.equal(loads.at(-1).requests.length,14);
vm.runInContext("selectRoomAnalyticView('phase');selectRoomAnalyticView('summary')",context);
assert.equal(context.mainGraphSetting.day,'2026-10-29');
const reopened=evaluate("createRoomControlPlotSetting('Oktopusz')");
assert.equal(reopened.presenceMode,'occupied','presence choice is remembered for the room');
assert.equal(reopened.title,'room_control_diagnostic');
assert.equal(reopened.types.length,2);
assert.equal(evaluate('typeof roomPhaseSummaryOutline'),'undefined');
context.mainGraphSetting=reopened;
headings[1].options.onSelect('empty');
assert.equal(context.mainGraphSetting.presenceMode,'empty');
vm.runInContext("selectRoomPhaseSummaryPresence('all')",context);
assert.equal(context.mainGraphSetting.presenceMode,'all');
const beforeInvalid=context.mainGraphSetting;
vm.runInContext("selectRoomPhaseSummaryPresence('invalid')",context);
assert.equal(context.mainGraphSetting,beforeInvalid);
context.mainGraphSetting={title:'room_control_daily'};
const unchanged=context.mainGraphSetting;
vm.runInContext("selectRoomPhaseSummaryPresence('empty')",context);
assert.equal(context.mainGraphSetting,unchanged,'presence selector cannot alter an aggregate view');
console.log('Room phase summary passed: three-way occupancy selector, explicit absence only, seven calendar days, duration-weighted bins, missing-data breaks, offsets and stale-response isolation.');
