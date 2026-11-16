// Re-render presentation from retained inputs; keep IDs, selection and data intact.
let dashboardRenderedLanguage = dashboardPageOptions().language;
let dashboardLanguagePlot;

function cacheDashboardPlotLanguage(data, setting) {
    if (data !== null) dashboardLanguagePlot = {data, setting};
}

function switchDashboardLanguage(language) {
    if (!['hu','en'].includes(language) || language === dashboardPageOptions().language) return;
    const url = new URL(window.location.href);
    url.searchParams.set('lang', language);
    window.history.replaceState(window.history.state, '', url.href);
    applyDashboardLanguage();
}

function applyDashboardLanguage() {
    const language = dashboardPageOptions().language;
    if (language === dashboardRenderedLanguage) return;
    const previous = dashboardRenderedLanguage;
    dashboardRenderedLanguage = language;
    initializeDashboardPage({initial: false});
    document.querySelectorAll('[data-dashboard-text]').forEach(node => {
        node.textContent = dashboardText(node.dataset.dashboardText);
    });
    if (typeof refreshDashboardMessageLanguage === 'function') refreshDashboardMessageLanguage(previous);
    const replaying = typeof dashboardReplayActive === 'function' && dashboardReplayActive();
    if (replaying) replayPaint(false);
    else if (typeof replayLatestLive !== 'undefined' && replayLatestLive)
        renderDashboardState(replayLatestLive, {languageOnly: true});
    if (typeof localizeReplayPane === 'function') localizeReplayPane();
    if (typeof updateDashboardClock === 'function') updateDashboardClock();
    const tooltip = document.getElementById('tooltip');
    if (tooltip) tooltip.style.visibility = 'hidden';
    if (typeof mainGraphSetting !== 'undefined' && typeof drawMainGraph === 'function') {
        const cached = dashboardLanguagePlot;
        // An unloaded chart already has an in-flight request. Relabel its
        // placeholder without starting another request or resetting selection.
        drawMainGraph(cached?.setting === mainGraphSetting ? cached.data : {});
    }
}

window.addEventListener('popstate', applyDashboardLanguage);
