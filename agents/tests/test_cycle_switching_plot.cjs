const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const calls=[],lines=[];
function selection(tag) {
    const node={tag,attrs:{},attr(key,value){this.attrs[key]=value;return this;},
        append(child){const next=selection(child);lines.push(next);return next;}};
    return node;
}
function scaleLinear() {
    let domain=[0,1],range=[0,1];
    const scale=value=>range[0]+(value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
    scale.domain=value=>(domain=value,scale);scale.range=value=>(range=value,scale);return scale;
}
const context=require('./dashboard_test_context.cjs')({Date,Number,Object,Math,isMobile:false,
    dayStamp:()=> '2026-11-18',d3:{scaleLinear},
    drawPlot:(rows,options)=>{calls.push({rows,options});return {plotElement:selection('g'),plotDims:{w:240,h:100}};}
});
vm.runInContext(fs.readFileSync('docs/cycle_heat_plots.js','utf8'),context);
const evaluate=code=>JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.setting={title:'heating_state',day:'2026-11-18',types:['heating_state']};
context.rows=[
    {h_of_day_frac:0,cycle_states:{1:0,2:0,3:0,4:0}},
    {h_of_day_frac:4,cycle_states:{1:1,2:0,3:0,4:0}},
    {h_of_day_frac:5.75,cycle_states:{1:1,2:1,3:1,4:0}},
    {h_of_day_frac:10.75,cycle_states:{1:1,2:1,3:1,4:0}}
];
context.now=new Date(2026,10,18,11,10,0);
context.system={state:{last_updated:'2026-11-18-11-09-30',pump_states:{1:1,2:1,3:1,4:0}}};
context.payload={'2026-11-18':{heating_state:context.rows}};
const original=JSON.stringify(context.rows);
context.live=evaluate("withLivePlotReadings(payload,setting,system,now)['2026-11-18'].heating_state");
vm.runInContext('drawCycleSwitchingPlot(live,setting)',context);
assert.equal(calls.length,1,'one common frame and date navigation');
const end=calls[0].options.now.pos;
assert.equal(end,11+10/60);
for(let cycle=1;cycle<=4;cycle++) {
    const bars=lines.filter(line=>line.attrs['data-cycle']===cycle);
    assert.equal(bars.at(-1).attrs['data-end'],end,'all states meet the current-time marker');
    assert.equal(bars.at(-1).attrs.x2,end*10);
    for(let index=1;index<bars.length;index++) {
        assert.equal(bars[index-1].attrs.x2,bars[index].attrs.x1,'state intervals meet exactly at switching edges');
    }
    assert.equal(bars.at(-1).attrs['data-state'],cycle===4?0:1);
}
assert.ok(lines.every(line=>line.attrs['stroke-linecap']==='butt'));
assert.ok(lines.filter(line=>line.attrs['data-state']===0).every(line=>line.attrs['stroke-width']===6));
assert.ok(lines.filter(line=>line.attrs['data-state']===1).every(line=>line.attrs['stroke-width']===8));
assert.equal(JSON.stringify(context.rows),original,'never modify the archive');
context.rows=[{h_of_day_frac:0,cycle_states:{1:0}},
    {h_of_day_frac:4,cycle_states:{1:1}},
    {h_of_day_frac:4.02,cycle_states:{1:0}},
    {h_of_day_frac:4.04,cycle_states:{1:1}}];
assert.deepEqual(evaluate('cycleSwitchingIntervals(rows,1,5)'),[
    {start:0,end:4,state:0},{start:4,end:4.02,state:1},
    {start:4.02,end:4.04,state:0},{start:4.04,end:5,state:1}
],'short off periods must not be bridged by joining equal-state samples');
context.rows=[{h_of_day_frac:-.1,cycle_states:{1:1}},
    {h_of_day_frac:1,cycle_states:{1:0}},
    {h_of_day_frac:1,cycle_states:{1:1}},
    {h_of_day_frac:2,cycle_states:{}},
    {h_of_day_frac:3,cycle_states:{1:0}}];
assert.deepEqual(evaluate('cycleSwitchingIntervals(rows,1,4)'),[
    {start:0,end:2,state:1},{start:3,end:4,state:0}
],'midnight context and duplicate ordering work; genuinely unknown states remain blank');
assert.deepEqual(evaluate('cycleSwitchingIntervals(rows.slice().reverse(),1,.5)'),[{start:0,end:.5,state:1}],
    'do not extend beyond the replay/data edge');
context.rows=[];calls.length=0;lines.length=0;
vm.runInContext('drawCycleSwitchingPlot(rows,setting)',context);
assert.equal(lines.length,0,'no state is invented for an empty day');
assert.equal(calls[0].options.now.pos,0);
const source=fs.readFileSync('docs/data.js','utf8');
const body=source.slice(source.indexOf('                case "heating_state":',source.indexOf('function drawMainGraph')),
    source.indexOf('                case "weather_metrics":',source.indexOf('function drawMainGraph')));
assert.match(body,/drawCycleSwitchingPlot\(graphData.heating_state, mainGraphSetting\)/);
assert.doesNotMatch(body,/segment.*gap/);
console.log('Circuit switching passed: upload gaps, Firebase extension, exact state edges, source immutability, midnight, unknown states, duplicates and replay boundaries.');
