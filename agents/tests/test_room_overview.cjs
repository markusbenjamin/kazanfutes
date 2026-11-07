const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({});
vm.runInContext(fs.readFileSync('docs/room_overview.js','utf8'),context);
const run=source=>JSON.parse(JSON.stringify(vm.runInContext(source,context)));
assert.deepEqual(run(`averageOverviewTemperatures([
 [{h_of_day_frac:0,temp:20},{h_of_day_frac:1,temp:22},{h_of_day_frac:2,temp:24}],
 [{h_of_day_frac:0,temp:10},{h_of_day_frac:2,temp:14}]])`),[
 {h_of_day_frac:0,temp:15},{h_of_day_frac:1,temp:17},{h_of_day_frac:2,temp:19}]);
assert.deepEqual(run(`averageOverviewTemperatures([
 [{h_of_day_frac:0,temp:0},{h_of_day_frac:1,temp:NaN}],
 [{h_of_day_frac:0,temp:10},{h_of_day_frac:1,temp:12,live:true}]])`),[
 {h_of_day_frac:0,temp:5},{h_of_day_frac:1,temp:12,live:true}]);
assert.deepEqual(run(`averageOverviewTemperatures([
 [{h_of_day_frac:0,temp:20},{h_of_day_frac:4,temp:24}],
 [{h_of_day_frac:2,temp:10}]])`),[
 {h_of_day_frac:0,temp:20},{h_of_day_frac:2,temp:10},{h_of_day_frac:4,temp:24}]);
context.rooms={1:{name:'shared'},2:{name:'shared'},3:{name:'own'}};
context.data={room_1_measurements:[{h_of_day_frac:0,temp:20}],
 room_2_measurements:[{h_of_day_frac:0,temp:10}],room_3_measurements:[{h_of_day_frac:1,temp:30}]};
const grouped=run('roomOverviewGroups(data,[1,2,3],rooms,[1,2,3],rows=>rows)');
assert.equal(grouped.length,2);assert.equal(grouped[0].data[0].temp,15);
assert.deepEqual(grouped[0].roomIds,[1,2]);assert.equal(grouped[1].data[0].temp,30);
const cycle=run('roomOverviewGroups(data,[1,2,3],rooms,[2],rows=>rows)');
assert.equal(cycle[0].data[0].temp,10);assert.equal(cycle[0].colorRoom,1);
assert.equal(cycle[1].emphasis,false);
context.rooms[2].name='renamed';
assert.equal(run('roomOverviewGroups(data,[1,2,3],rooms,[1,2,3],rows=>rows)').length,3);
assert.equal(context.rooms[1].name,'shared');
console.log('Room overview: aligned equal-room averaging, missing/zero/gap handling, grouping, cycle isolation and renames passed.');
