const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const styles={},flames=[];
const context=vm.createContext({console,Number,Math,
    cycleSupplyTemperature:(system,cycle)=>system[cycle],
    d3:{select:id=>({style(key,value){(styles[id]||={})[key]=value;return this;}})},
    currentGasUsageRate:0,aspectRatio:1,constrain:(v,min,max)=>Math.max(min,Math.min(max,v)),
    getBBoxP5jsDimensions:()=>({cx:0,cy:0,w:10,h:10}),mapSize:()=>({w:1,h:1}),
    random:()=>1,color:(...args)=>args,drawFlame:(...args)=>flames.push(args),isValidNumber:()=>false});
const source=fs.readFileSync('docs/data.js','utf8');
vm.runInContext(source.slice(source.indexOf('let boilerState ='),source.indexOf('let pastNDaysAverageRoomTemps')),context);
const draw=fs.readFileSync('docs/draw.js','utf8');
vm.runInContext(draw.slice(draw.indexOf('function drawBoiler('),draw.indexOf('function textOnArcUprightWeighted(')),context);
const run=source=>vm.runInContext(source,context);
const cold = (temperatures, switches = {1:0,2:1,3:0,4:0}) => {
    context.sample = {...temperatures,switch:{cycles:switches}};
    return run('boilerWaterTooCold(sample)');
};
assert.equal(cold({1:20,2:27.9,3:19,4:22}),true);
assert.equal(cold({1:20,2:28,3:19}),false,'28 °C is outside the below-threshold condition');
assert.equal(cold({1:20,2:60}),false,'The hottest enabled circuit determines the result');
assert.equal(cold({1:20,2:27,3:80},{1:0,2:1,3:-1,4:-1}),true,'Hot disabled circuits cannot suppress the warning');
assert.equal(cold({1:40,2:20},{1:0,2:-1,3:-1,4:-1}),false,'Cold disabled circuits do not count');
assert.equal(cold({1:20,2:24},{1:-1,2:-1,3:-1,4:-1}),false,'No enabled circuits means no cold-boiler inference');
assert.equal(cold({1:20},{}),false,'Missing switch states must not be guessed enabled');
assert.equal(cold({1:null,2:NaN,3:0}),false,'Unavailable or invalid readings cannot establish cold water');
run('updateBoilerColor(1,true); drawBoiler()');
assert.equal(styles['#boiler_body'].stroke,'black');
assert.equal(styles['#flame_nest'].fill,'rgba(0.2,0.2,0.2,1)');
assert.equal(styles['#flame_nest']['fill-opacity'],'1','The flame area remains visible without animated flames');
assert.equal(flames.length,0,'Cold-water condition suppresses every animated flame');
run('updateBoilerColor(0,true); drawBoiler()');
assert.equal(flames.length,0,'No blue pilot flames in the cold-water condition either');
run('updateBoilerColor(1,false); drawBoiler()');
assert.equal(styles['#boiler_body'].stroke,'rgba(255,0,0,1)');
assert.ok(flames.length>0,'Normal flames return when the water recovers');
assert.equal(styles['#flame_nest']['fill-opacity'],'1');
const hands=[];
Object.assign(context,{currentGasUsageRate:5,isValidNumber:Number.isFinite,
    PI:Math.PI,TWO_PI:Math.PI*2,sin:Math.sin,cos:Math.cos,getZoomLevel:()=>1,
    roundTo:(value,step)=>Math.round(value/step)*step,isFractional:value=>!Number.isInteger(value),
    drawIsoscelesTriangle:(...args)=>hands.push(args)});
for(const name of ['strokeWeight','stroke','line','fill','noStroke','noFill','ellipse']) context[name]=()=>{};
run('updateBoilerColor(1,true); drawBoiler()');
assert.ok(Math.abs(hands.at(-1)[4]-Math.PI*1.25)<1e-10,'The boiler gas dial points exactly to zero in the error state');
assert.equal(context.currentGasUsageRate,5,'The total measured gas usage remains untouched');
for (const pumpState of [0,1]) {
    const count=flames.length;
    run(`updateBoilerColor(${pumpState},false,false); drawBoiler()`);
    assert.equal(styles['#boiler_body'].stroke,'black','Main switch off takes precedence over circulation');
    assert.equal(styles['#flame_nest']['fill-opacity'],'1','The empty flame area remains visible');
    assert.equal(flames.length,count,'Switching heating off removes both active and pilot flames');
    assert.ok(Math.abs(hands.at(-1)[4]-Math.PI*1.25)<1e-10,'The dial points exactly to zero while heating is off');
    assert.equal(run('boilerColdWaterError'),false,'Heating off is not itself a boiler fault');
    assert.equal(context.currentGasUsageRate,5,'Other gas use remains measured');
}
const offFlames=flames.length;
run('updateBoilerColor(0,false,true); drawBoiler()');
assert.equal(styles['#boiler_body'].stroke,'rgba(0,0,255,1)','Enabled standby returns to blue');
assert.ok(flames.length>offFlames,'Enabled standby restores the pilot flames');
run('updateBoilerColor(1,false,true); drawBoiler()');
assert.equal(styles['#boiler_body'].stroke,'rgba(255,0,0,1)','Heating returns to its active red appearance');
const messages=[];
context.isMobile=false;
context.getBBoxDrawingDimensions=()=>({w:130,h:167});
context.d3.selectAll=()=>({remove(){}});
context.addLineToBox=(id,text,x,y,font)=>{
    const row={text,x,y,styles:{}};messages.push(row);
    return {style(key,value){row.styles[key]=value;return this;},classed(){return this;},
        node(){return {getComputedTextLength:()=>text.length*font*.6};}};
};
vm.runInContext(source.slice(source.indexOf('function updateGeneralInfobox('),source.indexOf('function updateCycleInfobox(')),context);
run('updateGeneralInfobox({heatingOn:0,boilerError:true})');
const warning=messages.find(row=>row.text==='kazán hiba!');
assert.equal(warning.styles.fill,'red');
assert.equal(warning.styles['font-weight'],'normal');
assert.equal(warning.y,messages[0].y,'The warning stays on the title row');
console.log('Cold boiler: enabled-circuit selection, 28 °C threshold, invalid readings, black outline, empty flame area and recovery passed.');
