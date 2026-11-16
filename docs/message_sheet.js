// Message text and priorities come directly from the public config Sheet.
// Firebase supplies only the operational warning states, not these settings.
const DASHBOARD_MESSAGE_SHEET_URL = 'https://docs.google.com/spreadsheets/d/1sXoPC301Wurbm7yW5A956dlFEJcwM-fIb090fKOxROw/export?format=csv';
const DASHBOARD_MESSAGE_SHEET_KEYS = ['admin_message','rain_protection_message','boiler_fault_message']
    .flatMap(key => [key,key+'_en',key+'_priority']);
let dashboardMessageSheetRequest = null;

function dashboardMessagesFromSheetRows(rows) {
    if (!Array.isArray(rows) || !rows.some(row => Array.isArray(row) && typeof row[0] === 'string'
        && DASHBOARD_MESSAGE_SHEET_KEYS.includes(row[0].trim())))
        throw Error('The Sheet response is missing the dashboard message settings');
    const config = Object.fromEntries(DASHBOARD_MESSAGE_SHEET_KEYS.map(key => [key,'']));
    for (const row of rows) {
        const key = typeof row?.[0] === 'string' ? row[0].trim() : '';
        if (Object.hasOwn(config,key)) config[key] = row[1] ?? '';
    }
    return config;
}

function refreshDashboardMessageSheet() {
    if (dashboardMessageSheetRequest) return dashboardMessageSheetRequest;
    dashboardMessageSheetRequest = (async () => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(),12000);
        try {
            const response = await fetch(DASHBOARD_MESSAGE_SHEET_URL + '&updated=' + Date.now(),
                {credentials:'omit',cache:'no-store',signal:controller.signal});
            if (!response.ok) throw Error('Message Sheet HTTP ' + response.status);
            const csv = await response.text();
            if (/^\s*</.test(csv) || !/text\/(csv|plain)/i.test(response.headers.get('Content-Type') || ''))
                throw Error('Message Sheet did not return CSV');
            const config = dashboardMessagesFromSheetRows(d3.csvParseRows(csv));
            updateDashboardMessageConfig(config);
            return true;
        } catch (error) {
            // Preserve the last successful text and acknowledgement through an
            // outage. Only a successful Sheet read can clear/update messages.
            console.warn('Could not refresh dashboard messages from Google Sheet:',error);
            return false;
        } finally {
            clearTimeout(timeout);
            dashboardMessageSheetRequest = null;
        }
    })();
    return dashboardMessageSheetRequest;
}

document.addEventListener('DOMContentLoaded', () => {
    refreshDashboardMessageSheet();
    setInterval(refreshDashboardMessageSheet,30000);
});
