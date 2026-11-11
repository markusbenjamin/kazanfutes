const assert = require('node:assert/strict');
const vm = require('node:vm');
const createContext = require('./dashboard_test_context.cjs');
const context = createContext({URLSearchParams, window:{location:{search:''}}});
const evaluate = code => JSON.parse(JSON.stringify(vm.runInContext(code,context)));
const t = value => {context.value=value;return vm.runInContext('dashboardText(value)',context);};
assert.deepEqual(evaluate('dashboardPageOptions()'),{language:'hu',demo:false});
assert.equal(t('fázissík'),'fázissík');
assert.equal(t('Átlagos eltérés: +1,5 K.'),'Átlagos eltérés: +1,5 K.');
for (const search of ['?lang=en','?zoom=0.8&lang=en&demo=1']) {
    context.window.location.search=search;
    assert.equal(t('fázissík'),'phase plane');
    assert.equal(t('radiátor - szoba hőmérséklet (K)'),'radiator - room temperature (K)');
    assert.equal(t('Átlagos eltérés: +1,5 K.'),'Mean deviation: +1.5 K.');
    assert.equal(t('be, 50°C'),'on, 50°C');
    assert.equal(t('ki, 20°C'),'off, 20°C');
    assert.equal(t('Kazán 1:'),'Kazán 1:','proper circuit names are not boiler labels');
    assert.equal(t('Kazán 2:'),'Kazán 2:');
    assert.equal(t('1. kazán mai villamos teljesítménye'),"Boiler 1 today's electrical power",'actual boiler plots still translate');
    assert.equal(t('kazán — '),'boiler — ');
    assert.equal(t('2. kör — '),'Circuit 2 — ');
    for (const circuit of [1,2,3,4]) {
        const name = ['1-es','2-es','3-mas','4-es'][circuit-1] + ' kör';
        assert.equal(t(name + ' mai fűtőteljesítménye'),"today's heat output on circuit " + circuit);
        assert.equal(t(name + ' napi fűtőteljesítménye'),'daily heat output on circuit ' + circuit);
        assert.equal(t(name + ' — '),'Circuit ' + circuit + ' — ');
        assert.equal(t(name),'circuit ' + circuit);
        assert.equal(t(circuit + '. kör mai fűtőteljesítménye'),"today's heat output on circuit " + circuit);
        assert.equal(t(circuit + '. kör napi fűtőteljesítménye'),'daily heat output on circuit ' + circuit);
    }
    assert.equal(t('Mérce kért és mért hőmérséklet'),'Mérce set and measured temperature');
    assert.equal(t('PK mért hőmérséklet (+ elmúlt 3 nap átlaga)'),'PK measured temperature (+ past 3-day mean)');
    assert.equal(t('szobák mai hőmérsékleti görbéje a 3-mas körön'),"today's room temperatures — circuit 3");
    assert.equal(t('átlagos szerdai jelenlét (%)'),'average Wednesday occupancy (%)');
    assert.equal(t('2026-11-02 (hétfő)'),'2026-11-02 (Monday)');
    assert.equal(t('Vezérlés lefutott: 32  másodperce.'),'Last control run: 32 seconds ago.');
    assert.equal(t('Keringetett körök: mind.'),'Running circuits: all.');
    assert.equal(t('Keringetett fűtővíz: 52 °C.'),'Circulating water: 52 °C.');
    assert.equal(t('szoba jó de hűl, radiátor meleg és melegszik'),'room comfortable but cooling, radiator hot and warming');
    assert.equal(t('Mérce<br>Beállított felett.'),'Mérce<br>Above setpoint.');
    assert.equal(t('2026-11-02\nleadott: 80,0 kWh\ngázenergia: 94,4 kWh\n84,7%'),
        '2026-11-02\ndelivered: 80.0 kWh\ngas energy: 94.4 kWh\n84.7%');
    assert.equal(t('K'),'K','Kelvin is not the Hungarian east compass label');
    assert.equal(evaluate("dashboardCompassLabel('K')"),'E');
    assert.equal(t('Mérce'),'Mérce','proper room names remain unchanged');
    assert.equal(t('merce_radiator_1'),'merce_radiator_1','IDs remain unchanged');
    assert.equal(t(t('fázissík')),'phase plane','display translation is idempotent');
    assert.equal(t(0),0);
    assert.equal(t(null),null);
}
for (const search of ['?demo=1','?demo=true','?lang=en&demo=1&ref_source=form']) {
    context.window.location.search=search;
    assert.equal(evaluate('dashboardPageOptions().demo'),true);
}
for (const search of ['','?demo=0','?demo=false','?demo=','?other=demo%3D1','?lang=fr']) {
    context.window.location.search=search;
    assert.equal(evaluate('dashboardPageOptions().demo'),false);
    assert.equal(evaluate('dashboardPageOptions().language'),'hu');
}
context.payload={admin_message:'Magyar',admin_message_en:'English'};
assert.equal(evaluate('dashboardAdminMessage(payload)'),'Magyar');
context.window.location.search='?lang=en';
assert.equal(evaluate('dashboardAdminMessage(payload)'),'English');
delete context.payload.admin_message_en;
assert.equal(vm.runInContext('dashboardAdminMessage(payload)',context),undefined,'no silent Hungarian fallback in English mode');
console.log('Dashboard language passed: independent URL modes, display-only labels, weekdays, dynamic states, units, identity and localized admin fields.');
