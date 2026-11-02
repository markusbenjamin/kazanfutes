// Help is independent of the polled admin message and never acknowledges it.
// Hungarian help is on hold; retain the content for re-enabling later.
const HUNGARIAN_DASHBOARD_HELP_ENABLED = false;
function dashboardHelpEnabled() {
    return dashboardPageOptions().language === 'en' || HUNGARIAN_DASHBOARD_HELP_ENABLED;
}
const demoHelpBox = document.getElementById('demo-help');
const demoHelpLauncher = document.getElementById('demo-help-launcher');
let demoHelpPreviousFocus;

function showDemoHelp() {
    if (!dashboardHelpEnabled()) return;
    demoHelpPreviousFocus = document.activeElement;
    demoHelpBox.hidden = false;
    demoHelpLauncher.setAttribute('aria-expanded','true');
    demoHelpBox.focus({preventScroll:true});
}

function hideDemoHelp() {
    const hadFocus = demoHelpBox.contains(document.activeElement);
    demoHelpBox.hidden = true;
    demoHelpLauncher.setAttribute('aria-expanded','false');
    if (hadFocus) (demoHelpPreviousFocus?.isConnected ? demoHelpPreviousFocus : demoHelpLauncher).focus({preventScroll:true});
}

function initializeDashboardPage() {
    const {language, demo} = dashboardPageOptions();
    document.documentElement.lang = language;
    document.title = dashboardText(document.title);
    ['admin-message','admin-message-close','demo-help','demo-help-close'].forEach(id => {
        const node = document.getElementById(id);
        node.setAttribute('aria-label',dashboardText(node.getAttribute('aria-label')));
    });
    document.querySelector('#admin-message a').textContent = dashboardText('Kérdésem van');
    demoHelpLauncher.textContent = dashboardText('mi ez?');
    demoHelpLauncher.hidden = !dashboardHelpEnabled();
    document.getElementById('dashboard-page-tools').setAttribute('aria-label',language === 'en' ? 'Language and help' : 'Nyelv és súgó');
    ['hu','en'].forEach(code => {
        const link = document.getElementById('dashboard-language-' + code);
        const url = new URL(window.location.href);
        url.searchParams.set('lang',code);
        link.setAttribute('href',url.href);
        link.setAttribute('aria-current',code === language ? 'true' : 'false');
        link.hidden = code === language;
    });
    const introduction = language === 'en' ? [
        'This dashboard is the live window into the Kazán–Gólya heating monitoring and control system. It brings room climate, occupancy, radiator and heating-circuit temperatures, weather, gas use and delivered heat together on one building map.',
        'By connecting room-by-room heating needs with measured operation, the system makes it possible to follow how the building responds, compare requested and measured temperatures, and examine heat delivery and energy use over time. It provides a practical basis for improving comfort and energy efficiency, and for evaluating changes against real operating data.'
    ] : [
        'Ez a dashboard a Kazán–Gólya fűtésfelügyeleti és szabályozási rendszerének élő nézete. Egyetlen épülettérképen kapcsolja össze a szobák klímáját és jelenléti adatait, a radiátorok és fűtési körök hőmérsékletét, az időjárást, a gázfogyasztást és a leadott hőt.',
        'A helyiségenkénti fűtési igény és a mért működés összekapcsolásával követhetővé válik az épület viselkedése, összevethető a kért és mért hőmérséklet, valamint időben vizsgálható a hőleadás és az energiafelhasználás. Ez gyakorlati alapot ad a komfort és az energiahatékonyság javításához, a változtatások pedig valós üzemi adatokon értékelhetők.'
    ];
    const paragraphs = language === 'en' ? [
        'Hover over a room, radiator, pipe, meter or thermometer to see its chart.',
        'Ctrl+click: detailed measurements. Alt+click: analytics, where available. Use the chart tabs to switch views.',
        'On touch screens, tap an element, then choose basic, details or analytics above the chart.',
        'Corner arrows change the day. Click empty space to unpin. Scroll/pinch to zoom; drag to pan.',
        'Live data. Close with Ok or ×; reopen with help at the top right.'
    ] : [
        'Vidd a kurzort egy szoba, radiátor, cső, mérő vagy hőmérő fölé a grafikonhoz.',
        'Ctrl+kattintás: részletes mérések. Alt+kattintás: analitika, ahol elérhető. A grafikon felirataival válthatsz nézetet.',
        'Érintőképernyőn koppints egy elemre, majd válaszd az alap, részletes vagy analitika nézetet a grafikon felett.',
        'A saroknyilakkal napot válthatsz. Üres részre kattintva feloldhatod a rögzítést. Görgetés/csippentés: nagyítás; húzás: mozgatás.',
        'Élő adatok. Az Ok vagy × bezárja a dobozt; a jobb felső „mi ez?” gombbal újra megnyithatod.'
    ];
    const content = document.getElementById('demo-help-content');
    introduction.forEach(text => {const p=document.createElement('p');p.textContent=text;content.append(p);});
    const heading = document.createElement('h3');
    heading.textContent = dashboardText('A dashboard használata');
    content.append(heading);
    paragraphs.forEach(text => {const p=document.createElement('p');p.textContent=text;content.append(p);});
    if (demo) showDemoHelp();
}

demoHelpLauncher.addEventListener('click',showDemoHelp);
document.getElementById('demo-help-close').addEventListener('click',hideDemoHelp);
document.getElementById('demo-help-ok').addEventListener('click',hideDemoHelp);
demoHelpBox.addEventListener('keydown',event => {if(event.key === 'Escape') hideDemoHelp();});
initializeDashboardPage();
