// The config updater publishes only the Sheet's admin_message to Firebase.
// Keep acknowledgement only until reload, so polling does not reopen it.
const adminMessageBox = document.getElementById("admin-message");
const adminMessageContent = document.getElementById("admin-message-content");
const adminMessageOk = document.getElementById("admin-message-ok");
let currentAdminMessage = "";
let dismissedAdminMessage = "";
let adminMessagePreviousFocus;

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
    dismissedAdminMessage = currentAdminMessage;
    hideAdminMessage();
}

function updateAdminMessage(value) {
    // Returning from the request form should go straight to the dashboard.
    if (new URLSearchParams(window.location.search).get("ref_source") === "form") {
        hideAdminMessage();
        return;
    }
    const message = typeof value === "string" ? value.replace(/\r\n?/g, "\n").trim() : "";
    if (!message) {
        currentAdminMessage = "";
        dismissedAdminMessage = "";
        hideAdminMessage();
        return;
    }
    if (message === dismissedAdminMessage) {
        hideAdminMessage();
        return;
    }
    if (message !== currentAdminMessage || adminMessageBox.hidden) {
        const wasHidden = adminMessageBox.hidden;
        currentAdminMessage = message;
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
