const assert = require('node:assert/strict');
const vm = require('node:vm');
const createContext = require('./dashboard_test_context.cjs');
const now = new Date(2026,10,3,12,0,0), day='2026-11-03', stamp=day+'-11-59-30';
const context = createContext({Date, Number, Object, Math, now});
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code,context)));
context.setting={title:'all_rooms',day,types:['room_1_measurements','room_1_valve_state','heating_state']};
context.payload={[day]:{room_1_measurements:[{timestamp:day+'-11-55-00',h_of_day_frac:11+55/60,temp:19,hum:40}],
    room_1_valve_state:[{h_of_day_frac:11,valve:.2}]}};
context.system={setup:{rooms:{1:{thermostats:'a;b'}}},state:{last_updated:stamp,
    measured_temps:{1:20.5},sensor_last_updated:{1:day+'-11-30-00'}, measured_humidity:{1:50},humidity_last_updated:{1:stamp},
    valve_states:{1:[0,60]},pump_states:{1:1,2:0,3:0,4:0}}};
const original=JSON.stringify(context.payload);
let result=evaluate('withLivePlotReadings(payload,setting,system,now)');
assert.equal(result[day].room_1_measurements.at(-1).temp,20.5);
assert.equal(result[day].room_1_measurements.at(-1).hum,50);
assert.equal(result[day].room_1_measurements.at(-1).h_of_day_frac,12);
assert.equal(result[day].room_1_measurements.at(-1).live,true);
assert.equal(result[day].room_1_valve_state.at(-1).valve,.3);
assert.equal(JSON.stringify(context.payload),original,'cached history is never mutated');
assert.equal(evaluate('withLivePlotReadings(payload,setting,system,now)')[day].room_1_measurements.length,2,'repeated refresh does not accumulate endpoints');
for (const value of [null, '0', false, NaN, Infinity]) {
    context.system.state.measured_temps[1]=value;
    const row=evaluate('withLivePlotReadings(payload,setting,system,now)')[day].room_1_measurements.at(-1);
    assert.equal(row.temp,undefined,'null/malformed temperatures are never coerced to zero');
}
context.system.state.measured_temps[1]=20.5;
for (const observed of ['bad',day+'-09-00-00',day+'-12-05-00']) {
    context.system.state.sensor_last_updated[1]=observed;
    assert.equal(evaluate('withLivePlotReadings(payload,setting,system,now)')[day].room_1_measurements.at(-1).temp,undefined,'stale/bad/future sensor data is not appended');
}
context.system.state.sensor_last_updated[1]=stamp;
context.system.state.last_updated=day+'-11-00-00';
assert.deepEqual(evaluate('withLivePlotReadings(payload,setting,system,now)'),context.payload,'fresh sensor metadata cannot rescue an obsolete controller snapshot');
context.system.state.last_updated=stamp;
context.setting.day='2026-11-02';
assert.deepEqual(evaluate('withLivePlotReadings(payload,setting,system,now)'),context.payload,'no live values on historical days');
context.setting.day=day;context.setting.title='room_control_phase';
assert.deepEqual(evaluate('withLivePlotReadings(payload,setting,system,now)'),context.payload,'analytics stays on logged history');
context.setting.title='room_metrics';context.system.state.measured_temps[1]=0;
assert.equal(evaluate('withLivePlotReadings(payload,setting,system,now)')[day].room_1_measurements.at(-1).temp,0,'a genuinely fresh numerical zero stays valid');
context.system.state.last_updated=day+'-12-00-00';
context.payload[day].room_1_measurements.push({timestamp:day+'-12-01-00',h_of_day_frac:12+1/60,temp:22});
assert.deepEqual(evaluate('withLivePlotReadings(payload,setting,system,now)')[day].room_1_measurements,
    context.payload[day].room_1_measurements,'no out-of-order endpoint');

context.payload={[day]:{cycle_1_heat_delivery:[{h_of_day_frac:11,power_kw:10,flow_m3h:.5}],
    cycle_1_water_temps:[{h_of_day_frac:11,water_temp:58,return_temp:38}],
    pumps_power:[{h_of_day_frac:11,pump_1_power:30}]}};
context.setting={title:'cycle_water_temp',day,types:['cycle_1_heat_delivery','cycle_1_water_temps','pumps_power']};
context.system.state.heatmeters={last_updated:stamp,1:{temp:60,return_temp:40,flow:.5,power:11.63}};
context.system.state.pumps={last_updated:stamp,power:{1:0}};
result=evaluate('withLivePlotReadings(payload,setting,system,now)')[day];
assert.equal(result.cycle_1_heat_delivery.at(-1).power_kw,11.63);
assert.equal(result.cycle_1_water_temps.at(-1).return_temp,40);
assert.equal(result.pumps_power.at(-1).pump_1_power,0);
context.system.state.heatmeters[1].power=33391;
result=evaluate('withLivePlotReadings(payload,setting,system,now)')[day];
assert.equal(result.cycle_1_heat_delivery.at(-1).power_kw,undefined,'live power cannot bypass the formatter cross-check');
context.system.state.heatmeters[1].return_temp=undefined;
assert.equal(evaluate('withLivePlotReadings(payload,setting,system,now)')[day].cycle_1_heat_delivery.at(-1).power_kw,undefined);
context.system.state.heatmeters[1].power=0;
assert.equal(evaluate('withLivePlotReadings(payload,setting,system,now)')[day].cycle_1_heat_delivery.at(-1).power_kw,0);
context.setting={title:'weather_metrics',day,metric:'temperature',types:['weather_station','external_temp']};
context.payload={[day]:{weather_station:[{h_of_day_frac:11,temperature_c:-1,humidity_pct:80}],
    external_temp:[{h_of_day_frac:11,external_temp:-1}]}};
context.system.state.weather_station={timestamp:stamp,temperature_c:-2,humidity_pct:85};
assert.equal(evaluate('withLivePlotReadings(payload,setting,system,now)')[day].external_temp.at(-1).external_temp,-2);
context.setting.metric='direction';
assert.deepEqual(evaluate('withLivePlotReadings(payload,setting,system,now)'),context.payload,'wind histogram must not count a synthetic observation');
context.setting.metric='rain';
assert.deepEqual(evaluate('withLivePlotReadings(payload,setting,system,now)'),context.payload,'rain accumulation/differentiation stays on actual observations');
context.setting={title:'radiator',day,types:['radiator_temps','radiator_valves','boiler_1_plug_power']};
context.payload={[day]:{radiator_temps:[{h_of_day_frac:11,probes:{'shelly/100':50,'shelly/101':45}}],
    radiator_valves:[{h_of_day_frac:11,valves:{a:20,b:40}}],boiler_1_plug_power:[{h_of_day_frac:11,power_w:40}]}};
context.system.state.radiator_probes={timestamp:stamp,devices:{shelly:{100:55,101:null}}};
context.system.state.radiator_valves={timestamp:stamp,valves:{a:0,b:50}};
context.system.state.boiler_plugs={boiler_1_plug:{timestamp:stamp,reachable:true,power_w:0}};
result=evaluate('withLivePlotReadings(payload,setting,system,now)')[day];
assert.deepEqual(result.radiator_temps.at(-1).probes,{'shelly/100':55,'shelly/101':null});
assert.equal(result.radiator_valves.at(-1).valves.a,0);
assert.equal(result.boiler_1_plug_power.at(-1).power_w,0);
context.system.state.boiler_plugs.boiler_1_plug.reachable=false;
assert.equal(evaluate('withLivePlotReadings(payload,setting,system,now)')[day].boiler_1_plug_power.length,1);
assert.equal(evaluate("livePlotDate('2026-02-31-12-00-00')"),null);

// Firebase may arrive before the history request. It must not create a lone dot,
// a new channel, or a derived mean from otherwise-unloaded source curves.
const history={
    room_1_measurements:[{h_of_day_frac:11,temp:19,hum:40}],
    room_1_valve_state:[{h_of_day_frac:11,valve:0}],
    heating_state:[{h_of_day_frac:11,cycle_states:{1:1,2:0,3:0,4:0}}],
    cycle_1_water_temps:[{h_of_day_frac:11,water_temp:58,return_temp:38}],
    cycle_1_heat_delivery:[{h_of_day_frac:11,power_kw:10,flow_m3h:.5}],
    pumps_power:[{h_of_day_frac:11,pump_1_power:0}],
    radiator_temps:[{h_of_day_frac:11,probes:{'shelly/100':50,'shelly/101':null}}],
    radiator_valves:[{h_of_day_frac:11,valves:{a:0}}],
    boiler_1_plug_power:[{h_of_day_frac:11,power_w:0}],
    weather_station:[{h_of_day_frac:11,temperature_c:-1,humidity_pct:null}],
    external_temp:[{h_of_day_frac:11,external_temp:-1}]
};
context.setting={title:'room_plot',day,types:Object.keys(history)};
context.system={setup:{rooms:{1:{thermostats:'a;b'}}},state:{last_updated:stamp,
    measured_temps:{1:20},measured_humidity:{1:50},sensor_last_updated:{1:stamp},humidity_last_updated:{1:stamp},
    pump_states:{1:1,2:0,3:0,4:0},heatmeters:{last_updated:stamp,1:{temp:60,return_temp:40,flow:.5,power:11.63}},
    pumps:{last_updated:stamp,power:{1:0,2:30}},radiator_probes:{timestamp:stamp,devices:{shelly:{100:55,101:56}}},
    radiator_valves:{timestamp:stamp,valves:{a:0,b:50}},
    boiler_plugs:{boiler_1_plug:{timestamp:stamp,reachable:true,power_w:0}},
    weather_station:{timestamp:stamp,temperature_c:-2,humidity_pct:85}}};
context.payload={[day]:{}};
assert.deepEqual(evaluate('withLivePlotReadings(payload,setting,system,now)'),context.payload,'unloaded requests stay empty until history arrives');
for (const [type,rows] of Object.entries(history)) {
    for (const unavailable of [undefined,[],[null],[{}],[{h_of_day_frac:11}],rows.map(row=>({...row,live:true}))]) {
        context.payload={[day]:{...history}};
        if (unavailable===undefined) delete context.payload[day][type];
        else context.payload[day][type]=unavailable;
        const actual=evaluate('withLivePlotReadings(payload,setting,system,now)')[day][type];
        assert.equal(actual?.length,unavailable?.length,type+': absent/empty/invalid/synthetic history cannot enable an endpoint');
    }
}
context.payload={[day]:history};
result=evaluate('withLivePlotReadings(payload,setting,system,now)')[day];
for(const type of Object.keys(history)) {
    assert.equal(result[type].length,2,type+': history arriving enables the fresh endpoint');
    assert.equal(result[type].at(-1).live,true);
}
assert.equal(result.pumps_power.at(-1).pump_2_power,undefined,'one pump curve does not enable another');
assert.equal(result.radiator_temps.at(-1).probes['shelly/101'],undefined,'one probe curve does not enable another');
assert.equal(result.radiator_valves.at(-1).valves.b,undefined,'one TRV curve does not enable another');
assert.equal(result.weather_station.at(-1).humidity_pct,undefined,'temperature history does not enable a humidity dot');
context.payload[day].cycle_1_water_temps=[{h_of_day_frac:11,water_temp:58,return_temp:null}];
context.payload[day].room_1_measurements=[{h_of_day_frac:11,temp:19}];
result=evaluate('withLivePlotReadings(payload,setting,system,now)')[day];
assert.equal(result.cycle_1_water_temps.at(-1).return_temp,undefined,'supply-only history does not enable a return dot');
assert.equal(result.room_1_measurements.at(-1).hum,undefined,'room-temperature history does not enable a humidity dot');
console.log('Live endpoints passed: sensor/controller freshness, null/zero, historical/analytic isolation, cache safety, source ordering, heat validation, weather, probes, valves and plugs.');
