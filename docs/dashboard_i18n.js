// Presentation-only translations. Never translate IDs, data keys or control state.
function dashboardPageOptions(search = typeof window === 'undefined' ? '' : window.location?.search || '') {
    if (typeof URLSearchParams === 'undefined') return {language: 'hu', demo: false};
    const params = new URLSearchParams(search);
    return {language: params.get('lang') === 'en' ? 'en' : 'hu',
        demo: ['1', 'true'].includes(params.get('demo'))};
}

const DASHBOARD_ENGLISH = {
    'Kazán-Gólya fűtés: rendszerállapot': 'Kazán-Gólya heating: system status',
    'Adminisztrátori üzenet': 'Admin message', 'Üzenet bezárása': 'Close message',
    'Kérdésem van': 'I have a question', 'Rendszerállapot': 'System status',
    'Senki nem kér fűtést.': 'No heat requested.', 'Ma még nem érkezett kérés.': 'No requests today.',
    'Keringetett körök: mind': 'Running circuits: all',
    'Fűtés kikapcsolva.': 'Heating disabled.', 'Nem kér fűtést.': 'No heat requested.',
    'Fűtést kér.': 'Heat requested.', 'Fűtést kér:': 'Heat requested:',
    'kering': 'running', 'áll': 'idle',
    'kör ki': 'off',
    'kazán hiba!': 'boiler fault!',
    'Átlagos eltérés:': 'Mean deviation:', 'Eltérés:': 'Deviation:',
    'Idővezérelt be.': 'Timed on.', 'Idővezérelt ki.': 'Timed off.',
    'Beállított alatt.': 'Below setpoint.', 'Beállított felett.': 'Above setpoint.',
    'Felső hiszterézis.': 'Upper hysteresis.', 'Alsó hiszterézis.': 'Lower hysteresis.',
    'Szelepek zárva.': 'Valves closed.', 'Szelepek nyitva.': 'Valves open.',
    'Zárt hiszterézis.': 'Closed hysteresis.', 'Nyitott hiszterézis.': 'Open hysteresis.',
    'Szoba be.': 'Room enabled.', 'Szoba ki.': 'Room disabled.',
    'Kör időzítetten lekapcsolva.': 'Circuit disabled by schedule.',
    'Kör manuálisan bekapcsolva.': 'Circuit manually enabled.',
    'Kör manuálisan lekapcsolva.': 'Circuit manually disabled.',
    'rögzítve': 'pinned', 'Adatok betöltése.': 'Loading data.',
    'Előző nap': 'Previous day', 'Következő nap': 'Next day', 'óra': 'hour', 'kör': 'circuit',
    '1-es kör': 'circuit 1', '2-es kör': 'circuit 2', '3-mas kör': 'circuit 3', '3-as kör': 'circuit 3', '4-es kör': 'circuit 4',
    'alap': 'basic', 'részletes': 'details', 'analitika': 'analytics', 'Grafikon nézete': 'Chart view',
    'grafikon választása': 'chart selection', 'kazán': 'boiler', 'szobák': 'rooms',
    'fázissík': 'phase plane', 'statisztika': 'statistics', 'napi hiba': 'daily error',
    'jelenlét': 'occupied', 'üres': 'unoccupied', 'össz': 'all',
    'hőm.': 'temp.', 'páratart.': 'humidity', 'jelenl.': 'occupancy',
    'radiátor hőm.': 'radiator temp.', 'radiátor hőmérséklet': 'radiator temperature',
    'átlag hőm.': 'mean temp.', 'hőm. próbánként': 'temp. per probe', 'szelepnyitás': 'valve opening',
    'fűtővíz hőm.': 'water temp.', 'fűtőtelj.': 'heat output', 'átfolyás': 'flow',
    'szivattyú telj.': 'pump power', 'fűtőteljesítmény (kW)': 'heat output (kW)',
    'térfogatáram (m³/h)': 'flow (m³/h)', 'szivattyú teljesítmény (W)': 'pump power (W)',
    'teljesítmény (W)': 'power (W)', 'ráta (m³/h)': 'rate (m³/h)',
    'előremenő': 'supply', 'visszatérő': 'return', 'instant hőigény': 'instant heat demand',
    'átlagos fűtővíz hőm.': 'mean water temp.', 'hőigény': 'heat demand', 'hőigény (kW)': 'heat demand (kW)',
    'hőhasznosítás': 'heat utilisation', 'napi pontok': 'daily points',
    'napi leadott hő (kWh)': 'daily delivered heat (kWh)',
    'leadott hő / gázenergia (%)': 'delivered heat / gas energy (%)',
    'leadott hő / gázenergia': 'delivered heat / gas energy',
    'radiátor - szoba hőmérséklet (K)': 'radiator - room temperature (K)',
    'eltérés: mért − kért (K)': 'deviation: measured − set (K)',
    'eltérés (K) —': 'deviation (K) —',
    'szabályozási hiba (K)': 'control error (K)', 'alulfűtés': 'underheating', 'túlfűtés': 'overheating',
    'fűtés be, kért alatt': 'heat on, below set', 'fűtés be, kért felett': 'heat on, above set',
    'fűtés ki, kért alatt': 'heat off, below set', 'fűtés ki, kért felett': 'heat off, above set',
    'fűtés be': 'heat on', 'fűtés ki': 'heat off', 'kért alatt': 'below set', 'kért felett': 'above set',
    'átlagos irány': 'mean direction',
    'mért hőmérséklet': 'measured temperature', 'kért hőmérséklet': 'set temperature',
    'radiátor nyitási százalék': 'radiator valve opening',
    'elmúlt 3 nap átlagos hőmérséklete': 'mean temperature over the past 3 days',
    'hőm./harmatp.': 'temp./dew pt.', 'szél': 'wind', 'széllökés': 'gust', 'szélirány': 'wind direction',
    'fény': 'light', 'csapadék': 'rainfall', 'csapadék össz.': 'total rainfall', 'légnyomás': 'pressure',
    'hőmérséklet': 'temperature', 'harmatpont': 'dew point', 'nem kér': 'no heat requested', 'kér': 'heat requested',
    'élnek a kövek mert bennük is erő szalad': 'the stones are alive, for strength runs within them',
    'élnek a kövek': 'the stones are alive', 'mert bennük is erő szalad': 'for strength runs within them',
    'Nincs szélirányadat.': 'No wind direction data.',
    'Az adott napra nincs kapcsolási adat.': 'No switching data for this day.',
    'Nincs engedélyezett fűtési kör.': 'No enabled heating circuits.',
    'Átlagos jelenlét nem elérhető.': 'Average occupancy unavailable.',
    'Nincs elegendő energiaadat.': 'Insufficient energy data.',
    'Az adott napra nincs érvényes fázispont.': 'No valid phase points for this day.',
    'Az adott napra nincs szabályozási adat.': 'No control data for this day.',
    'Nincs érvényes fázisadat erre az időszakra.': 'No valid phase data for this period.',
    'Jelenlétkor nincs érvényes fázisadat.': 'No valid phase data during occupancy.',
    'Üresen nincs érvényes fázisadat.': 'No valid phase data while unoccupied.',
    'Nincs elegendő szabályozási adat.': 'Insufficient control data.',
    'Nincs megfigyelt állapotidő.': 'No observed time in this state.',
    'Nincs megfigyelt adat.': 'No observed data.', 'Az adott napra nincs adat.': 'No data for this day.',
    'A szobához nincs radiátor-hőmérő rendelve.': 'No radiator temperature probe is assigned to this room.',
    'mi ez?': 'help', 'Súgó bezárása': 'Close help', 'A dashboard használata': 'Using the dashboard',
    'az adott állapot átlagos abszolút eltérése': 'mean absolute deviation in the selected state'
};

const DASHBOARD_ENGLISH_PREFIXES = {
    'Szobák:': 'Rooms:', 'Fűtővíz:': 'Water:',
    'Keringetett fűtővíz:': 'Circulating water:',
    'Készenléti fűtővíz:': 'Standby water:',
    'Átlagos eltérés: ': 'Mean deviation: ', 'Eltérés: ': 'Deviation: ',
    'Keringetett körök: ': 'Running circuits: ', 'Utolsó kérés:': 'Last request:',
    'Beállítások frissítve:': 'Settings updated:', 'Vezérlés lefutott:': 'Last control run:',
    'Külső hőmérséklet:': 'Outdoor temperature:', 'Gázfogyasztási ráta:': 'Gas usage rate:',
    'Összes elégett gáz:': 'Total gas burnt:', 'Összköltség kb.': 'Estimated cost:',
    'Túlfűtés:': 'Overheating:', 'Alulfűtés:': 'Underheating:',
    'átlagos absz. eltérés:': 'mean absolute deviation:', 'nyitással súlyozott állapotidő:': 'valve-weighted state time:',
    'adatlefedettség:': 'data coverage:', 'radiátor:': 'radiator:', 'eltérés:': 'deviation:',
    'leadott:': 'delivered:', 'gázenergia:': 'gas energy:', 'gáz:': 'gas:', 'nap:': 'day:'
};
const DASHBOARD_WEEKDAYS = {
    'vasárnap': 'Sunday', 'hétfő': 'Monday', 'kedd': 'Tuesday', 'szerda': 'Wednesday',
    'csütörtök': 'Thursday', 'péntek': 'Friday', 'szombat': 'Saturday',
    'vasárnapi': 'Sunday', 'hétfői': 'Monday', 'keddi': 'Tuesday', 'szerdai': 'Wednesday',
    'csütörtöki': 'Thursday', 'pénteki': 'Friday', 'szombati': 'Saturday'
};

function dashboardEnglishLine(line) {
    const leading = line.match(/^\s*/)[0], trailing = line.match(/\s*$/)[0], text = line.trim();
    if (!text) return line;
    if (Object.hasOwn(DASHBOARD_ENGLISH, text)) return leading + DASHBOARD_ENGLISH[text] + trailing;
    let result = text;
    // Fixed phrases surrounding dynamic room names, dates and measured numbers.
    const patterns = [
        [/^(\d+)(?:\.|-(?:es|mas)) kör (mai|napi) fűtőteljesítménye$/, (_,n,day) => (day === 'mai' ? "today's" : 'daily') + ' heat output on circuit ' + n],
        [/^(\d+)(?:\.|-(?:es|mas)) kör(.*)$/, (_,n,tail) => 'Circuit ' + n + tail],
        [/^(\d+)\. kazán (mai|napi) villamos teljesítménye$/, (_,n,day) => 'Boiler ' + n + (day === 'mai' ? " today's" : ' daily') + ' electrical power'],
        [/^(\d+)-(?:es|mas) szivattyú (mai|napi) teljesítménygörbéje$/, (_,n,day) => 'Pump ' + n + (day === 'mai' ? " today's" : ' daily') + ' power'],
        [/^(mai|napi) gázfogyasztás$/, (_,day) => day === 'mai' ? "today's gas usage" : 'daily gas usage'],
        [/^(mai|napi) külső hőmérséklet$/, (_,day) => day === 'mai' ? "today's outdoor temperature" : 'daily outdoor temperature'],
        [/^szobák (mai|napi) hőmérsékleti görbéje(?: az? (\d+)-(?:es|mas) körön)?$/, (_,day,n) => (day === 'mai' ? "today's room temperatures" : 'daily room temperatures') + (n ? ' — circuit ' + n : '')],
        [/^körök (mai|napi) kapcsolási mintázata$/, (_,day) => day === 'mai' ? "today's circuit commands" : 'daily circuit commands'],
        [/^(.*) kért és mért hőmérséklet$/, '$1 set and measured temperature'],
        [/^(.*) mért hőmérséklet( \(\+ elmúlt 3 nap átlaga\))?$/, (_,name,mean) => name + ' measured temperature' + (mean ? ' (+ past 3-day mean)' : '')],
        [/^(.*) — radiátor (hőmérséklet|nyitás)$/, (_,name,metric) => name + ' — radiator ' + (metric === 'nyitás' ? 'opening' : 'temperature')],
        [/^átlagos (\S+) jelenlét \(%\)$/, (_,day) => 'average ' + (DASHBOARD_WEEKDAYS[day] || day) + ' occupancy (%)'],
        // Kazán 1 / Kazán 2 are proper circuit names, not boiler labels.
        [/^(kazán|szobák) —(?: (.*))?$/, (_,name,tail) => DASHBOARD_ENGLISH[name] + ' —' + (tail ? ' ' + tail : '')],
        [/^(be|ki)(,.*)?$/, (_,state,tail) => (state === 'be' ? 'on' : 'off') + (tail || '')],
        [/^Vezérlés: (.*) hiba!$/, 'Control: $1 error!'],
        [/^Vezérlés: (.*) áll!$/, 'Control stalled: $1'],
        [/^részarány a fűtés (be|ki) idején: (.*)$/, (_,state,value) => 'share while heat ' + (state === 'be' ? 'on' : 'off') + ': ' + value],
        [/^(szoba|radiátor) (hideg|jó|langyos|meleg)(?: (és|de) (hűl|melegszik))?$/, (_,name,state,join,motion) =>
            (name === 'szoba' ? 'room' : 'radiator') + ' ' + ({hideg:'cold',jó:'comfortable',langyos:'warm',meleg:'hot'})[state]
            + (motion ? (join === 'de' ? ' but ' : ' and ') + (motion === 'hűl' ? 'cooling' : 'warming') : '')]
    ];
    for (const [pattern, replacement] of patterns) if (pattern.test(result)) {result = result.replace(pattern,replacement); break;}
    for (const [prefix, translation] of Object.entries(DASHBOARD_ENGLISH_PREFIXES)) {
        if (result.startsWith(prefix)) {result = translation + result.slice(prefix.length); break;}
    }
    return leading + result
        .replace(/\b(\d+)\s+(másodperce|perce|órája)\b/g, (_,n,unit) => n + ({másodperce:' seconds ago',perce:' minutes ago',órája:' hours ago'})[unit])
        .replace(/\((vasárnap|hétfő|kedd|szerda|csütörtök|péntek|szombat)\)/g, (_,day) => '(' + DASHBOARD_WEEKDAYS[day] + ')')
        .replace(/\b7 nap:/g,'7 days:').replace(/\(átl\.:/g,'(avg.:')
        .replace(/ eFt\./g,' kHUF.').replace(/ Ft\./g,' HUF.').replace(/(\d),(?=\d)/g,'$1.') + trailing;
}

function dashboardText(value) {
    if (typeof value !== 'string' || dashboardPageOptions().language !== 'en') return value;
    // Leaf strings only: preserve DOM structure, HTML separators and proper names.
    return value.split(/(\n|<br\s*\/?>)/i).map(part => /^(\n|<br\s*\/?>)$/i.test(part) ? part
        : part.split(/(, )(?=(?:szoba|radiátor) (?:hideg|jó|langyos|meleg))/)
            .map(dashboardEnglishLine).join('')).join('');
}

function dashboardAdminMessage(dashboard) {
    return dashboard?.[dashboardPageOptions().language === 'en' ? 'admin_message_en' : 'admin_message'];
}

function dashboardCompassLabel(label) {
    return dashboardPageOptions().language === 'en' ? ({Ny:'W',É:'N',K:'E',D:'S'})[label] || label : label;
}
