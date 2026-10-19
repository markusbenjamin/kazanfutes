const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../docs/data.js'), 'utf8').replace(/\r\n/g, '\n');
const plotCase = source.match(/case "external_temp": \{([\s\S]*?)\n\s*break;\n\s*\}/)[1];
const plots = [];
const context = vm.createContext({
    Number, Math, graphData: {}, drawPlot: (rows, options) => plots.push({rows, options}),
    d3: { extent: values => [Math.min(...values), Math.max(...values)],
        range: (start, end, step) => Array.from({length: Math.ceil((end-start)/step)}, (_, i) => start+i*step) },
});
function plot(data) {
    plots.length = 0;
    context.graphData = data;
    vm.runInContext('{'+plotCase+'}', context);
    return plots[0];
}
for (const data of [{}, {external_temp: []}, {external_temp: [{external_temp: null}]}]) {
    const result = plot(data);
    assert.equal(result.rows.length, 0);
    assert.equal(result.options.curveEndText.show, false);
    assert.ok(result.options.domain.left.every(Number.isFinite));
}
const zero = plot({external_temp: [{external_temp: -1.5}, {external_temp: 0}]});
assert.equal(zero.rows.length, 2);
assert.equal(zero.options.curveEndText.text, '0°C');
const value = plot({external_temp: [{external_temp: 10.2}]});
assert.equal(value.options.curveEndText.text, '10.2°C');
const thermometer = fs.readFileSync(path.resolve(__dirname, '../../docs/draw.js'), 'utf8');
assert.match(thermometer, /function drawExternalThermometer\(\) \{\s*if \(Number\.isFinite\(externalTemp\)\)/);
assert.match(source, /externalTemp = Number\.isFinite\(systemJSON\.state\.external_temp\)/);
console.log('External temperature display/plot passed: WS90 Firebase contract, zero, negatives, empty data.');
