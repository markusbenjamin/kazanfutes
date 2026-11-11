const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('docs/data.js','utf8');
const context=vm.createContext({console,Date,Number,Math,
    dateFromTimestamp:stamp=>new Date(stamp),
    d3:{mean:values=>values.reduce((sum,value)=>sum+value,0)/values.length}});
vm.runInContext(fs.readFileSync('docs/live_plot_data.js','utf8'),context);
const radiators=fs.readFileSync('docs/radiator_plots.js','utf8');
vm.runInContext(radiators.slice(radiators.indexOf('function radiatorFresh('),radiators.indexOf('function cyclePipingColor(')),context);
vm.runInContext(source.slice(source.indexOf('function infoboxRoomTemperature('),source.indexOf('function updateGeneralInfobox(')),context);
const run=source=>vm.runInContext(source,context);
run(`const system={switch:{cycles:{1:0,2:1,3:0,4:-1}},state:{pump_states:{1:1,2:0,3:1,4:0},
 heatmeters:{last_updated:new Date().toISOString(),1:{temp:60},2:{temp:20},3:{temp:40},4:{temp:30}},
 measured_temps:{1:20,2:22,3:null,4:99},sensor_last_updated:{1:livePlotStamp(new Date()),2:livePlotStamp(new Date()),3:livePlotStamp(new Date()),4:'2000-01-01-00-00-00'}}};`);
assert.equal(run('infoboxCirculatedWaterTemperature(system)'),50,'Only circulating circuits contribute while pumps run');
run('system.state.pump_states[1]=0; system.state.pump_states[3]=0;');
assert.equal(run('infoboxCirculatedWaterTemperature(system)'),40,'Standby uses enabled circuit roots, including automatic and manual-on');
run('system.switch.cycles[2]=-1;');
assert.equal(run('infoboxCirculatedWaterTemperature(system)'),50,'Disabled circuits do not enter the standby average');
run('system.switch.cycles[2]=1;');
run('system.state.heatmeters[2].temp=null;');
assert.equal(run('infoboxCirculatedWaterTemperature(system)'),50,'Missing enabled roots are omitted');
run('system.state.pump_states[2]=1;');
assert.equal(run('infoboxCirculatedWaterTemperature(system)'),null,'A missing running-circuit reading must not use idle circuits');
assert.equal(run('infoboxRoomTemperature(system,[1,2,3,4])'),21,'Stale and missing room readings do not skew the average');
assert.equal(run('infoboxRoomTemperature(system,[3,4])'),null);
run('system.state.pump_states[2]=0; system.switch.cycles={1:-1,2:-1,3:-1,4:-1};');
assert.equal(run('infoboxCirculatedWaterTemperature(system)'),null,'No enabled circuits means no standby average');
run('system.switch.cycles={1:0};');
assert.equal(run('infoboxCirculatedWaterTemperature(system)'),60,'Absent switch states do not enter the standby average');
run('system.state.heatmeters.last_updated="2000-01-01"; system.state.pump_states[2]=0;');
assert.equal(run('infoboxCirculatedWaterTemperature(system)'),null,'Old heatmeter snapshots are unavailable');
const lines=[];
context.isMobile=false;
context.getBBoxDrawingDimensions=()=>({w:58,h:100});
context.d3.selectAll=()=>({remove(){}});
context.addLineToBox=(id,message,x,y,font)=>{
    lines.push(message);return {style(){return this;},node(){return {getComputedTextLength:()=>message.length*font*.6};}};
};
vm.runInContext(source.slice(source.indexOf('function updateCycleInfobox('),source.indexOf('let dataWaitTime')),context);
run('updateCycleInfobox(1,{enabled:true,state:1,roomTemp:21.25,waterTemp:61.8,wantHeating:[]})');
assert.deepEqual(lines.slice(0,4).map(line=>line.trim()),['Kazán 1:','kering','Szobák: 21.3 °C','Fűtővíz: 62 °C']);
for (const [enabled,state,status] of [[true,0,'áll'],[false,0,'kör ki'],[false,1,'kör ki']]) {
    lines.length=0; context.statusInfo={enabled,state,wantHeating:[]};
    run('updateCycleInfobox(1,statusInfo)');
    assert.equal(lines[1].trim(),status,'Heating-switch disable takes precedence over pump state');
}
context.d3.select=()=>({style(){return this;}});
Object.assign(context,{getFractionalHourOfDay:()=>12,hourStamp:()=>'12:00',externalTemp:10,
    currentGasUsageRate:null,currentGasTotal:null,isValidNumber:Number.isFinite});
vm.runInContext(source.slice(source.indexOf('function updateGeneralInfobox('),source.indexOf('function updateCycleInfobox(')),context);
run(`const info={heatingOn:1,cyclesOn:[1,2,3,4],waterTemp:52,lastRequest:{granularity:'órája',timeSince:99},
 scheduleLastUpdated:new Date(),lastControlRun:{timeSince:0,granularity:'másodperce'},error:{error:false}};`);
lines.length=0;
run('updateGeneralInfobox(info)');
assert.ok(lines.includes('Keringetett fűtővíz: 52 °C.'));
assert.ok(lines.includes('Keringetett körök: mind.'));
lines.length=0;
run('info.cyclesOn=[];updateGeneralInfobox(info)');
assert.ok(lines.includes('Készenléti fűtővíz: 52 °C.'));
console.log('Infobox temperatures: running/standby selection, sensor freshness, room averaging, cycle rows and sentence punctuation passed.');
