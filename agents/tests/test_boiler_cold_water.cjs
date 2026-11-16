const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const styles={},flames=[];
const now=new Date('2026-11-15T12:00:00Z');
const context=vm.createContext({console,Date,Number,Math,dashboardNow:()=>now,
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
const warnings = state => {
    context.sample = {state};
    return JSON.parse(run('JSON.stringify(dashboardBoilerWarnings(sample))'));
};
for (const value of ['', ' \n ', null, undefined, false, {}])
    assert.equal(warnings({boiler_error:value}).boilerError,false);
assert.equal(warnings({boiler_error:'kazán hiba!'}).boilerError,true,'Use the published boiler diagnostic');
assert.equal(warnings({boiler_error:'',heatmeters:{1:{temp:20}}}).boilerError,false,'No frontend temperature-based fallback');
const rain={enabled:true,running:true,rain_shutdown:true,mode:'rain_shutdown',
    checked_at_epoch:now.getTime()/1000,fresh_for_seconds:180};
assert.deepEqual(warnings({rain_protection:rain}),{boilerError:false,rainProtection:true});
assert.deepEqual(warnings({boiler_error:'kazán hiba!',rain_protection:rain}),{boilerError:true,rainProtection:true});
for (const change of [{rain_shutdown:false},{enabled:false},{running:false,mode:'stopped'},
    {checked_at_epoch:rain.checked_at_epoch-181},{checked_at_epoch:rain.checked_at_epoch+31},
    {checked_at_epoch:null},{fresh_for_seconds:0},{fresh_for_seconds:'180'}])
    assert.equal(warnings({rain_protection:{...rain,...change}}).rainProtection,false,'Inactive, stopped or stale rain status is not a warning');
assert.equal(warnings({rain_protection:{...rain,checked_at_epoch:rain.checked_at_epoch-180}}).rainProtection,true,'Allow the published freshness boundary');
for (const value of [undefined,null,true,'normal',{}])
    assert.equal(warnings({rain_protection:value}).rainProtection,false,'The status object itself is not an activation flag');
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
    assert.equal(run('boilerWarningActive'),false,'Heating off is not itself a warning');
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
for (const [boilerError,rainProtection,label] of [[true,false,'kazán hiba!'],[false,true,'esővédelem!'],
    [true,true,'esővédelem!'],[false,false,'']]) {
    messages.length=0;
    context.info={heatingOn:0,boilerError,rainProtection};
    run('updateGeneralInfobox(info)');
    const shown=messages.filter(row=>['kazán hiba!','esővédelem!'].includes(row.text));
    assert.equal(shown.length,0,'Warnings are presented in the dismissible message box, not the infobox');
    if (label) {
        const count=flames.length;
        run('updateBoilerColor(1,info.boilerError||info.rainProtection,true);drawBoiler()');
        assert.equal(styles['#boiler_body'].stroke,'black','Either published warning makes the boiler black');
        assert.equal(flames.length,count);
        assert.ok(Math.abs(hands.at(-1)[4]-Math.PI*1.25)<1e-10);
    }
}
console.log('Published boiler/rain warnings: source fields, freshness, precedence, clearing, black appearance, empty flames, dial and heating-off recovery passed.');
