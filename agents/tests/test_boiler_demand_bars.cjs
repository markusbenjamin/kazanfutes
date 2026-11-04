const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const nodes=[], tooltips=[];
function selection() {return {attrs:{},append(tag){const item=selection();item.tag=tag;nodes.push(item);return item;},
    attr(key,value){this.attrs[key]=value;return this;},style(){return this;},text(value){this.textValue=value;return this;}};}
function scale(){let domain=[0,1],range=[0,1];const f=value=>range[0]+(value-domain[0])/(domain[1]-domain[0])*(range[1]-range[0]);
    f.domain=value=>(domain=value,f);f.range=value=>(range=value,f);f.nice=()=>f;return f;}
const context=require('./dashboard_test_context.cjs')({Number,Math,Map,Object,dashboardFont:'Consolas',
    d3:{scaleLinear:scale},bindPlotCurveTooltip:(node,text)=>tooltips.push(text)});
vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../docs/boiler_demand_bars.js'),'utf8'),context);
const evaluate=code=>JSON.parse(JSON.stringify(vm.runInContext(code,context)));
const row=(hour,total,values)=>({h_of_day_frac:hour,demand_kw:total,cycle_demand_kw:values&&Object.fromEntries(values.map((value,index)=>[index+1,value]))});
context.rows=[row(1,15,[10,5,0,0]),row(2,6,[10,-4,0,0]),row(3,0,[-4,1,0,0]),
    row(4,null,[1,1,1,1]),row(5,8),row(6,8,[1,1,0,0]),row(8,10,[10,0,0,0]),row(8,null,[10,0,0,0])];
const original=JSON.stringify(context.rows);
assert.deepEqual(evaluate('boilerDemandExtent(rows)'),[0,15]);
assert.equal(evaluate('boilerDemandStack(rows[1]).parts[1].start'),0);
assert.equal(evaluate('boilerDemandStack(rows[1]).parts[1].end'),-4);
assert.equal(evaluate('boilerDemandStack(rows[2]).positive'),1,'positive contributions are unchanged');
assert.equal(evaluate('boilerDemandStack(rows[5])'),null,'inconsistent breakdown must not be presented as a valid decomposition');
context.area={plotElement:selection(),plotDims:{w:240,h:100}};
vm.runInContext("drawBoilerDemandBars(area,rows,{color:'orange'},[0,20])",context);
const bars=nodes.filter(node=>node.attrs.class==='boiler-demand-bar');
assert.deepEqual(nodes.filter(node=>node.tag==='tspan').map(node=>node.textValue),
    ['1-es kör',' · 2-es kör',' · 3-mas kör',' · 4-es kör']);
assert.equal(bars.length,12,'negative components are omitted from three stacks; two fallback total bars remain');
assert.ok(bars.every(node=>Number.isFinite(node.attrs.height)&&node.attrs.height>=0&&node.attrs.width>0));
assert.ok(bars.every(node=>Math.abs(node.attrs.width-1.5)<1e-8&&node.attrs.stroke==='none'),'ten-minute bins have 10% gaps and no border');
assert.ok(bars.every(node=>node.attrs['data-value']>=0),'no negative demand bars are drawn');
assert.ok(bars.every(node=>node.attrs.y+node.attrs.height<=100+1e-8),'all bars stay above the zero baseline');
assert.equal(nodes.filter(node=>node.attrs.class==='boiler-demand-net').length,3);
assert.ok(!tooltips.some(text=>text.includes('-4 kW')),'hidden negative contributions have no tooltip');
assert.ok(tooltips.some(text=>text.includes('1-es kör: 10 kW')&&text.includes('hőigény: 6 kW')),
    'positive components and logged net demand retain their original values');
assert.equal(nodes.find(node=>node.attrs.class==='logged-power-end-label').textValue,'8 kW');
assert.equal(JSON.stringify(context.rows),original);
nodes.length=0;context.rows=[];
vm.runInContext("drawBoilerDemandBars(area,rows,{color:'orange'},[0,20])",context);
assert.equal(nodes.filter(node=>node.attrs.class==='boiler-demand-bar').length,0);
console.log('Boiler stacks passed: negative bars hidden, zero-based axis, unchanged net/positive contributions, null gaps, fallbacks, labels, tooltips and immutable history.');
context.rows=[row(1,0,[-10,0,0,0]),row(1+1/60,10,[10,0,0,0]),row(1+2/60,null)];
const clipped=evaluate('boilerDemandBins(rows)[0]');
assert.ok(Math.abs(clipped.demand_kw-5)<1e-8,'average logged clamped demand, not clamp of average contributions');
assert.ok(Math.abs(clipped.cycle_demand_kw[1])<1e-8);
context.rows=[row(1,10,[10,0,0,0]),row(1+1/60,20),row(1+2/60,null)];
assert.equal(evaluate('boilerDemandBins(rows)[0].cycle_demand_kw ?? null'),null,'partial breakdown cannot be stacked against full total coverage');
context.window={location:{search:'?lang=en'}};
nodes.length=0;tooltips.length=0;context.rows=[row(1,10,[10,0,0,0])];
vm.runInContext("drawBoilerDemandBars(area,rows,{color:'orange'},[0,20])",context);
assert.deepEqual(nodes.filter(node=>node.tag==='tspan').map(node=>node.textValue),['circuit 1',' · circuit 2',' · circuit 3',' · circuit 4']);
assert.ok(tooltips.some(text=>text.includes('circuit 1: 10 kW')));
