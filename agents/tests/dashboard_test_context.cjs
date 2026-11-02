// Production presentation helpers shared by the isolated dashboard test contexts.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../../docs/dashboard_i18n.js'), 'utf8');
module.exports = sandbox => {
    const context = vm.createContext({URLSearchParams, ...sandbox});
    vm.runInContext(source, context);
    return context;
};
