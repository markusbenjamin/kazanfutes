// message_sheet.js reads the Sheet's message text and priorities directly.
// Keep acknowledgement only until reload, so polling does not reopen it.
const adminMessageBox = document.getElementById("admin-message");
const adminMessageContent = document.getElementById("admin-message-content");
const adminMessageOk = document.getElementById("admin-message-ok");
let currentAdminMessage = "";
let dismissedAdminMessage = "";
let adminMessagePreviousFocus;
let currentDashboardWarnings = {rainProtection: false, boilerError: false};
const dismissedDashboardWarnings = new Map();
let displayedDashboardMessage = "";
let dashboardMessageConfig = {};

function appendAdminMessageInline(parent, text) {
    // Build DOM nodes, never HTML: Sheet content cannot run scripts or handlers.
    const tokens = /(\*\*([^*\n]+)\*\*|\*([^*\n]+)\*|\[([^\]\n]+)\]\(([^\s)]+)\))/g;
    let previousEnd = 0;
    for (const match of text.matchAll(tokens)) {
        parent.append(document.createTextNode(text.slice(previousEnd, match.index)));
        let element;
        if (match[2] || match[3]) {
            element = document.createElement(match[2] ? "strong" : "em");
            element.textContent = match[2] || match[3];
        } else {
            try {
                const url = new URL(match[5]);
                if (["https:", "http:", "mailto:"].includes(url.protocol)) {
                    element = document.createElement("a");
                    element.href = url.href;
                    element.textContent = match[4];
                }
            } catch (error) {
                // Invalid or unsafe links remain readable, literal text.
            }
        }
        parent.append(element || document.createTextNode(match[0]));
        previousEnd = match.index + match[0].length;
    }
    parent.append(document.createTextNode(text.slice(previousEnd)));
}

function formatAdminMessage(message) {
    adminMessageContent.replaceChildren();
    let block;
    let blockType;
    for (const line of message.split("\n")) {
        if (!line.trim()) {
            block = null;
            blockType = null;
            continue;
        }
        const heading = line.match(/^#{1,6}\s+(.+)$/);
        const bullet = line.match(/^\s*[-*•]\s+(.+)$/);
        const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
        const type = heading ? "h3" : bullet ? "ul" : numbered ? "ol" : "p";
        if (!block || blockType !== type || heading) {
            block = document.createElement(type);
            adminMessageContent.append(block);
            blockType = type;
        } else if (type === "p") {
            block.append(document.createTextNode("\n"));
        }
        let target = block;
        if (bullet || numbered) {
            target = document.createElement("li");
            block.append(target);
        }
        appendAdminMessageInline(target, (heading || bullet || numbered)?.[1] || line);
    }
}

function hideAdminMessage() {
    const hadFocus = adminMessageBox.contains(document.activeElement);
    adminMessageBox.hidden = true;
    if (hadFocus && adminMessagePreviousFocus?.isConnected) {
        adminMessagePreviousFocus.focus({ preventScroll: true });
    }
}

function dismissAdminMessage() {
    const selected = selectedDashboardMessage();
    if (selected?.type !== 'admin' && selected) dismissedDashboardWarnings.set(selected.type, selected.message);
    else dismissedAdminMessage = currentAdminMessage;
    hideAdminMessage();
}

function updateAdminMessage(value) {
    const key = dashboardPageOptions().language === 'en' ? 'admin_message_en' : 'admin_message';
    updateDashboardMessageConfig({...dashboardMessageConfig, [key]: value});
}

function normalizeDashboardMessage(value) {
    return typeof value === 'string' ? value.replace(/\r\n?/g, '\n').trim() : '';
}

function updateDashboardMessageConfig(config) {
    dashboardMessageConfig = config && typeof config === 'object' ? {...config} : {};
    currentAdminMessage = normalizeDashboardMessage(dashboardAdminMessage(dashboardMessageConfig));
    if (!currentAdminMessage) dismissedAdminMessage = '';
    for (const [type,key] of [['rainProtection','rain_protection_message'],['boilerError','boiler_fault_message']]) {
        if (!normalizeDashboardMessage(dashboardConfigMessage(dashboardMessageConfig,key))) dismissedDashboardWarnings.delete(type);
    }
    renderDashboardMessage();
}

function selectedDashboardMessage() {
    // Priority 1 ranks first; ties retain rain/boiler/admin order.
    return [
        {type:'rainProtection',key:'rain_protection_message',active:currentDashboardWarnings.rainProtection},
        {type:'boilerError',key:'boiler_fault_message',active:currentDashboardWarnings.boilerError},
        {type:'admin',key:'admin_message',active:true}
    ].map(candidate => {
        const raw = dashboardMessageConfig[candidate.key + '_priority'];
        const priority = typeof raw === 'number' || typeof raw === 'string' && raw.trim() ? Number(raw) : NaN;
        return {...candidate, message:normalizeDashboardMessage(dashboardConfigMessage(dashboardMessageConfig,candidate.key)),
            priority:Number.isFinite(priority) ? priority : Infinity};
    }).filter(candidate => candidate.active && candidate.message)
        .sort((a,b) => a.priority === b.priority ? 0 : a.priority - b.priority)[0] || null;
}

function updateDashboardWarnings(warnings) {
    for (const key of ['rainProtection','boilerError']) {
        currentDashboardWarnings[key] = warnings?.[key] === true;
        // Acknowledgement lasts for this occurrence, even while another error
        // has priority. A clear followed by recurrence should show it again.
        if (!currentDashboardWarnings[key]) dismissedDashboardWarnings.delete(key);
    }
    renderDashboardMessage();
}

function renderDashboardMessage() {
    const selected = selectedDashboardMessage();
    if (!selected || (selected.type === 'admin' ? selected.message === dismissedAdminMessage
        : selected.message === dismissedDashboardWarnings.get(selected.type))) {
        hideAdminMessage();
        return;
    }
    const {message} = selected;
    const key = selected.type + ':' + message;
    if (key !== displayedDashboardMessage || adminMessageBox.hidden) {
        const wasHidden = adminMessageBox.hidden;
        displayedDashboardMessage = key;
        formatAdminMessage(message);
        adminMessageContent.scrollTop = 0;
        adminMessageBox.hidden = false;
        if (wasHidden) {
            adminMessagePreviousFocus = document.activeElement;
            adminMessageBox.focus({ preventScroll: true });
        }
    }
}

adminMessageOk.addEventListener("click", dismissAdminMessage);
document.getElementById("admin-message-close").addEventListener("click", dismissAdminMessage);
adminMessageBox.addEventListener("keydown", event => {
    if (event.key === "Escape") {
        dismissAdminMessage();
    }
});
