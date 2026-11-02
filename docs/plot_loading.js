// A new plot gets a short grace period before declaring its data unavailable.
// Only status text changes on timeout: never redraw over a curve that arrived.
const MAIN_PLOT_LOADING_GRACE_MS = 10000;
let mainPlotLoadingState;

function beginMainPlotLoading(setting) {
    const key = JSON.stringify(setting);
    if (mainPlotLoadingState?.key === key) return false;
    if (mainPlotLoadingState) clearTimeout(mainPlotLoadingState.timer);
    const state = {key, expired: false, labels: new Map()};
    mainPlotLoadingState = state;
    state.timer = setTimeout(() => {
        if (mainPlotLoadingState !== state || JSON.stringify(mainGraphSetting) !== key) return;
        state.expired = true;
        state.labels.forEach(({selection, message}, node) => {
            if (node.isConnected) selection.attr('data-plot-status', 'empty').text(dashboardText(message));
        });
        state.labels.clear();
    }, MAIN_PLOT_LOADING_GRACE_MS);
    return true;
}

function setPlotEmptyMessage(selection, message) {
    const state = mainPlotLoadingState;
    // Known configuration facts are not waiting on chart data.
    const waiting = state && !state.expired && state.key === JSON.stringify(mainGraphSetting)
        && message !== 'A szobához nincs radiátor-hőmérő rendelve.';
    selection.attr('data-plot-status', waiting ? 'loading' : 'empty')
        .text(dashboardText(waiting ? 'Adatok betöltése.' : message));
    if (waiting) {
        // A redraw removes old SVG nodes; do not retain them during refreshes.
        state.labels.forEach((value, node) => {if (!node.isConnected) state.labels.delete(node);});
        const node = selection.node();
        if (node) state.labels.set(node, {selection, message});
    }
    return selection;
}
