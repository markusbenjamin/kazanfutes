import html
import json
from datetime import datetime
from time import perf_counter, sleep

import duckdb


MODE = "write_stream_timeline"
DUCKDB_CONNECT_RETRY_SECONDS = 180
DUCKDB_CONNECT_RETRY_INTERVAL_SECONDS = 2

DATA_PATH = __file__.replace("\\", "/").rsplit("/", 2)[0]
DB_PATH = f"{DATA_PATH}/db/store/observations.duckdb"
STREAM_METADATA_PATH = f"{DATA_PATH}/db/metadata/stream_metadata.csv"
TIMELINE_PATH = f"{DATA_PATH}/db/stream_availability.html"
AVAILABILITY_CSV_PATH = f"{DATA_PATH}/db/stream_availability.csv"

STREAM_AVAILABILITY_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stream availability</title>
<style>
:root {
    --background: #f6f7f9;
    --surface: #ffffff;
    --surface-2: #f9fafb;
    --border: #d9dee6;
    --border-soft: #e8ebf0;
    --text: #1f2933;
    --muted: #64748b;
    --muted-2: #94a3b8;
    --blue: #2563eb;
    --teal: #0f766e;
    --green: #16803c;
    --amber: #b45309;
    --red: #b42318;
    --violet: #6d28d9;
    --track: #edf1f5;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: var(--background);
    color: var(--text);
    font-family: Arial, Helvetica, sans-serif;
    letter-spacing: 0;
}

button,
input,
select {
    font: inherit;
    letter-spacing: 0;
}

main {
    width: min(1640px, calc(100% - 32px));
    margin: 0 auto;
    padding: 24px 0 32px;
}

.page-header {
    display: flex;
    justify-content: space-between;
    gap: 20px;
    align-items: flex-start;
    margin-bottom: 16px;
}

h1 {
    margin: 0 0 6px;
    font-size: 24px;
    line-height: 1.2;
}

.meta-line {
    color: var(--muted);
    font-size: 13px;
}

.link-row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: flex-end;
}

.link-row a {
    color: var(--blue);
    text-decoration: none;
    font-size: 13px;
}

.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 10px;
    margin: 0 0 14px;
}

.stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    min-height: 76px;
}

.stat-label {
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 8px;
}

.stat-value {
    font-size: 22px;
    line-height: 1.1;
    font-weight: 700;
}

.toolbar {
    position: sticky;
    top: 0;
    z-index: 10;
    background: rgba(246, 247, 249, 0.96);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 14px;
    backdrop-filter: blur(8px);
}

.control-grid {
    display: grid;
    grid-template-columns: minmax(220px, 2fr) repeat(4, minmax(150px, 1fr)) auto;
    gap: 10px;
    align-items: center;
}

.control-grid input,
.control-grid select {
    width: 100%;
    min-height: 36px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    padding: 7px 9px;
}

.plain-button,
.chip {
    min-height: 34px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    padding: 6px 10px;
    cursor: pointer;
}

.plain-button:hover,
.chip:hover {
    border-color: var(--blue);
}

.chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
}

.chip {
    color: var(--muted);
    font-size: 12px;
}

.chip.active {
    background: #1f3a5f;
    border-color: #1f3a5f;
    color: #ffffff;
}

.missing-panel,
.list-panel,
.inspector {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
}

.missing-panel {
    margin-bottom: 14px;
}

.missing-panel > summary {
    padding: 11px 14px;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    gap: 12px;
    font-weight: 700;
}

.missing-list {
    border-top: 1px solid var(--border-soft);
    padding: 12px 14px;
}

.missing-list details {
    border: 1px solid var(--border-soft);
    border-radius: 6px;
    margin-bottom: 8px;
}

.missing-list summary {
    cursor: pointer;
    padding: 8px 10px;
}

.missing-items {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 6px;
    padding: 0 10px 10px;
}

.missing-item {
    color: var(--muted);
    font-size: 12px;
    overflow-wrap: anywhere;
}

.result-meta {
    color: var(--muted);
    font-size: 13px;
    margin: 0 0 8px;
}

.plot-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin: 0 0 14px;
    padding: 14px;
}

.plot-header {
    display: flex;
    justify-content: space-between;
    gap: 14px;
    align-items: flex-start;
    margin-bottom: 12px;
}

.plot-title {
    font-size: 18px;
    font-weight: 700;
    line-height: 1.25;
    margin-bottom: 3px;
}

.plot-subtitle {
    color: var(--muted);
    font-size: 12px;
    overflow-wrap: anywhere;
}

.plot-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: flex-end;
}

.plot-control-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin: 8px 0 0;
}

.plot-control-row label {
    color: var(--muted);
    font-size: 12px;
}

.plot-control-row input,
.plot-control-row select {
    min-height: 32px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    padding: 5px 8px;
}

.plot-stream-select {
    min-width: 300px;
    max-width: 100%;
}

.plot-group-select {
    min-width: 180px;
}

.plot-button {
    min-height: 30px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--muted);
    padding: 5px 9px;
    cursor: pointer;
    font-size: 12px;
}

.plot-button.active {
    background: #1f3a5f;
    border-color: #1f3a5f;
    color: #ffffff;
}

.plot-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 10px 0 4px;
}

.plot-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 28px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface-2);
    color: var(--text);
    padding: 4px 8px;
    font-size: 12px;
}

.plot-chip button {
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    padding: 0 2px;
}

.plot-swatch {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    display: inline-block;
}

.scatter-selects {
    display: none;
}

.plot-panel.scatter-mode .scatter-selects {
    display: flex;
}

.plot-frame {
    position: relative;
}

.plot-canvas {
    width: 100%;
    height: 340px;
    border: 1px solid var(--border-soft);
    border-radius: 6px;
    background: #fbfcfe;
    display: block;
}

.plot-tooltip {
    position: absolute;
    pointer-events: none;
    display: none;
    max-width: 260px;
    background: #111827;
    color: #ffffff;
    border-radius: 6px;
    padding: 8px 9px;
    font-size: 12px;
    line-height: 1.4;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.22);
    z-index: 4;
}

.plot-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
    color: var(--muted);
    font-size: 12px;
    margin-top: 8px;
}

.legend-item {
    display: inline-flex;
    gap: 6px;
    align-items: center;
}

.legend-swatch {
    width: 18px;
    height: 8px;
    border-radius: 999px;
    display: inline-block;
}

.legend-count {
    background: var(--teal);
}

.legend-value {
    background: var(--amber);
}

.report-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(300px, 340px);
    gap: 14px;
    align-items: start;
}

.list-panel {
    overflow: hidden;
}

.empty-state {
    color: var(--muted);
    padding: 20px;
}

.group {
    border-top: 1px solid var(--border-soft);
}

.group:first-child {
    border-top: 0;
}

.group > summary {
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: baseline;
    padding: 10px 12px;
    background: var(--surface-2);
}

.group.level-1 > summary {
    font-weight: 700;
}

.group.level-2 > summary {
    padding-left: 24px;
}

.group-title {
    overflow-wrap: anywhere;
}

.group-stats {
    color: var(--muted);
    font-size: 12px;
    text-align: right;
    white-space: nowrap;
}

.stream-row {
    appearance: none;
    width: 100%;
    border: 0;
    border-top: 1px solid var(--border-soft);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
    display: grid;
    grid-template-columns: minmax(250px, 390px) minmax(220px, 1fr) 108px;
    gap: 14px;
    align-items: center;
    min-height: 58px;
    padding: 9px 12px;
    text-align: left;
}

.stream-row:hover,
.stream-row.active {
    background: #f4f8ff;
}

.stream-main {
    min-width: 0;
}

.stream-name {
    font-size: 13px;
    font-weight: 700;
    overflow-wrap: anywhere;
}

.stream-description,
.stream-id {
    color: var(--muted);
    font-size: 12px;
    overflow-wrap: anywhere;
}

.stream-id {
    margin-top: 2px;
}

.status-line {
    display: flex;
    gap: 7px;
    align-items: center;
    margin-top: 5px;
    color: var(--muted);
    font-size: 12px;
}

.badge {
    display: inline-flex;
    align-items: center;
    min-height: 20px;
    border-radius: 999px;
    padding: 2px 7px;
    font-size: 11px;
    font-weight: 700;
}

.badge.loaded {
    background: #e8f5ee;
    color: var(--green);
}

.badge.missing {
    background: #fff1f0;
    color: var(--red);
}

.badge.stale {
    background: #fff7e6;
    color: var(--amber);
}

.stream-viz {
    display: grid;
    gap: 7px;
}

.coverage-track {
    position: relative;
    height: 10px;
    background: var(--track);
    border-radius: 999px;
    overflow: hidden;
}

.coverage-bar {
    position: absolute;
    top: 0;
    bottom: 0;
    min-width: 2px;
    background: var(--blue);
    border-radius: 999px;
}

.gap-strip {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: 1fr;
    gap: 1px;
    height: 16px;
}

.gap-strip span {
    min-width: 1px;
    border-radius: 1px;
}

.gap-empty {
    background: #e5e7eb;
}

.gap-low {
    background: #a7f3d0;
}

.gap-mid {
    background: #2dd4bf;
}

.gap-high {
    background: #0f766e;
}

.stream-count {
    color: var(--muted);
    font-size: 12px;
    text-align: right;
    white-space: nowrap;
}

.inspector {
    position: sticky;
    top: 94px;
    padding: 14px;
}

.inspector h2 {
    margin: 0 0 4px;
    font-size: 18px;
    line-height: 1.25;
}

.inspector-subtitle {
    color: var(--muted);
    font-size: 12px;
    overflow-wrap: anywhere;
    margin-bottom: 12px;
}

.metric-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin: 12px 0;
}

.metric {
    border: 1px solid var(--border-soft);
    border-radius: 6px;
    padding: 8px;
    min-width: 0;
}

.metric-label {
    color: var(--muted);
    font-size: 11px;
    margin-bottom: 4px;
}

.metric-value {
    font-size: 13px;
    font-weight: 700;
    overflow-wrap: anywhere;
}

.chart {
    width: 100%;
    height: 180px;
    border: 1px solid var(--border-soft);
    border-radius: 6px;
    background: #fbfcfe;
    display: block;
}

.inspector-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin: 10px 0 12px;
}

.hidden {
    display: none;
}

@media (max-width: 1100px) {
    .control-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .report-layout {
        grid-template-columns: 1fr;
    }

    .inspector {
        position: static;
    }
}

@media (max-width: 760px) {
    main {
        width: min(100% - 20px, 1640px);
        padding-top: 14px;
    }

    .page-header,
    .link-row {
        display: block;
    }

    .control-grid {
        grid-template-columns: 1fr;
    }

    .stream-row {
        grid-template-columns: 1fr;
    }

    .stream-count {
        text-align: left;
    }
}
</style>
</head>
<body>
<main>
    <header class="page-header">
        <div>
            <h1>Stream availability</h1>
            <div class="meta-line" id="timelineMeta"></div>
        </div>
        <nav class="link-row" aria-label="Report outputs">
            <a href="stream_availability.csv">CSV</a>
            <a href="store/observations.duckdb">DuckDB</a>
        </nav>
    </header>

    <section class="summary-grid" id="summaryCards" aria-label="Summary"></section>

    <section class="toolbar" aria-label="Filters">
        <div class="control-grid">
            <input id="searchInput" type="search" placeholder="Search streams">
            <select id="statusFilter" aria-label="Status">
                <option value="all">All statuses</option>
                <option value="loaded">Loaded</option>
                <option value="missing">Missing</option>
                <option value="stale">Stale</option>
            </select>
            <select id="groupMode" aria-label="Grouping">
                <option value="scope">Group by scope</option>
                <option value="scope_variable">Group by scope and variable</option>
                <option value="variable">Group by variable</option>
                <option value="flat">Flat list</option>
            </select>
            <select id="sortMode" aria-label="Sort">
                <option value="scope">Scope order</option>
                <option value="missing">Missing first</option>
                <option value="stale">Stale first</option>
                <option value="count_desc">Most observations</option>
                <option value="count_asc">Fewest observations</option>
            </select>
            <select id="variableFilter" aria-label="Variable"></select>
            <button class="plain-button" id="clearFilters" type="button">Clear</button>
        </div>
        <div class="chip-row" id="scopeChips" aria-label="Scope type filters"></div>
    </section>

    <details class="missing-panel" id="missingPanel" open>
        <summary>
            <span>Missing streams</span>
            <span id="missingSummary"></span>
        </summary>
        <div class="missing-list" id="missingList"></div>
    </details>

    <section class="plot-panel" id="plotPanel" aria-label="Selected stream plot"></section>

    <div class="result-meta" id="resultMeta"></div>

    <section class="report-layout">
        <div class="list-panel" id="streamList"></div>
        <aside class="inspector" id="inspector" aria-label="Stream inspector"></aside>
    </section>
</main>

<script>
const REPORT = __REPORT_DATA__;
const firstLoadedStream = REPORT.streams.find((stream) => stream.loaded) || REPORT.streams[0] || null;

const state = {
    query: "",
    status: "all",
    group: "scope",
    sort: "scope",
    variable: "",
    scopeTypes: new Set(),
    selectedId: firstLoadedStream ? firstLoadedStream.id : null,
    plotIds: firstLoadedStream ? [firstLoadedStream.id] : [],
    plotKind: "timeseries",
    plotBucket: "weekly",
    spreadMode: "std",
    bandPeriod: "day",
    bandBin: "hour",
    addPickerGroup: "",
    scatterPickerGroup: "",
    rangeStart: REPORT.summary.dayStart,
    rangeEnd: (REPORT.summary.timelineEnd || "").slice(0, 10),
    rangePreset: "all",
    scatterAgainstId: null
};

const streamsById = new Map(REPORT.streams.map((stream) => [stream.id, stream]));
const loadedStreams = REPORT.streams.filter((stream) => stream.loaded);
const plotColors = [
    "#2563eb",
    "#b45309",
    "#0f766e",
    "#6d28d9",
    "#b42318",
    "#64748b",
    "#0284c7",
    "#7c2d12"
];
const weeklyCache = new Map();

function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
        element.className = className;
    }
    if (text !== undefined && text !== null) {
        element.textContent = text;
    }
    return element;
}

function formatNumber(value) {
    return new Intl.NumberFormat("en-US").format(value || 0);
}

function formatDate(value) {
    if (!value) {
        return "";
    }
    return value.replace("T", " ").slice(0, 19);
}

function formatDays(days) {
    if (days === null || days === undefined) {
        return "";
    }
    if (days < 1) {
        return "fresh";
    }
    if (days < 30) {
        return `${Math.round(days)}d old`;
    }
    return `${Math.round(days / 30)}mo old`;
}

function naturalCompare(a, b) {
    return String(a || "").localeCompare(String(b || ""), undefined, {
        numeric: true,
        sensitivity: "base"
    });
}

function streamStatus(stream) {
    if (!stream.loaded) {
        return "missing";
    }
    if (stream.lastAgeDays !== null && stream.lastAgeDays > REPORT.summary.staleDays) {
        return "stale";
    }
    return "loaded";
}

function statusText(stream) {
    const status = streamStatus(stream);
    if (status === "missing") {
        return "missing";
    }
    if (status === "stale") {
        return "stale";
    }
    return "loaded";
}

function renderSummary() {
    const summary = REPORT.summary;
    document.getElementById("timelineMeta").textContent = summary.timelineStart
        ? `${formatDate(summary.timelineStart)} to ${formatDate(summary.timelineEnd)}`
        : "No observations";

    const cards = [
        ["Streams", formatNumber(summary.totalStreams)],
        ["Loaded", `${formatNumber(summary.loadedStreams)} / ${formatNumber(summary.totalStreams)}`],
        ["Missing", formatNumber(summary.missingStreams)],
        ["Observations", formatNumber(summary.observations)],
        ["Days", formatNumber(summary.dayCount)],
        ["Generated", formatDate(summary.generatedAt)]
    ];

    const container = document.getElementById("summaryCards");
    container.innerHTML = "";
    for (const [label, value] of cards) {
        const card = make("div", "stat-card");
        card.append(make("div", "stat-label", label));
        card.append(make("div", "stat-value", value));
        container.append(card);
    }
}

function populateVariableFilter() {
    const counts = new Map();
    for (const stream of REPORT.streams) {
        counts.set(stream.variable, (counts.get(stream.variable) || 0) + 1);
    }

    const variables = Array.from(counts.entries()).sort((a, b) => {
        if (b[1] !== a[1]) {
            return b[1] - a[1];
        }
        return naturalCompare(a[0], b[0]);
    });

    const select = document.getElementById("variableFilter");
    select.innerHTML = "";
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "All variables";
    select.append(all);

    for (const [variable, count] of variables) {
        const option = document.createElement("option");
        option.value = variable;
        option.textContent = `${variable} (${count})`;
        select.append(option);
    }
}

function renderScopeChips() {
    const counts = new Map();
    for (const stream of REPORT.streams) {
        counts.set(stream.scopeType, (counts.get(stream.scopeType) || 0) + 1);
    }

    const container = document.getElementById("scopeChips");
    container.innerHTML = "";
    const scopeTypes = Array.from(counts.keys()).sort(naturalCompare);
    for (const scopeType of scopeTypes) {
        const chip = make("button", "chip", `${scopeType} (${counts.get(scopeType)})`);
        chip.type = "button";
        chip.dataset.scopeType = scopeType;
        if (state.scopeTypes.has(scopeType)) {
            chip.classList.add("active");
        }
        chip.addEventListener("click", () => {
            if (state.scopeTypes.has(scopeType)) {
                state.scopeTypes.delete(scopeType);
            } else {
                state.scopeTypes.add(scopeType);
            }
            render();
        });
        container.append(chip);
    }
}

function passesQuery(stream) {
    if (!state.query) {
        return true;
    }

    const haystack = [
        stream.id,
        stream.variable,
        stream.scopeType,
        stream.scopeId,
        stream.scopeLabel,
        stream.description,
        stream.unit
    ].join(" ").toLowerCase();

    return haystack.includes(state.query);
}

function filteredStreams() {
    return REPORT.streams.filter((stream) => {
        if (!passesQuery(stream)) {
            return false;
        }
        if (state.variable && stream.variable !== state.variable) {
            return false;
        }
        if (state.scopeTypes.size > 0 && !state.scopeTypes.has(stream.scopeType)) {
            return false;
        }
        if (state.status !== "all" && streamStatus(stream) !== state.status) {
            return false;
        }
        return true;
    });
}

function sortStreams(records) {
    const sorted = records.slice();

    sorted.sort((a, b) => {
        if (state.sort === "count_desc") {
            return b.count - a.count || scopeCompare(a, b);
        }
        if (state.sort === "count_asc") {
            return a.count - b.count || scopeCompare(a, b);
        }
        if (state.sort === "missing") {
            return Number(a.loaded) - Number(b.loaded) || scopeCompare(a, b);
        }
        if (state.sort === "stale") {
            return (b.lastAgeDays || -1) - (a.lastAgeDays || -1) || scopeCompare(a, b);
        }
        return scopeCompare(a, b);
    });

    return sorted;
}

function scopeCompare(a, b) {
    return (
        naturalCompare(a.scopeType, b.scopeType)
        || naturalCompare(a.scopeId, b.scopeId)
        || naturalCompare(a.variable, b.variable)
        || naturalCompare(a.id, b.id)
    );
}

function groupConfig() {
    if (state.group === "flat") {
        return [];
    }
    if (state.group === "variable") {
        return [
            {
                key: (stream) => stream.variable,
                title: (records) => records[0].variable
            }
        ];
    }
    if (state.group === "scope_variable") {
        return [
            {
                key: (stream) => stream.scopeType,
                title: (records) => records[0].scopeType
            },
            {
                key: (stream) => `${stream.scopeType}\\0${stream.variable}`,
                title: (records) => records[0].variable
            }
        ];
    }
    return [
        {
            key: (stream) => stream.scopeType,
            title: (records) => records[0].scopeType
        },
        {
            key: (stream) => `${stream.scopeType}\\0${stream.scopeId}`,
            title: (records) => records[0].scopeLabel
        }
    ];
}

function statsFor(records) {
    let loaded = 0;
    let count = 0;
    let first = null;
    let last = null;

    for (const stream of records) {
        if (stream.loaded) {
            loaded += 1;
            if (!first || stream.first < first) {
                first = stream.first;
            }
            if (!last || stream.last > last) {
                last = stream.last;
            }
        }
        count += stream.count;
    }

    return {
        total: records.length,
        loaded,
        missing: records.length - loaded,
        count,
        first,
        last
    };
}

function statsText(stats) {
    const loaded = `${formatNumber(stats.loaded)} / ${formatNumber(stats.total)} loaded`;
    const count = `${formatNumber(stats.count)} obs`;
    const range = stats.first ? `${formatDate(stats.first).slice(0, 10)} to ${formatDate(stats.last).slice(0, 10)}` : "no observations";
    return `${loaded} · ${count} · ${range}`;
}

function renderGroups(records, container, config, level) {
    if (config.length === 0) {
        for (const stream of records) {
            container.append(renderStreamRow(stream));
        }
        return;
    }

    const [current, ...rest] = config;
    const groups = new Map();
    for (const stream of records) {
        const key = current.key(stream);
        if (!groups.has(key)) {
            groups.set(key, []);
        }
        groups.get(key).push(stream);
    }

    const grouped = Array.from(groups.values()).sort((a, b) => {
        return naturalCompare(current.title(a), current.title(b));
    });

    grouped.forEach((groupRecords, index) => {
        const details = make("details", `group level-${level}`);
        const hasActiveFilter = Boolean(
            state.query || state.status !== "all" || state.variable || state.scopeTypes.size
        );
        details.open = hasActiveFilter || level === 1 || (level === 2 && grouped.length <= 8);

        const summary = make("summary");
        const title = make("span", "group-title", current.title(groupRecords));
        const stats = make("span", "group-stats", statsText(statsFor(groupRecords)));
        summary.append(title, stats);
        details.append(summary);

        const body = make("div", "group-body");
        renderGroups(groupRecords, body, rest, level + 1);
        details.append(body);
        container.append(details);
    });
}

function weeklySegments(streamId) {
    if (weeklyCache.has(streamId)) {
        return weeklyCache.get(streamId);
    }

    const weekCount = Math.max(1, Math.ceil((REPORT.summary.dayCount || 1) / 7));
    const counts = Array.from({ length: weekCount }, () => 0);
    for (const bin of REPORT.bins[streamId] || []) {
        const week = Math.min(weekCount - 1, Math.floor(bin[0] / 7));
        counts[week] += bin[1];
    }

    const maxCount = Math.max(...counts, 0);
    const segments = counts.map((count) => {
        if (count === 0) {
            return "gap-empty";
        }
        if (count < maxCount * 0.15) {
            return "gap-low";
        }
        if (count < maxCount * 0.55) {
            return "gap-mid";
        }
        return "gap-high";
    });

    weeklyCache.set(streamId, segments);
    return segments;
}

function renderStreamRow(stream) {
    const row = make("button", "stream-row");
    row.type = "button";
    row.dataset.streamId = stream.id;
    if (stream.id === state.selectedId) {
        row.classList.add("active");
    }

    row.addEventListener("click", () => {
        state.selectedId = stream.id;
        state.plotIds = [stream.id];
        render();
        window.requestAnimationFrame(() => {
            document.getElementById("plotPanel").scrollIntoView({
                behavior: "smooth",
                block: "start"
            });
        });
    });

    const main = make("div", "stream-main");
    const unit = stream.unit ? ` (${stream.unit})` : "";
    main.append(make("div", "stream-name", `${stream.variable}${unit} / ${stream.scopeLabel}`));
    main.append(make("div", "stream-description", stream.description || ""));
    main.append(make("div", "stream-id", stream.id));

    const status = streamStatus(stream);
    const statusLine = make("div", "status-line");
    statusLine.append(make("span", `badge ${status}`, statusText(stream)));
    if (stream.loaded) {
        statusLine.append(make("span", "", `${formatDate(stream.first).slice(0, 10)} to ${formatDate(stream.last).slice(0, 10)}`));
        statusLine.append(make("span", "", formatDays(stream.lastAgeDays)));
    }
    main.append(statusLine);
    row.append(main);

    const viz = make("div", "stream-viz");
    const coverage = make("div", "coverage-track");
    if (stream.loaded) {
        const bar = make("span", "coverage-bar");
        bar.style.left = `${stream.startPercent || 0}%`;
        bar.style.width = `${stream.widthPercent || 0}%`;
        coverage.append(bar);
    }
    viz.append(coverage);

    const strip = make("div", "gap-strip");
    if (stream.loaded) {
        for (const className of weeklySegments(stream.id)) {
            strip.append(make("span", className));
        }
    } else {
        strip.append(make("span", "gap-empty"));
    }
    viz.append(strip);
    row.append(viz);

    const count = make("div", "stream-count", stream.loaded ? `${formatNumber(stream.count)} obs` : "no observations");
    row.append(count);

    return row;
}

function renderMissingList() {
    const missing = REPORT.streams.filter((stream) => !stream.loaded);
    const summary = document.getElementById("missingSummary");
    summary.textContent = `${formatNumber(missing.length)} missing`;

    const container = document.getElementById("missingList");
    container.innerHTML = "";
    if (missing.length === 0) {
        container.append(make("div", "empty-state", "No missing streams."));
        return;
    }

    const groups = new Map();
    for (const stream of missing) {
        if (!groups.has(stream.scopeType)) {
            groups.set(stream.scopeType, []);
        }
        groups.get(stream.scopeType).push(stream);
    }

    const groupList = Array.from(groups.entries()).sort((a, b) => naturalCompare(a[0], b[0]));
    for (const [scopeType, records] of groupList) {
        const details = make("details");
        const summaryRow = make("summary", "", `${scopeType} (${records.length})`);
        details.append(summaryRow);

        const items = make("div", "missing-items");
        records.sort(scopeCompare).forEach((stream) => {
            items.append(make("div", "missing-item", stream.id));
        });
        details.append(items);
        container.append(details);
    }
}

function renderList() {
    const records = sortStreams(filteredStreams());
    const list = document.getElementById("streamList");
    list.innerHTML = "";
    document.getElementById("resultMeta").textContent = `${formatNumber(records.length)} of ${formatNumber(REPORT.streams.length)} streams`;

    if (records.length === 0) {
        list.append(make("div", "empty-state", "No streams match the current filters."));
        return;
    }

    const config = groupConfig();
    if (config.length === 0) {
        renderGroups(records, list, [], 1);
    } else {
        renderGroups(records, list, config, 1);
    }
}

function metric(label, value) {
    const element = make("div", "metric");
    element.append(make("div", "metric-label", label));
    element.append(make("div", "metric-value", value || ""));
    return element;
}

function addDays(dayIndex) {
    const date = new Date(`${REPORT.summary.dayStart}T00:00:00`);
    date.setDate(date.getDate() + dayIndex);
    return date;
}

function isoDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function dayLabel(dayIndex) {
    return isoDate(addDays(dayIndex));
}

function addHours(hourIndex) {
    const date = new Date(`${REPORT.summary.dayStart}T00:00:00`);
    date.setHours(date.getHours() + hourIndex);
    return date;
}

function hourLabel(hourIndex) {
    const date = addHours(hourIndex);
    return `${isoDate(date)} ${String(date.getHours()).padStart(2, "0")}:00`;
}

function bucketLabel(bucket) {
    if (bucket.label) {
        return bucket.label;
    }
    if (bucket.endDay <= bucket.startDay) {
        return dayLabel(bucket.startDay);
    }
    return `${dayLabel(bucket.startDay)} to ${dayLabel(bucket.endDay)}`;
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function reportEndDate() {
    return (REPORT.summary.timelineEnd || REPORT.summary.dayStart || "").slice(0, 10);
}

function dayIndexFromDate(value) {
    if (!value || !REPORT.summary.dayStart) {
        return null;
    }

    const start = new Date(`${REPORT.summary.dayStart}T00:00:00`);
    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) {
        return null;
    }

    return Math.round((date - start) / 86400000);
}

function dateFromDayIndex(dayIndex) {
    return dayLabel(clamp(Math.round(dayIndex), 0, Math.max(0, REPORT.summary.dayCount - 1)));
}

function selectedRange() {
    const maxDay = Math.max(0, REPORT.summary.dayCount - 1);
    let startDay = dayIndexFromDate(state.rangeStart);
    let endDay = dayIndexFromDate(state.rangeEnd);

    if (startDay === null) {
        startDay = 0;
    }
    if (endDay === null) {
        endDay = maxDay;
    }

    startDay = clamp(startDay, 0, maxDay);
    endDay = clamp(endDay, 0, maxDay);
    if (startDay > endDay) {
        [startDay, endDay] = [endDay, startDay];
    }

    return { startDay, endDay };
}

function setRangeDays(startDay, endDay, preset) {
    const maxDay = Math.max(0, REPORT.summary.dayCount - 1);
    startDay = clamp(Math.round(startDay), 0, maxDay);
    endDay = clamp(Math.round(endDay), 0, maxDay);
    if (startDay > endDay) {
        [startDay, endDay] = [endDay, startDay];
    }

    state.rangeStart = dateFromDayIndex(startDay);
    state.rangeEnd = dateFromDayIndex(endDay);
    state.rangePreset = preset || "custom";
    syncRangeControls();
}

function setRangePreset(value) {
    if (value === "custom") {
        state.rangePreset = "custom";
        syncRangeControls();
        return;
    }

    const maxDay = Math.max(0, REPORT.summary.dayCount - 1);
    let startDay = 0;
    let endDay = maxDay;

    if (value === "30d") {
        startDay = Math.max(0, maxDay - 29);
    } else if (value === "90d") {
        startDay = Math.max(0, maxDay - 89);
    } else if (value === "180d") {
        startDay = Math.max(0, maxDay - 179);
    } else if (value === "365d") {
        startDay = Math.max(0, maxDay - 364);
    }

    setRangeDays(startDay, endDay, value);
}

function syncRangeControls() {
    const startInput = document.getElementById("plotRangeStart");
    const endInput = document.getElementById("plotRangeEnd");
    const preset = document.getElementById("plotRangePreset");
    if (startInput) {
        startInput.value = state.rangeStart || "";
    }
    if (endInput) {
        endInput.value = state.rangeEnd || "";
    }
    if (preset) {
        preset.value = state.rangePreset || "custom";
    }
}

function plotColor(index) {
    return plotColors[index % plotColors.length];
}

function streamPlotLabel(stream) {
    if (!stream) {
        return "";
    }
    const unit = stream.unit ? ` (${stream.unit})` : "";
    return `${stream.variable}${unit} / ${stream.scopeLabel}`;
}

function pickerMode() {
    return state.group === "variable" ? "variable" : "scopeType";
}

function pickerModeLabel(mode) {
    return mode === "variable" ? "Variable" : "Scope type";
}

function pickerGroupValue(stream, mode) {
    return mode === "variable" ? stream.variable : stream.scopeType;
}

function pickerGroupLabel(value, count, mode) {
    return mode === "variable"
        ? `${value} (${count})`
        : `${value} (${count})`;
}

function pickerStreamLabel(stream) {
    return `${streamPlotLabel(stream)} - ${stream.id}`;
}

function groupedPicker(prefix, selectedId, stateKey, streams) {
    const mode = pickerMode();
    const candidates = streams.filter((stream) => stream.loaded).sort(scopeCompare);
    const counts = new Map();
    for (const stream of candidates) {
        const value = pickerGroupValue(stream, mode);
        counts.set(value, (counts.get(value) || 0) + 1);
    }
    const groups = Array.from(counts.keys()).sort(naturalCompare);
    let selectedGroup = state[stateKey];
    const selectedStream = streamsById.get(selectedId);
    if (!selectedGroup && selectedStream) {
        selectedGroup = pickerGroupValue(selectedStream, mode);
    }
    if (!groups.includes(selectedGroup)) {
        selectedGroup = groups[0] || "";
    }
    state[stateKey] = selectedGroup;

    const groupSelect = make("select", "plot-group-select");
    groupSelect.id = `${prefix}Group`;
    for (const group of groups) {
        const option = document.createElement("option");
        option.value = group;
        option.textContent = pickerGroupLabel(group, counts.get(group), mode);
        groupSelect.append(option);
    }
    groupSelect.value = selectedGroup;
    groupSelect.addEventListener("change", (event) => {
        state[stateKey] = event.target.value;
        renderPlotPanel();
    });

    const streamSelect = make("select", "plot-stream-select");
    streamSelect.id = `${prefix}Stream`;
    const groupedStreams = candidates.filter((stream) => pickerGroupValue(stream, mode) === selectedGroup);
    for (const stream of groupedStreams) {
        const option = document.createElement("option");
        option.value = stream.id;
        option.textContent = pickerStreamLabel(stream);
        streamSelect.append(option);
    }
    if (selectedId && groupedStreams.some((stream) => stream.id === selectedId)) {
        streamSelect.value = selectedId;
    }

    return { groupSelect, streamSelect, mode };
}

function isCountStream(stream) {
    return Boolean(stream && (stream.variable === "impulse" || stream.unit === "count"));
}

function isValueStream(stream) {
    return !isCountStream(stream);
}

function metricName(stream) {
    return isCountStream(stream) ? "count" : "avg";
}

function metricDescription(stream) {
    return isCountStream(stream) ? "bucket count" : "bucket average";
}

function metricValue(stream, bucket) {
    return isCountStream(stream) ? bucket.count : bucket.avg;
}

function formatMetricValue(stream, value) {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return "n/a";
    }
    if (isCountStream(stream)) {
        return formatNumber(Math.round(value));
    }
    return String(Number(value.toFixed(3)));
}

function axisValueLabel(seriesList, value) {
    if (seriesList.length && seriesList.every((series) => isCountStream(series.stream))) {
        return formatNumber(Math.round(value));
    }
    return String(Number(value.toFixed(3)));
}

function ensurePlotStreams() {
    if (state.plotIds.length === 0 && state.selectedId) {
        state.plotIds = [state.selectedId];
    }
}

function bucketOptionsForCurrentPlot() {
    if (state.plotKind === "band") {
        return [];
    }
    if (state.plotKind === "scatter") {
        return [["hourly", "Hourly"], ["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"]];
    }
    return [["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"]];
}

function normalizePlotBucket() {
    const options = bucketOptionsForCurrentPlot().map(([value]) => value);
    if (!options.length) {
        return;
    }
    if (!options.includes(state.plotBucket)) {
        state.plotBucket = options.includes("daily") ? "daily" : options[0];
    }
}

function bandBinOptions(period) {
    if (period === "year") {
        return [["month", "Month"], ["day", "Day"], ["hour", "Hour"]];
    }
    if (period === "month") {
        return [["day", "Day"], ["hour", "Hour"]];
    }
    return [["hour", "Hour"]];
}

function normalizeBandControls() {
    if (!["day", "month", "year"].includes(state.bandPeriod)) {
        state.bandPeriod = "day";
    }
    const options = bandBinOptions(state.bandPeriod).map(([value]) => value);
    if (!options.includes(state.bandBin)) {
        state.bandBin = options[0];
    }
}

function choiceLabel(options, value) {
    const match = options.find(([optionValue]) => optionValue === value);
    return match ? match[1] : value;
}

function bandPeriodLabel() {
    return choiceLabel([["day", "Day"], ["month", "Month"], ["year", "Year"]], state.bandPeriod);
}

function bandBinLabel() {
    return choiceLabel(bandBinOptions(state.bandPeriod), state.bandBin);
}

function bandProfileLabel() {
    return `${bandPeriodLabel().toLowerCase()} profile, ${bandBinLabel().toLowerCase()} bins`;
}

function monthShortName(index) {
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][index] || "";
}

function dayOfYear(date) {
    const start = new Date(date.getFullYear(), 0, 1);
    return Math.floor((date - start) / 86400000);
}

function bandAxisConfig() {
    if (state.bandPeriod === "day") {
        return { min: 0, max: 24, startLabel: "00:00", endLabel: "24:00", title: "hour of day" };
    }
    if (state.bandPeriod === "month" && state.bandBin === "hour") {
        return { min: 0, max: 31 * 24, startLabel: "day 1 00:00", endLabel: "day 31 24:00", title: "hour of month" };
    }
    if (state.bandPeriod === "month") {
        return { min: 0, max: 31, startLabel: "day 1", endLabel: "day 31", title: "day of month" };
    }
    if (state.bandBin === "hour") {
        return { min: 0, max: 366 * 24, startLabel: "Jan 1 00:00", endLabel: "Dec 31 24:00", title: "hour of year" };
    }
    if (state.bandBin === "day") {
        return { min: 0, max: 366, startLabel: "Jan 1", endLabel: "Dec 31", title: "day of year" };
    }
    return { min: 0, max: 12, startLabel: "Jan", endLabel: "Dec", title: "month of year" };
}

function bandBucketInfo(date) {
    const hour = date.getHours();
    if (state.bandPeriod === "day") {
        return {
            key: `hour-${hour}`,
            xStart: hour,
            xEnd: hour + 1,
            label: `${String(hour).padStart(2, "0")}:00`
        };
    }

    const dayOfMonth = date.getDate();
    if (state.bandPeriod === "month" && state.bandBin === "hour") {
        const hourOfMonth = (dayOfMonth - 1) * 24 + hour;
        return {
            key: `month-hour-${hourOfMonth}`,
            xStart: hourOfMonth,
            xEnd: hourOfMonth + 1,
            label: `day ${dayOfMonth} ${String(hour).padStart(2, "0")}:00`
        };
    }
    if (state.bandPeriod === "month") {
        return {
            key: `month-day-${dayOfMonth}`,
            xStart: dayOfMonth - 1,
            xEnd: dayOfMonth,
            label: `day ${dayOfMonth}`
        };
    }

    const month = date.getMonth();
    const doy = dayOfYear(date);
    if (state.bandBin === "hour") {
        const hourOfYear = doy * 24 + hour;
        return {
            key: `year-hour-${hourOfYear}`,
            xStart: hourOfYear,
            xEnd: hourOfYear + 1,
            label: `${monthShortName(month)} ${date.getDate()} ${String(hour).padStart(2, "0")}:00`
        };
    }
    if (state.bandBin === "day") {
        return {
            key: `year-day-${doy}`,
            xStart: doy,
            xEnd: doy + 1,
            label: `${monthShortName(month)} ${date.getDate()}`
        };
    }
    return {
        key: `year-month-${month}`,
        xStart: month,
        xEnd: month + 1,
        label: monthShortName(month)
    };
}

function aggregateProfileBins(streamId, range) {
    const bins = (REPORT.hourBins || {})[streamId] || [];
    const groups = new Map();

    for (const bin of bins) {
        const hourIndex = bin[0];
        const startDay = hourIndex / 24;
        if (range && (startDay < range.startDay || startDay >= range.endDay + 1)) {
            continue;
        }

        const count = bin[1];
        const avgValue = bin[4];
        const valueSum = bin.length > 5 && bin[5] !== null
            ? bin[5]
            : (avgValue !== null && Number.isFinite(avgValue) ? avgValue * count : null);
        const valueSquareSum = bin.length > 6 ? bin[6] : null;
        if (
            valueSum === null
            || valueSquareSum === null
            || !Number.isFinite(valueSum)
            || !Number.isFinite(valueSquareSum)
            || count <= 0
        ) {
            continue;
        }

        const info = bandBucketInfo(addHours(hourIndex));
        if (!groups.has(info.key)) {
            groups.set(info.key, {
                key: info.key,
                xStart: info.xStart,
                xEnd: info.xEnd,
                label: info.label,
                count: 0,
                valueSum: 0,
                valueSquareSum: 0
            });
        }
        const group = groups.get(info.key);
        group.count += count;
        group.valueSum += valueSum;
        group.valueSquareSum += valueSquareSum;
    }

    return Array.from(groups.values())
        .sort((a, b) => a.xStart - b.xStart)
        .map((group) => {
            const avg = group.count > 0 ? group.valueSum / group.count : null;
            let std = null;
            let sem = null;
            if (group.count > 1) {
                const variance = Math.max(
                    0,
                    (group.valueSquareSum - ((group.valueSum * group.valueSum) / group.count))
                    / (group.count - 1)
                );
                std = Math.sqrt(variance);
                sem = std / Math.sqrt(group.count);
            } else if (group.count === 1) {
                std = 0;
                sem = 0;
            }
            return {
                ...group,
                xMid: group.xStart + ((group.xEnd - group.xStart) / 2),
                avg,
                std,
                sem
            };
        });
}

function bucketSpanDays(bucket) {
    return bucket.spanDays || Math.max(1, bucket.endDay - bucket.startDay + 1);
}

function bucketMiddleDay(bucket) {
    return bucket.startDay + (bucketSpanDays(bucket) / 2);
}

function aggregateBins(streamId, bucketMode, range) {
    const useHourly = bucketMode === "hourly";
    const binsByStream = useHourly ? (REPORT.hourBins || {}) : REPORT.bins;
    const bins = binsByStream[streamId] || [];
    const groups = new Map();

    for (const bin of bins) {
        const rawIndex = bin[0];
        const startDay = useHourly ? rawIndex / 24 : rawIndex;
        const endDay = useHourly ? rawIndex / 24 : rawIndex;
        const spanDays = useHourly ? (1 / 24) : 1;
        if (range && useHourly && (startDay < range.startDay || startDay >= range.endDay + 1)) {
            continue;
        }
        if (range && !useHourly && (startDay < range.startDay || startDay > range.endDay)) {
            continue;
        }

        const count = bin[1];
        const minValue = bin[2];
        const maxValue = bin[3];
        const avgValue = bin[4];
        const valueSum = bin.length > 5 && bin[5] !== null
            ? bin[5]
            : (avgValue !== null && Number.isFinite(avgValue) ? avgValue * count : null);
        const valueSquareSum = bin.length > 6 ? bin[6] : null;
        const date = useHourly ? addHours(rawIndex) : addDays(rawIndex);

        let key;
        let label = "";
        if (bucketMode === "hourly") {
            key = `hour-${rawIndex}`;
            label = hourLabel(rawIndex);
        } else if (bucketMode === "yearly") {
            key = `${date.getFullYear()}`;
        } else if (bucketMode === "monthly") {
            key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
        } else if (bucketMode === "weekly") {
            key = `week-${Math.floor(rawIndex / 7)}`;
        } else {
            key = `day-${rawIndex}`;
        }

        if (!groups.has(key)) {
            groups.set(key, {
                key,
                startDay,
                endDay,
                spanDays: 0,
                count: 0,
                min: null,
                max: null,
                weightedSum: 0,
                avgWeight: 0,
                valueSum: 0,
                valueSquareSum: 0,
                varianceWeight: 0,
                label
            });
        }

        const group = groups.get(key);
        group.startDay = Math.min(group.startDay, startDay);
        group.endDay = Math.max(group.endDay, endDay);
        group.spanDays += spanDays;
        group.count += count;

        if (minValue !== null) {
            group.min = group.min === null ? minValue : Math.min(group.min, minValue);
        }
        if (maxValue !== null) {
            group.max = group.max === null ? maxValue : Math.max(group.max, maxValue);
        }
        if (avgValue !== null && Number.isFinite(avgValue) && count > 0) {
            group.weightedSum += avgValue * count;
            group.avgWeight += count;
        }
        if (
            valueSum !== null
            && valueSquareSum !== null
            && Number.isFinite(valueSum)
            && Number.isFinite(valueSquareSum)
            && count > 0
        ) {
            group.valueSum += valueSum;
            group.valueSquareSum += valueSquareSum;
            group.varianceWeight += count;
        }
    }

    return Array.from(groups.values())
        .sort((a, b) => a.startDay - b.startDay)
        .map((group) => {
            const avg = group.avgWeight > 0 ? group.weightedSum / group.avgWeight : null;
            let std = null;
            let sem = null;
            if (group.varianceWeight > 1) {
                const variance = Math.max(
                    0,
                    (group.valueSquareSum - ((group.valueSum * group.valueSum) / group.varianceWeight))
                    / (group.varianceWeight - 1)
                );
                std = Math.sqrt(variance);
                sem = std / Math.sqrt(group.varianceWeight);
            } else if (group.varianceWeight === 1) {
                std = 0;
                sem = 0;
            }
            return {
                key: group.key,
                startDay: group.startDay,
                endDay: group.endDay,
                spanDays: bucketMode === "hourly"
                    ? group.spanDays
                    : Math.max(1, group.endDay - group.startDay + 1),
                count: group.count,
                min: group.min,
                max: group.max,
                avg,
                std,
                sem,
                label: bucketLabel(group)
            };
        });
}

function renderInspector() {
    const inspector = document.getElementById("inspector");
    inspector.innerHTML = "";

    const stream = streamsById.get(state.selectedId);
    if (!stream) {
        inspector.append(make("h2", "", "Select a stream"));
        inspector.append(make("div", "inspector-subtitle", "Details appear here."));
        return;
    }

    const unit = stream.unit ? ` (${stream.unit})` : "";
    inspector.append(make("h2", "", `${stream.variable}${unit}`));
    inspector.append(make("div", "inspector-subtitle", stream.id));

    const actions = make("div", "inspector-actions");
    const copy = make("button", "plain-button", "Copy stream id");
    copy.type = "button";
    copy.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(stream.id);
            copy.textContent = "Copied";
        } catch (error) {
            copy.textContent = "Copy failed";
        }
        window.setTimeout(() => {
            copy.textContent = "Copy stream id";
        }, 1200);
    });
    actions.append(copy);
    inspector.append(actions);

    const grid = make("div", "metric-grid");
    grid.append(metric("Status", statusText(stream)));
    grid.append(metric("Observations", formatNumber(stream.count)));
    grid.append(metric("Scope", `${stream.scopeType}:${stream.scopeId}`));
    grid.append(metric("Last age", stream.loaded ? formatDays(stream.lastAgeDays) : ""));
    grid.append(metric("First", formatDate(stream.first)));
    grid.append(metric("Last", formatDate(stream.last)));
    grid.append(metric("Min", stream.minValue === null ? "" : String(stream.minValue)));
    grid.append(metric("Max", stream.maxValue === null ? "" : String(stream.maxValue)));
    grid.append(metric("Average", stream.avgValue === null ? "" : String(stream.avgValue)));
    inspector.append(grid);
}

function renderPlotPanel() {
    const panel = document.getElementById("plotPanel");
    panel.innerHTML = "";

    const stream = streamsById.get(state.selectedId);
    if (!stream) {
        panel.append(make("div", "empty-state", "Select a stream to plot."));
        return;
    }

    const unit = stream.unit ? ` (${stream.unit})` : "";
    const header = make("div", "plot-header");
    const titleWrap = make("div");
    titleWrap.append(make("div", "plot-title", `${stream.variable}${unit} / ${stream.scopeLabel}`));
    titleWrap.append(make("div", "plot-subtitle", `${stream.id} · ${formatNumber(stream.count)} observations`));
    header.append(titleWrap);

    const controls = make("div", "plot-controls");
    const modeOptions = [
        ["count", "Count"],
        ["value", "Value"],
        ["both", "Both"]
    ];
    const bucketOptions = [
        ["daily", "Daily"],
        ["weekly", "Weekly"],
        ["monthly", "Monthly"]
    ];

    for (const [value, label] of modeOptions) {
        const button = make("button", "plot-button", label);
        button.type = "button";
        if (state.plotMode === value) {
            button.classList.add("active");
        }
        button.addEventListener("click", () => {
            state.plotMode = value;
            renderPlotPanel();
        });
        controls.append(button);
    }

    for (const [value, label] of bucketOptions) {
        const button = make("button", "plot-button", label);
        button.type = "button";
        if (state.plotBucket === value) {
            button.classList.add("active");
        }
        button.addEventListener("click", () => {
            state.plotBucket = value;
            renderPlotPanel();
        });
        controls.append(button);
    }

    header.append(controls);
    panel.append(header);

    const frame = make("div", "plot-frame");
    const canvas = make("canvas", "plot-canvas");
    const tooltip = make("div", "plot-tooltip");
    frame.append(canvas, tooltip);
    panel.append(frame);

    const legend = make("div", "plot-legend");
    if (state.plotMode !== "value") {
        const item = make("span", "legend-item");
        item.append(make("span", "legend-swatch legend-count"), make("span", "", "observation count"));
        legend.append(item);
    }
    if (state.plotMode !== "count") {
        const item = make("span", "legend-item");
        item.append(make("span", "legend-swatch legend-value"), make("span", "", "average value"));
        legend.append(item);
    }
    panel.append(legend);

    window.requestAnimationFrame(() => drawStreamPlot(canvas, tooltip, stream));
}

function drawStreamPlot(canvas, tooltip, stream) {
    const buckets = aggregateBins(stream.id, state.plotBucket);
    const scale = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 960;
    const height = canvas.clientHeight || 340;
    canvas.width = width * scale;
    canvas.height = height * scale;
    const context = canvas.getContext("2d");
    context.scale(scale, scale);

    context.clearRect(0, 0, width, height);
    context.fillStyle = "#fbfcfe";
    context.fillRect(0, 0, width, height);

    const left = 58;
    const right = 34;
    const top = 24;
    const bottom = 46;
    const chartWidth = width - left - right;
    const chartHeight = height - top - bottom;
    const dayCount = Math.max(1, REPORT.summary.dayCount || 1);
    const maxCount = Math.max(...buckets.map((bucket) => bucket.count), 0);
    const valueBuckets = buckets.filter((bucket) => bucket.avg !== null && Number.isFinite(bucket.avg));
    const valueMin = valueBuckets.length ? Math.min(...valueBuckets.map((bucket) => bucket.min ?? bucket.avg)) : null;
    const valueMax = valueBuckets.length ? Math.max(...valueBuckets.map((bucket) => bucket.max ?? bucket.avg)) : null;
    const canDrawValue = (
        valueBuckets.length > 0
        && valueMin !== null
        && valueMax !== null
        && valueMax !== valueMin
        && state.plotMode !== "count"
    );

    context.strokeStyle = "#e2e8f0";
    context.lineWidth = 1;

    for (let index = 0; index <= 4; index += 1) {
        const y = top + (chartHeight * index / 4);
        context.beginPath();
        context.moveTo(left, y);
        context.lineTo(left + chartWidth, y);
        context.stroke();
    }

    context.strokeStyle = "#cbd5e1";
    context.beginPath();
    context.moveTo(left, top);
    context.lineTo(left, top + chartHeight);
    context.lineTo(left + chartWidth, top + chartHeight);
    context.stroke();

    if (!buckets.length || maxCount === 0) {
        context.fillStyle = "#64748b";
        context.font = "12px Arial";
        context.fillText("No observations", left + 8, top + 24);
        return;
    }

    if (state.plotMode !== "value") {
        context.fillStyle = "rgba(15, 118, 110, 0.72)";
        for (const bucket of buckets) {
            const x = left + (bucket.startDay * chartWidth / dayCount);
            const span = Math.max(1, bucket.endDay - bucket.startDay + 1);
            const barWidth = Math.max(2, span * chartWidth / dayCount - 1);
            const barHeight = Math.max(1, bucket.count * chartHeight / maxCount);
            context.fillRect(x, top + chartHeight - barHeight, barWidth, barHeight);
        }
    }

    if (canDrawValue) {
        context.strokeStyle = "#b45309";
        context.lineWidth = 2;
        context.beginPath();
        let started = false;
        for (const bucket of buckets) {
            if (bucket.avg === null || !Number.isFinite(bucket.avg)) {
                continue;
            }
            const middleDay = bucket.startDay + ((bucket.endDay - bucket.startDay + 1) / 2);
            const x = left + (middleDay * chartWidth / dayCount);
            const y = top + chartHeight - (
                (bucket.avg - valueMin)
                * chartHeight
                / (valueMax - valueMin)
            );
            if (!started) {
                context.moveTo(x, y);
                started = true;
            } else {
                context.lineTo(x, y);
            }
        }
        context.stroke();
    } else if (state.plotMode === "value") {
        context.fillStyle = "#64748b";
        context.font = "12px Arial";
        context.textAlign = "left";
        context.fillText("No varying value preview for this stream", left + 8, top + 24);
    }

    context.fillStyle = "#64748b";
    context.font = "11px Arial";
    context.textAlign = "left";
    context.fillText(REPORT.summary.dayStart || "", left, height - 16);
    context.textAlign = "right";
    context.fillText((REPORT.summary.timelineEnd || "").slice(0, 10), left + chartWidth, height - 16);
    context.textAlign = "left";
    context.fillText(formatNumber(maxCount), 8, top + 4);
    context.fillText("0", 8, top + chartHeight);

    if (canDrawValue) {
        context.fillStyle = "#b45309";
        context.textAlign = "right";
        context.fillText(String(Number(valueMax.toFixed(3))), width - 6, top + 4);
        context.fillText(String(Number(valueMin.toFixed(3))), width - 6, top + chartHeight);
    }

    canvas._plot = {
        buckets,
        left,
        top,
        chartWidth,
        chartHeight,
        dayCount,
        maxCount,
        canDrawValue,
        valueMin,
        valueMax
    };
    wirePlotHover(canvas, tooltip);
}

function nearestBucket(buckets, day) {
    let best = null;
    let bestDistance = Infinity;
    for (const bucket of buckets) {
        const middle = bucket.startDay + ((bucket.endDay - bucket.startDay) / 2);
        const distance = day >= bucket.startDay && day <= bucket.endDay
            ? 0
            : Math.abs(day - middle);
        if (distance < bestDistance) {
            bestDistance = distance;
            best = bucket;
        }
    }
    return best;
}

function nearestProfileBucket(buckets, xValue) {
    let best = null;
    let bestDistance = Infinity;
    for (const bucket of buckets) {
        const middle = bucket.xMid ?? (bucket.xStart + ((bucket.xEnd - bucket.xStart) / 2));
        const distance = xValue >= bucket.xStart && xValue <= bucket.xEnd
            ? 0
            : Math.abs(xValue - middle);
        if (distance < bestDistance) {
            bestDistance = distance;
            best = bucket;
        }
    }
    return best;
}

function wirePlotHover(canvas, tooltip) {
    canvas.onmouseleave = () => {
        tooltip.style.display = "none";
    };

    canvas.onmousemove = (event) => {
        const plot = canvas._plot;
        if (!plot || !plot.buckets.length) {
            tooltip.style.display = "none";
            return;
        }

        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        if (
            x < plot.left
            || x > plot.left + plot.chartWidth
            || y < plot.top
            || y > plot.top + plot.chartHeight
        ) {
            tooltip.style.display = "none";
            return;
        }

        const day = (x - plot.left) * plot.dayCount / plot.chartWidth;
        const bucket = nearestBucket(plot.buckets, day);
        if (!bucket) {
            tooltip.style.display = "none";
            return;
        }

        const valueLine = bucket.avg === null
            ? ""
            : `<br>avg ${Number(bucket.avg.toFixed(3))}, min ${bucket.min}, max ${bucket.max}`;
        tooltip.innerHTML = `${bucket.label}<br>${formatNumber(bucket.count)} observations${valueLine}`;
        tooltip.style.display = "block";
        tooltip.style.left = `${clamp(x + 12, 8, rect.width - 260)}px`;
        tooltip.style.top = `${clamp(y + 12, 8, rect.height - 74)}px`;
    };
}

function renderPlotPanel() {
    const panel = document.getElementById("plotPanel");
    panel.innerHTML = "";
    ensurePlotStreams();

    const plottedStreams = state.plotIds
        .map((streamId) => streamsById.get(streamId))
        .filter(Boolean);
    const primaryStream = streamsById.get(state.selectedId) || plottedStreams[0];
    const valueStreams = plottedStreams.filter(isValueStream);
    const hasValueStreams = valueStreams.length > 0;
    if (state.plotKind === "band" && !hasValueStreams) {
        state.plotKind = "timeseries";
    }
    normalizePlotBucket();
    normalizeBandControls();
    panel.classList.toggle("scatter-mode", state.plotKind === "scatter");

    if (!primaryStream) {
        panel.append(make("div", "empty-state", "Select a stream to plot."));
        return;
    }

    const header = make("div", "plot-header");
    const titleWrap = make("div");
    const title = state.plotKind === "scatter"
        ? "Scatter plot"
        : state.plotKind === "band"
            ? valueStreams.length === 1
                ? `${streamPlotLabel(valueStreams[0])} ${bandProfileLabel()}`
                : `${valueStreams.length} ${bandProfileLabel()} bands`
        : plottedStreams.length === 1
            ? streamPlotLabel(plottedStreams[0])
            : `${plottedStreams.length} plotted streams`;
    titleWrap.append(make("div", "plot-title", title));
    titleWrap.append(make("div", "plot-subtitle", plottedStreams.map((stream) => stream.id).join(" | ")));
    header.append(titleWrap);

    const controls = make("div", "plot-controls");
    const plotKindOptions = [["timeseries", "Timeline"]];
    if (hasValueStreams) {
        plotKindOptions.push(["band", "Average band"]);
    }
    plotKindOptions.push(["histogram", "Histogram"], ["scatter", "Scatter"]);
    for (const [value, label] of plotKindOptions) {
        const button = make("button", "plot-button", label);
        button.type = "button";
        if (state.plotKind === value) {
            button.classList.add("active");
        }
        button.addEventListener("click", () => {
            state.plotKind = value;
            renderPlotPanel();
        });
        controls.append(button);
    }
    for (const [value, label] of bucketOptionsForCurrentPlot()) {
        const button = make("button", "plot-button", label);
        button.type = "button";
        if (state.plotBucket === value) {
            button.classList.add("active");
        }
        button.addEventListener("click", () => {
            state.plotBucket = value;
            renderPlotPanel();
        });
        controls.append(button);
    }
    header.append(controls);
    panel.append(header);

    panel.append(renderRangeControls());
    panel.append(renderPlotStreamControls(primaryStream));
    if (state.plotKind === "band") {
        panel.append(renderSpreadControls());
    }
    panel.append(renderPlotChips(plottedStreams));
    panel.append(renderScatterControls(plottedStreams));

    const frame = make("div", "plot-frame");
    const canvas = make("canvas", "plot-canvas");
    const tooltip = make("div", "plot-tooltip");
    frame.append(canvas, tooltip);
    panel.append(frame);

    const legend = make("div", "plot-legend");
    if (state.plotKind === "scatter") {
        const xStream = streamsById.get(state.scatterAgainstId);
        if (xStream) {
            const axisItem = make("span", "legend-item");
            axisItem.append(make("span", "legend-swatch legend-value"), make("span", "", `x: ${streamPlotLabel(xStream)} ${metricName(xStream)}`));
            legend.append(axisItem);
        }
        plottedStreams.forEach((stream, index) => {
            const item = make("span", "legend-item");
            const swatch = make("span", "legend-swatch");
            swatch.style.background = plotColor(index);
            item.append(swatch, make("span", "", `y: ${streamPlotLabel(stream)} ${metricName(stream)}`));
            legend.append(item);
        });
    } else if (state.plotKind === "band") {
        plottedStreams.forEach((stream, index) => {
            if (!isValueStream(stream)) {
                return;
            }
            const item = make("span", "legend-item");
            const swatch = make("span", "legend-swatch");
            swatch.style.background = plotColor(index);
            item.append(swatch, make("span", "", `${streamPlotLabel(stream)} avg +/- ${state.spreadMode.toUpperCase()} (${bandProfileLabel()})`));
            legend.append(item);
        });
    } else {
        plottedStreams.forEach((stream, index) => {
            const item = make("span", "legend-item");
            const swatch = make("span", "legend-swatch");
            swatch.style.background = plotColor(index);
            item.append(swatch, make("span", "", `${streamPlotLabel(stream)} ${metricName(stream)}`));
            legend.append(item);
        });
    }
    panel.append(legend);

    window.requestAnimationFrame(() => drawPlot(canvas, tooltip));
}

function renderRangeControls() {
    const row = make("div", "plot-control-row");
    const preset = make("select");
    preset.id = "plotRangePreset";
    for (const [value, label] of [["all", "Full range"], ["30d", "Last 30 days"], ["90d", "Last 90 days"], ["180d", "Last 180 days"], ["365d", "Last year"], ["custom", "Custom"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        preset.append(option);
    }
    preset.value = state.rangePreset || "custom";
    preset.addEventListener("change", (event) => {
        setRangePreset(event.target.value);
        renderPlotPanel();
    });

    const startInput = make("input");
    startInput.id = "plotRangeStart";
    startInput.type = "date";
    startInput.min = REPORT.summary.dayStart || "";
    startInput.max = reportEndDate();
    startInput.value = state.rangeStart || "";
    startInput.addEventListener("change", (event) => {
        state.rangeStart = event.target.value;
        state.rangePreset = "custom";
        setRangeDays(selectedRange().startDay, selectedRange().endDay, "custom");
        renderPlotPanel();
    });

    const endInput = make("input");
    endInput.id = "plotRangeEnd";
    endInput.type = "date";
    endInput.min = REPORT.summary.dayStart || "";
    endInput.max = reportEndDate();
    endInput.value = state.rangeEnd || "";
    endInput.addEventListener("change", (event) => {
        state.rangeEnd = event.target.value;
        state.rangePreset = "custom";
        setRangeDays(selectedRange().startDay, selectedRange().endDay, "custom");
        renderPlotPanel();
    });

    row.append(make("label", "", "Range"), preset, make("label", "", "From"), startInput, make("label", "", "To"), endInput);
    return row;
}

function renderSpreadControls() {
    const row = make("div", "plot-control-row");
    normalizeBandControls();

    const periodSelect = make("select");
    periodSelect.id = "plotBandPeriod";
    for (const [value, label] of [["day", "Day"], ["month", "Month"], ["year", "Year"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        periodSelect.append(option);
    }
    periodSelect.value = state.bandPeriod;
    periodSelect.addEventListener("change", (event) => {
        state.bandPeriod = event.target.value;
        normalizeBandControls();
        renderPlotPanel();
    });

    const binSelect = make("select");
    binSelect.id = "plotBandBin";
    for (const [value, label] of bandBinOptions(state.bandPeriod)) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        binSelect.append(option);
    }
    binSelect.value = state.bandBin;
    binSelect.addEventListener("change", (event) => {
        state.bandBin = event.target.value;
        normalizeBandControls();
        renderPlotPanel();
    });

    const spreadSelect = make("select");
    spreadSelect.id = "plotSpreadMode";
    for (const [value, label] of [["std", "STD band"], ["sem", "SEM band"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        spreadSelect.append(option);
    }
    spreadSelect.value = state.spreadMode;
    spreadSelect.addEventListener("change", (event) => {
        state.spreadMode = event.target.value;
        renderPlotPanel();
    });
    row.append(
        make("label", "", "Average over"),
        periodSelect,
        make("label", "", "Bin by"),
        binSelect,
        make("label", "", "Band"),
        spreadSelect
    );
    return row;
}

function renderPlotStreamControls(primaryStream) {
    const row = make("div", "plot-control-row");
    const picker = groupedPicker("plotAdd", primaryStream.id, "addPickerGroup", loadedStreams);
    const addButton = make("button", "plain-button", "Add stream");
    addButton.type = "button";
    addButton.addEventListener("click", () => {
        const streamId = picker.streamSelect.value;
        if (streamId && !state.plotIds.includes(streamId)) {
            state.plotIds.push(streamId);
        }
        state.selectedId = streamId || state.selectedId;
        render();
    });

    const onlyButton = make("button", "plain-button", "Only selected");
    onlyButton.type = "button";
    onlyButton.addEventListener("click", () => {
        state.plotIds = state.selectedId ? [state.selectedId] : [];
        render();
    });

    row.append(
        make("label", "", `Add ${pickerModeLabel(picker.mode)}`),
        picker.groupSelect,
        make("label", "", "Stream"),
        picker.streamSelect,
        addButton,
        onlyButton
    );
    return row;
}

function renderPlotChips(plottedStreams) {
    const row = make("div", "plot-chip-row");
    plottedStreams.forEach((stream, index) => {
        const chip = make("span", "plot-chip");
        const swatch = make("span", "plot-swatch");
        swatch.style.background = plotColor(index);
        const remove = make("button", "", "x");
        remove.type = "button";
        remove.addEventListener("click", () => {
            state.plotIds = state.plotIds.filter((streamId) => streamId !== stream.id);
            if (state.selectedId === stream.id) {
                state.selectedId = state.plotIds[0] || null;
            }
            render();
        });
        chip.append(swatch, make("span", "", streamPlotLabel(stream)), remove);
        row.append(chip);
    });
    return row;
}

function renderScatterControls(plottedStreams) {
    const row = make("div", "plot-control-row scatter-selects");
    const fallback = loadedStreams.find((stream) => !state.plotIds.includes(stream.id)) || loadedStreams[0];
    const picker = groupedPicker(
        "plotScatterAgainst",
        state.scatterAgainstId || fallback?.id,
        "scatterPickerGroup",
        loadedStreams
    );
    state.scatterAgainstId = picker.streamSelect.value;
    picker.streamSelect.addEventListener("change", (event) => {
        state.scatterAgainstId = event.target.value;
        renderPlotPanel();
    });
    row.append(
        make("label", "", `Scatter against ${pickerModeLabel(picker.mode)}`),
        picker.groupSelect,
        make("label", "", "Stream"),
        picker.streamSelect
    );
    return row;
}

function streamAxisSelect(id, selectedValue) {
    const select = make("select", "plot-stream-select");
    select.id = id;
    for (const stream of loadedStreams) {
        const option = document.createElement("option");
        option.value = stream.id;
        option.textContent = `${streamPlotLabel(stream)} - ${stream.id}`;
        select.append(option);
    }
    if (selectedValue && streamsById.has(selectedValue)) {
        select.value = selectedValue;
    }
    return select;
}

function plotSeries() {
    const range = selectedRange();
    return state.plotIds
        .map((streamId, index) => {
            const stream = streamsById.get(streamId);
            if (!stream) {
                return null;
            }
            return {
                stream,
                color: plotColor(index),
                buckets: aggregateBins(streamId, state.plotBucket, range)
            };
        })
        .filter(Boolean);
}

function profileSeries() {
    const range = selectedRange();
    return state.plotIds
        .map((streamId, index) => {
            const stream = streamsById.get(streamId);
            if (!stream || !isValueStream(stream)) {
                return null;
            }
            return {
                stream,
                color: plotColor(index),
                buckets: aggregateProfileBins(streamId, range)
            };
        })
        .filter(Boolean);
}

function bucketMetric(series, bucket) {
    return metricValue(series.stream, bucket);
}

function valueExtent(seriesList, metric) {
    const values = [];
    for (const series of seriesList) {
        for (const bucket of series.buckets) {
            const value = metric(bucket, series);
            if (value !== null && Number.isFinite(value)) {
                values.push(value);
            }
        }
    }
    if (!values.length) {
        return null;
    }
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (seriesList.length && seriesList.every((series) => isCountStream(series.stream))) {
        min = Math.min(0, min);
    }
    if (min === max) {
        min -= 1;
        max += 1;
    }
    return { min, max };
}

function spreadForBucket(bucket) {
    return state.spreadMode === "sem" ? bucket.sem : bucket.std;
}

function spreadLabel() {
    return state.spreadMode.toUpperCase();
}

function averageBandExtent(seriesList) {
    const values = [];
    for (const series of seriesList.filter((series) => isValueStream(series.stream))) {
        for (const bucket of series.buckets) {
            if (bucket.avg === null || !Number.isFinite(bucket.avg)) {
                continue;
            }
            const spread = spreadForBucket(bucket);
            if (spread !== null && Number.isFinite(spread)) {
                values.push(bucket.avg - spread, bucket.avg + spread);
            } else {
                values.push(bucket.avg);
            }
        }
    }
    if (!values.length) {
        return null;
    }
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) {
        min -= 1;
        max += 1;
    }
    return { min, max };
}

function colorWithAlpha(hexColor, alpha) {
    const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hexColor);
    if (!match) {
        return `rgba(37, 99, 235, ${alpha})`;
    }
    const red = parseInt(match[1], 16);
    const green = parseInt(match[2], 16);
    const blue = parseInt(match[3], 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function drawPlot(canvas, tooltip) {
    const seriesList = state.plotKind === "band" ? [] : plotSeries();
    const scale = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 960;
    const height = canvas.clientHeight || 340;
    canvas.width = width * scale;
    canvas.height = height * scale;
    const context = canvas.getContext("2d");
    context.scale(scale, scale);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#fbfcfe";
    context.fillRect(0, 0, width, height);

    if (state.plotKind === "histogram") {
        drawHistogramPlot(canvas, tooltip, context, seriesList, width, height);
    } else if (state.plotKind === "band") {
        drawAverageBandPlot(canvas, tooltip, context, seriesList, width, height);
    } else if (state.plotKind === "scatter") {
        drawScatterPlot(canvas, tooltip, context, width, height);
    } else {
        drawTimeSeriesPlot(canvas, tooltip, context, seriesList, width, height);
    }
}

function chartArea(width, height) {
    const left = 58;
    const right = 34;
    const top = 24;
    const bottom = 70;
    return { left, right, top, bottom, chartWidth: width - left - right, chartHeight: height - top - bottom };
}

function drawAxes(context, area) {
    context.strokeStyle = "#e2e8f0";
    context.lineWidth = 1;
    for (let index = 0; index <= 4; index += 1) {
        const y = area.top + (area.chartHeight * index / 4);
        context.beginPath();
        context.moveTo(area.left, y);
        context.lineTo(area.left + area.chartWidth, y);
        context.stroke();
    }
    context.strokeStyle = "#cbd5e1";
    context.beginPath();
    context.moveTo(area.left, area.top);
    context.lineTo(area.left, area.top + area.chartHeight);
    context.lineTo(area.left + area.chartWidth, area.top + area.chartHeight);
    context.stroke();
}

function drawRangeRail(context, area, width, height) {
    const maxDay = Math.max(1, REPORT.summary.dayCount - 1);
    const range = selectedRange();
    const railY = height - 32;
    const startX = area.left + (range.startDay * area.chartWidth / maxDay);
    const endX = area.left + (range.endDay * area.chartWidth / maxDay);

    context.strokeStyle = "#cbd5e1";
    context.lineWidth = 4;
    context.beginPath();
    context.moveTo(area.left, railY);
    context.lineTo(area.left + area.chartWidth, railY);
    context.stroke();

    context.strokeStyle = "#2563eb";
    context.beginPath();
    context.moveTo(startX, railY);
    context.lineTo(endX, railY);
    context.stroke();

    context.fillStyle = "#2563eb";
    for (const x of [startX, endX]) {
        context.beginPath();
        context.moveTo(x, railY - 9);
        context.lineTo(x - 6, railY + 3);
        context.lineTo(x + 6, railY + 3);
        context.closePath();
        context.fill();
    }

    context.fillStyle = "#64748b";
    context.font = "11px Arial";
    context.textAlign = "left";
    context.fillText(REPORT.summary.dayStart || "", area.left, height - 10);
    context.textAlign = "right";
    context.fillText(reportEndDate(), area.left + area.chartWidth, height - 10);

    return { y: railY, startX, endX, left: area.left, width: area.chartWidth };
}

function drawTimeSeriesPlot(canvas, tooltip, context, seriesList, width, height) {
    const area = chartArea(width, height);
    const range = selectedRange();
    const rangeDays = Math.max(1, range.endDay - range.startDay + 1);
    const valueMetric = (bucket, series) => metricValue(series.stream, bucket);
    const extent = valueExtent(seriesList, valueMetric);
    drawAxes(context, area);

    if (!seriesList.length || !extent) {
        context.fillStyle = "#64748b";
        context.font = "12px Arial";
        context.textAlign = "left";
        context.fillText("No plottable data in this range", area.left + 8, area.top + 24);
        const rail = drawRangeRail(context, area, width, height);
        canvas._plot = { kind: "timeseries", rail, range, seriesList, area, valueMetric };
        wirePlotPointer(canvas, tooltip);
        return;
    }

    for (const series of seriesList) {
        if (isCountStream(series.stream)) {
            context.fillStyle = colorWithAlpha(series.color, 0.34);
            for (const bucket of series.buckets) {
                const value = valueMetric(bucket, series);
                if (value === null || !Number.isFinite(value)) {
                    continue;
                }
                const x = area.left + ((bucket.startDay - range.startDay) * area.chartWidth / rangeDays);
                const span = bucketSpanDays(bucket);
                const barWidth = Math.max(2, span * area.chartWidth / rangeDays - 1);
                const barHeight = Math.max(1, (value - extent.min) * area.chartHeight / (extent.max - extent.min));
                context.fillRect(x, area.top + area.chartHeight - barHeight, barWidth, barHeight);
            }
            continue;
        }

        context.strokeStyle = series.color;
        context.lineWidth = 2;
        context.beginPath();
        let started = false;
        for (const bucket of series.buckets) {
            const value = valueMetric(bucket, series);
            if (value === null || !Number.isFinite(value)) {
                continue;
            }
            const middleDay = bucketMiddleDay(bucket);
            const x = area.left + ((middleDay - range.startDay) * area.chartWidth / rangeDays);
            const y = area.top + area.chartHeight - ((value - extent.min) * area.chartHeight / (extent.max - extent.min));
            if (!started) {
                context.moveTo(x, y);
                started = true;
            } else {
                context.lineTo(x, y);
            }
        }
        context.stroke();
    }

    context.fillStyle = "#64748b";
    context.font = "11px Arial";
    context.textAlign = "left";
    context.fillText(axisValueLabel(seriesList, extent.max), 8, area.top + 4);
    context.fillText(axisValueLabel(seriesList, extent.min), 8, area.top + area.chartHeight);
    context.fillText(dayLabel(range.startDay), area.left, height - 50);
    context.textAlign = "right";
    context.fillText(dayLabel(range.endDay), area.left + area.chartWidth, height - 50);

    const rail = drawRangeRail(context, area, width, height);
    canvas._plot = { kind: "timeseries", rail, range, area, seriesList, extent, valueMetric };
    wirePlotPointer(canvas, tooltip);
}

function drawProfileAxis(context, area, height, axis) {
    context.fillStyle = "#64748b";
    context.font = "11px Arial";
    context.textAlign = "left";
    context.fillText(axis.startLabel, area.left, height - 50);
    context.textAlign = "right";
    context.fillText(axis.endLabel, area.left + area.chartWidth, height - 50);
    context.textAlign = "center";
    context.fillText(axis.title, area.left + area.chartWidth / 2, height - 50);
}

function drawAverageBandPlot(canvas, tooltip, context, seriesList, width, height) {
    const area = chartArea(width, height);
    const range = selectedRange();
    const valueSeriesList = profileSeries();
    const axis = bandAxisConfig();
    const axisSpan = Math.max(1, axis.max - axis.min);
    const extent = averageBandExtent(valueSeriesList);
    drawAxes(context, area);

    if (!valueSeriesList.length || !extent) {
        context.fillStyle = "#64748b";
        context.font = "12px Arial";
        context.textAlign = "left";
        context.fillText("No average-band data in this range", area.left + 8, area.top + 24);
        drawProfileAxis(context, area, height, axis);
        canvas._plot = { kind: "band", range, area, axis, seriesList: valueSeriesList, extent, valueMetric: (bucket) => bucket.avg };
        wirePlotPointer(canvas, tooltip);
        return;
    }

    for (const series of valueSeriesList) {
        const points = [];
        for (const bucket of series.buckets) {
            if (bucket.avg === null || !Number.isFinite(bucket.avg)) {
                continue;
            }
            const spread = spreadForBucket(bucket);
            const safeSpread = spread !== null && Number.isFinite(spread) ? spread : 0;
            const x = area.left + ((bucket.xMid - axis.min) * area.chartWidth / axisSpan);
            const yAvg = area.top + area.chartHeight - ((bucket.avg - extent.min) * area.chartHeight / (extent.max - extent.min));
            const yHigh = area.top + area.chartHeight - (((bucket.avg + safeSpread) - extent.min) * area.chartHeight / (extent.max - extent.min));
            const yLow = area.top + area.chartHeight - (((bucket.avg - safeSpread) - extent.min) * area.chartHeight / (extent.max - extent.min));
            points.push({ x, yAvg, yHigh, yLow, bucket });
        }

        if (!points.length) {
            continue;
        }

        context.fillStyle = colorWithAlpha(series.color, 0.16);
        context.strokeStyle = colorWithAlpha(series.color, 0.32);
        context.lineWidth = 1;
        if (points.length > 1) {
            context.beginPath();
            points.forEach((point, index) => {
                if (index === 0) {
                    context.moveTo(point.x, point.yHigh);
                } else {
                    context.lineTo(point.x, point.yHigh);
                }
            });
            for (let index = points.length - 1; index >= 0; index -= 1) {
                const point = points[index];
                context.lineTo(point.x, point.yLow);
            }
            context.closePath();
            context.fill();
            context.stroke();
        } else {
            const point = points[0];
            context.beginPath();
            context.moveTo(point.x, point.yHigh);
            context.lineTo(point.x, point.yLow);
            context.stroke();
        }

        context.strokeStyle = series.color;
        context.lineWidth = 2.4;
        context.beginPath();
        points.forEach((point, index) => {
            if (index === 0) {
                context.moveTo(point.x, point.yAvg);
            } else {
                context.lineTo(point.x, point.yAvg);
            }
        });
        context.stroke();

        if (points.length <= 14) {
            context.fillStyle = series.color;
            for (const point of points) {
                context.beginPath();
                context.arc(point.x, point.yAvg, 3, 0, Math.PI * 2);
                context.fill();
            }
        }
    }

    context.fillStyle = "#64748b";
    context.font = "11px Arial";
    context.textAlign = "left";
    context.fillText(String(Number(extent.max.toFixed(3))), 8, area.top + 4);
    context.fillText(String(Number(extent.min.toFixed(3))), 8, area.top + area.chartHeight);
    drawProfileAxis(context, area, height, axis);

    canvas._plot = { kind: "band", range, area, axis, seriesList: valueSeriesList, extent, valueMetric: (bucket) => bucket.avg };
    wirePlotPointer(canvas, tooltip);
}

function drawHistogramPlot(canvas, tooltip, context, seriesList, width, height) {
    const area = chartArea(width, height);
    const metric = (bucket, series) => metricValue(series.stream, bucket);
    const extent = valueExtent(seriesList, metric);
    const binCount = 24;
    drawAxes(context, area);

    if (!seriesList.length || !extent) {
        context.fillStyle = "#64748b";
        context.font = "12px Arial";
        context.textAlign = "left";
        context.fillText("No histogram data in this range", area.left + 8, area.top + 24);
        const rail = drawRangeRail(context, area, width, height);
        canvas._plot = { kind: "histogram", rail, area, seriesList: [] };
        wirePlotPointer(canvas, tooltip);
        return;
    }

    const histograms = seriesList.map((series) => {
        const counts = Array.from({ length: binCount }, () => 0);
        for (const bucket of series.buckets) {
            const value = metric(bucket, series);
            if (value === null || !Number.isFinite(value)) {
                continue;
            }
            const index = clamp(Math.floor((value - extent.min) * binCount / (extent.max - extent.min)), 0, binCount - 1);
            counts[index] += 1;
        }
        return { ...series, counts };
    });
    const maxCount = Math.max(...histograms.flatMap((histogram) => histogram.counts), 1);
    const binWidth = area.chartWidth / binCount;

    histograms.forEach((histogram, seriesIndex) => {
        context.strokeStyle = histogram.color;
        context.lineWidth = 2;
        context.beginPath();
        histogram.counts.forEach((count, index) => {
            const x = area.left + index * binWidth + binWidth / 2;
            const y = area.top + area.chartHeight - (count * area.chartHeight / maxCount);
            if (index === 0) {
                context.moveTo(x, y);
            } else {
                context.lineTo(x, y);
            }
        });
        context.stroke();
        if (seriesIndex === 0) {
            context.fillStyle = "rgba(37, 99, 235, 0.12)";
            histogram.counts.forEach((count, index) => {
                const x = area.left + index * binWidth;
                const barHeight = count * area.chartHeight / maxCount;
                context.fillRect(x, area.top + area.chartHeight - barHeight, Math.max(1, binWidth - 1), barHeight);
            });
        }
    });

    context.fillStyle = "#64748b";
    context.font = "11px Arial";
    context.textAlign = "left";
    context.fillText(axisValueLabel(seriesList, extent.min), area.left, height - 50);
    context.textAlign = "right";
    context.fillText(axisValueLabel(seriesList, extent.max), area.left + area.chartWidth, height - 50);
    context.textAlign = "left";
    context.fillText(formatNumber(maxCount), 8, area.top + 4);
    context.fillText("0", 8, area.top + area.chartHeight);

    const rail = drawRangeRail(context, area, width, height);
    canvas._plot = { kind: "histogram", rail, area, histograms, extent, binCount, binWidth };
    wirePlotPointer(canvas, tooltip);
}

function pairedScatterPoints(xSeries, ySeries) {
    const yByKey = new Map();
    for (const bucket of ySeries.buckets) {
        yByKey.set(bucket.key, bucket);
    }
    const points = [];
    for (const xBucket of xSeries.buckets) {
        const yBucket = yByKey.get(xBucket.key);
        if (!yBucket) {
            continue;
        }
        const xValue = bucketMetric(xSeries, xBucket);
        const yValue = bucketMetric(ySeries, yBucket);
        if (xValue === null || yValue === null || !Number.isFinite(xValue) || !Number.isFinite(yValue)) {
            continue;
        }
        points.push({ label: xBucket.label, xValue, yValue, xBucket, yBucket, series: ySeries });
    }
    return points;
}

function drawScatterPlot(canvas, tooltip, context, width, height) {
    const area = chartArea(width, height);
    const range = selectedRange();
    const xStream = streamsById.get(state.scatterAgainstId);
    const ySeriesList = plotSeries();
    drawAxes(context, area);

    if (!xStream || !ySeriesList.length) {
        context.fillStyle = "#64748b";
        context.font = "12px Arial";
        context.fillText("Choose a stream to scatter against.", area.left + 8, area.top + 24);
        return;
    }

    const xSeries = { stream: xStream, buckets: aggregateBins(xStream.id, state.plotBucket, range) };
    const points = ySeriesList.flatMap((series) => pairedScatterPoints(xSeries, series));

    if (!points.length) {
        context.fillStyle = "#64748b";
        context.font = "12px Arial";
        context.textAlign = "left";
        context.fillText("No overlapping bucketed values in this range", area.left + 8, area.top + 24);
        const rail = drawRangeRail(context, area, width, height);
        canvas._plot = { kind: "scatter", rail, area, points: [] };
        wirePlotPointer(canvas, tooltip);
        return;
    }

    let xMin = Math.min(...points.map((point) => point.xValue));
    let xMax = Math.max(...points.map((point) => point.xValue));
    let yMin = Math.min(...points.map((point) => point.yValue));
    let yMax = Math.max(...points.map((point) => point.yValue));
    if (isCountStream(xStream)) {
        xMin = Math.min(0, xMin);
    }
    if (ySeriesList.every((series) => isCountStream(series.stream))) {
        yMin = Math.min(0, yMin);
    }
    if (xMin === xMax) {
        xMin -= 1;
        xMax += 1;
    }
    if (yMin === yMax) {
        yMin -= 1;
        yMax += 1;
    }

    const plottedPoints = points.map((point) => {
        const x = area.left + ((point.xValue - xMin) * area.chartWidth / (xMax - xMin));
        const y = area.top + area.chartHeight - ((point.yValue - yMin) * area.chartHeight / (yMax - yMin));
        context.fillStyle = colorWithAlpha(point.series.color, 0.74);
        context.beginPath();
        context.arc(x, y, 3.5, 0, Math.PI * 2);
        context.fill();
        return { ...point, x, y };
    });

    context.fillStyle = "#64748b";
    context.font = "11px Arial";
    context.textAlign = "left";
    context.fillText(`${streamPlotLabel(xStream)} ${metricName(xStream)} min ${formatMetricValue(xStream, xMin)}`, area.left, height - 50);
    context.textAlign = "right";
    context.fillText(`max ${formatMetricValue(xStream, xMax)}`, area.left + area.chartWidth, height - 50);
    context.save();
    context.translate(14, area.top + area.chartHeight / 2);
    context.rotate(-Math.PI / 2);
    context.textAlign = "center";
    context.fillText(ySeriesList.length === 1
        ? `${streamPlotLabel(ySeriesList[0].stream)} ${metricName(ySeriesList[0].stream)}`
        : "plotted streams"
    , 0, 0);
    context.restore();

    const rail = drawRangeRail(context, area, width, height);
    canvas._plot = { kind: "scatter", rail, area, points: plottedPoints, xStream };
    wirePlotPointer(canvas, tooltip);
}

function findNearestPoint(points, x, y) {
    let best = null;
    let bestDistance = Infinity;
    for (const point of points) {
        const distance = Math.hypot(point.x - x, point.y - y);
        if (distance < bestDistance) {
            best = point;
            bestDistance = distance;
        }
    }
    return bestDistance <= 18 ? best : null;
}

function showTooltip(tooltip, rect, x, y, htmlText) {
    tooltip.innerHTML = htmlText;
    tooltip.style.display = "block";
    tooltip.style.left = `${clamp(x + 12, 8, rect.width - 270)}px`;
    tooltip.style.top = `${clamp(y + 12, 8, rect.height - 90)}px`;
}

function formatPlotValue(value) {
    return value === null || value === undefined || !Number.isFinite(value)
        ? "n/a"
        : String(Number(value.toFixed(3)));
}

function dayFromRailX(plot, x) {
    const maxDay = Math.max(0, REPORT.summary.dayCount - 1);
    return Math.round(clamp((x - plot.rail.left) * maxDay / plot.rail.width, 0, maxDay));
}

function activeRangeHandle(plot, x, y) {
    if (!plot.rail || Math.abs(y - plot.rail.y) > 18) {
        return null;
    }
    const startDistance = Math.abs(x - plot.rail.startX);
    const endDistance = Math.abs(x - plot.rail.endX);
    if (startDistance <= 14 || endDistance <= 14) {
        return startDistance <= endDistance ? "start" : "end";
    }
    return null;
}

function wirePlotPointer(canvas, tooltip) {
    canvas.onpointerleave = () => {
        if (!canvas._dragHandle) {
            tooltip.style.display = "none";
        }
    };
    canvas.onpointerdown = (event) => {
        const plot = canvas._plot;
        if (!plot) {
            return;
        }
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        const handle = activeRangeHandle(plot, x, y);
        if (handle) {
            canvas._dragHandle = handle;
            canvas.setPointerCapture(event.pointerId);
        }
    };
    canvas.onpointerup = (event) => {
        if (canvas._dragHandle) {
            canvas.releasePointerCapture(event.pointerId);
        }
        canvas._dragHandle = null;
    };
    canvas.onpointermove = (event) => {
        const plot = canvas._plot;
        if (!plot) {
            return;
        }
        const rect = canvas.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;

        if (canvas._dragHandle) {
            const range = selectedRange();
            const day = dayFromRailX(plot, x);
            if (canvas._dragHandle === "start") {
                setRangeDays(day, range.endDay, "custom");
            } else {
                setRangeDays(range.startDay, day, "custom");
            }
            drawPlot(canvas, tooltip);
            return;
        }

        const handle = activeRangeHandle(plot, x, y);
        canvas.style.cursor = handle ? "ew-resize" : "default";
        if (handle) {
            tooltip.style.display = "none";
            return;
        }

        if (plot.kind === "scatter") {
            const point = findNearestPoint(plot.points || [], x, y);
            if (!point) {
                tooltip.style.display = "none";
                return;
            }
            const yStream = point.series.stream;
            showTooltip(
                tooltip,
                rect,
                x,
                y,
                `${point.label}<br>${plot.xStream.id} ${metricDescription(plot.xStream)}: ${formatMetricValue(plot.xStream, point.xValue)}<br>${yStream.id} ${metricDescription(yStream)}: ${formatMetricValue(yStream, point.yValue)}`
            );
            return;
        }

        if (plot.kind === "histogram") {
            if (!plot.extent || !plot.histograms || !plot.histograms.length) {
                tooltip.style.display = "none";
                return;
            }
            if (x < plot.area.left || x > plot.area.left + plot.area.chartWidth || y < plot.area.top || y > plot.area.top + plot.area.chartHeight) {
                tooltip.style.display = "none";
                return;
            }
            const index = clamp(Math.floor((x - plot.area.left) / plot.binWidth), 0, plot.binCount - 1);
            const low = plot.extent.min + (index * (plot.extent.max - plot.extent.min) / plot.binCount);
            const high = plot.extent.min + ((index + 1) * (plot.extent.max - plot.extent.min) / plot.binCount);
            const rows = plot.histograms
                .map((histogram) => `${histogram.stream.id} ${metricDescription(histogram.stream)}: ${formatNumber(histogram.counts[index])} buckets`)
                .join("<br>");
            showTooltip(tooltip, rect, x, y, `${Number(low.toFixed(3))} to ${Number(high.toFixed(3))}<br>${rows}`);
            return;
        }

        if (plot.kind === "band") {
            if (x < plot.area.left || x > plot.area.left + plot.area.chartWidth || y < plot.area.top || y > plot.area.top + plot.area.chartHeight) {
                tooltip.style.display = "none";
                return;
            }
            const axisSpan = Math.max(1, plot.axis.max - plot.axis.min);
            const profileX = plot.axis.min + ((x - plot.area.left) * axisSpan / plot.area.chartWidth);
            const rows = [];
            let label = null;
            for (const series of plot.seriesList) {
                const bucket = nearestProfileBucket(series.buckets, profileX);
                if (!bucket || bucket.avg === null || !Number.isFinite(bucket.avg)) {
                    continue;
                }
                label = label || bucket.label;
                const spread = spreadForBucket(bucket);
                rows.push(`${series.stream.id}: avg ${formatPlotValue(bucket.avg)} +/- ${formatPlotValue(spread)} ${spreadLabel()} (${formatNumber(bucket.count)} obs)`);
            }
            if (!rows.length) {
                tooltip.style.display = "none";
                return;
            }
            showTooltip(tooltip, rect, x, y, `${label || plot.axis.title}<br>${rows.join("<br>")}`);
            return;
        }

        if (x < plot.area.left || x > plot.area.left + plot.area.chartWidth || y < plot.area.top || y > plot.area.top + plot.area.chartHeight) {
            tooltip.style.display = "none";
            return;
        }
        const rangeDays = Math.max(1, plot.range.endDay - plot.range.startDay + 1);
        const day = plot.range.startDay + ((x - plot.area.left) * rangeDays / plot.area.chartWidth);
        const rows = [];
        let label = null;
        for (const series of plot.seriesList) {
            const bucket = nearestBucket(series.buckets, day);
            if (!bucket) {
                continue;
            }
            label = label || bucket.label;
            const value = plot.valueMetric(bucket, series);
            if (isCountStream(series.stream)) {
                rows.push(`${series.stream.id}: ${formatMetricValue(series.stream, value)} events`);
            } else {
                rows.push(`${series.stream.id} ${metricDescription(series.stream)}: ${formatMetricValue(series.stream, value)} (${formatNumber(bucket.count)} obs)`);
            }
        }
        if (!rows.length) {
            tooltip.style.display = "none";
            return;
        }
        showTooltip(tooltip, rect, x, y, `${label || dayLabel(day)}<br>${rows.join("<br>")}`);
    };
}

function render() {
    renderScopeChips();
    renderMissingList();
    renderList();
    renderPlotPanel();
    renderInspector();
}

function clearFilters() {
    state.query = "";
    state.status = "all";
    state.group = "scope";
    state.sort = "scope";
    state.variable = "";
    state.scopeTypes = new Set();
    document.getElementById("searchInput").value = "";
    document.getElementById("statusFilter").value = state.status;
    document.getElementById("groupMode").value = state.group;
    document.getElementById("sortMode").value = state.sort;
    document.getElementById("variableFilter").value = state.variable;
    render();
}

function wireControls() {
    document.getElementById("searchInput").addEventListener("input", (event) => {
        state.query = event.target.value.trim().toLowerCase();
        render();
    });
    document.getElementById("statusFilter").addEventListener("change", (event) => {
        state.status = event.target.value;
        render();
    });
    document.getElementById("groupMode").addEventListener("change", (event) => {
        state.group = event.target.value;
        render();
    });
    document.getElementById("sortMode").addEventListener("change", (event) => {
        state.sort = event.target.value;
        render();
    });
    document.getElementById("variableFilter").addEventListener("change", (event) => {
        state.variable = event.target.value;
        render();
    });
    document.getElementById("clearFilters").addEventListener("click", clearFilters);
}

renderSummary();
populateVariableFilter();
wireControls();
render();
</script>
</body>
</html>
"""


def is_duckdb_file_lock_error(error):
    message = str(error).lower()
    return (
        "cannot open file" in message
        and (
            "used by another process" in message
            or "file is already open" in message
        )
    )


def format_seconds(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes}m {remaining_seconds:.0f}s"


def output(message):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def connect(read_only=False):
    started_at = perf_counter()
    next_report_at = 0
    attempts = 0

    while True:
        attempts += 1
        try:
            return duckdb.connect(DB_PATH, read_only=read_only)
        except Exception as error:
            if not is_duckdb_file_lock_error(error):
                raise

            elapsed = perf_counter() - started_at
            if elapsed >= DUCKDB_CONNECT_RETRY_SECONDS:
                raise

            if elapsed >= next_report_at:
                mode = "read-only" if read_only else "read-write"
                output(
                    "DuckDB file is locked; "
                    f"waiting to open {mode} connection "
                    f"(attempt {attempts}, elapsed {format_seconds(elapsed)})"
                )
                next_report_at = elapsed + 10

            sleep(DUCKDB_CONNECT_RETRY_INTERVAL_SECONDS)


def table_exists(con, table_name):
    return con.execute("""
    SELECT count(*)
    FROM information_schema.tables
    WHERE table_name = ?;
    """, [table_name]).fetchone()[0] > 0


def column_exists(con, table_name, column_name):
    return con.execute("""
    SELECT count(*)
    FROM information_schema.columns
    WHERE table_name = ?
      AND column_name = ?;
    """, [table_name, column_name]).fetchone()[0] > 0


def migrate_series_to_streams(con):
    if table_exists(con, "series") and not table_exists(con, "streams"):
        con.execute("ALTER TABLE series RENAME TO streams;")

    if table_exists(con, "streams") and column_exists(con, "streams", "series_id"):
        con.execute("ALTER TABLE streams RENAME COLUMN series_id TO stream_id;")

    if table_exists(con, "observations") and column_exists(con, "observations", "series_id"):
        con.execute("ALTER TABLE observations RENAME COLUMN series_id TO stream_id;")


def drop_source_from_streams(con):
    if table_exists(con, "streams") and column_exists(con, "streams", "source"):
        con.execute("ALTER TABLE streams DROP COLUMN source;")


def migrate_observation_timestamp_column(con):
    if (
        table_exists(con, "observations")
        and column_exists(con, "observations", "timestamp_utc")
        and not column_exists(con, "observations", "timestamp")
    ):
        con.execute("DROP VIEW IF EXISTS stream_availability;")
        con.execute("ALTER TABLE observations RENAME COLUMN timestamp_utc TO timestamp;")
        con.execute("""
        UPDATE observations
        SET "timestamp" = ("timestamp" AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Budapest';
        """)


def init_db():
    con = connect()

    migrate_series_to_streams(con)
    drop_source_from_streams(con)
    migrate_observation_timestamp_column(con)

    con.execute("""
    CREATE TABLE IF NOT EXISTS streams (
        stream_id TEXT PRIMARY KEY,
        variable TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        unit TEXT,
        description TEXT
    );
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS observations (
        "timestamp" TIMESTAMP NOT NULL,
        stream_id TEXT NOT NULL,
        value DOUBLE NOT NULL
    );
    """)

    con.execute("""
    CREATE OR REPLACE VIEW stream_availability AS
    SELECT
        st.stream_id,
        st.variable,
        st.scope_type,
        st.scope_id,
        st.unit,
        min(o."timestamp") AS first_observation,
        max(o."timestamp") AS last_observation,
        count(o."timestamp") AS observation_count
    FROM streams AS st
    LEFT JOIN observations AS o
        ON st.stream_id = o.stream_id
    GROUP BY
        st.stream_id,
        st.variable,
        st.scope_type,
        st.scope_id,
        st.unit;
    """)

    con.close()

    print("initialized", DB_PATH)


def load_stream_metadata():
    con = connect()

    con.execute("""
    CREATE TEMP TABLE loaded_streams AS
    SELECT
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        description
    FROM read_csv_auto(?);
    """, [STREAM_METADATA_PATH])

    con.execute("""
    DELETE FROM streams
    USING loaded_streams
    WHERE streams.stream_id = loaded_streams.stream_id;
    """)

    con.execute("""
    DELETE FROM streams
    WHERE NOT EXISTS (
        SELECT 1
        FROM loaded_streams
        WHERE loaded_streams.stream_id = streams.stream_id
    );
    """)

    con.execute("""
    INSERT INTO streams (
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        description
    )
    SELECT
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        description
    FROM loaded_streams
    ORDER BY scope_type, scope_id, variable, stream_id;
    """)

    stream_count = con.execute("SELECT count(*) FROM streams;").fetchone()[0]
    con.close()

    print("loaded stream metadata", STREAM_METADATA_PATH)
    print("stream count:", stream_count)


def show_stream_availability():
    con = connect()

    rows = con.execute("""
    SELECT
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        first_observation,
        last_observation,
        observation_count
    FROM stream_availability
    ORDER BY scope_type, scope_id, variable, stream_id;
    """).fetchall()

    con.close()

    if not rows:
        print("stream_availability is empty")
        return

    for row in rows:
        print(row)


def fetch_stream_availability():
    con = connect(read_only=True)

    rows = con.execute("""
    SELECT
        availability.stream_id,
        availability.variable,
        availability.scope_type,
        availability.scope_id,
        availability.unit,
        streams.description,
        availability.first_observation,
        availability.last_observation,
        availability.observation_count,
        value_stats.min_value,
        value_stats.max_value,
        value_stats.avg_value
    FROM stream_availability AS availability
    LEFT JOIN streams
        ON streams.stream_id = availability.stream_id
    LEFT JOIN (
        SELECT
            stream_id,
            min(value) AS min_value,
            max(value) AS max_value,
            avg(value) AS avg_value
        FROM observations
        GROUP BY stream_id
    ) AS value_stats
        ON value_stats.stream_id = availability.stream_id
    ORDER BY
        availability.scope_type,
        availability.scope_id,
        availability.variable,
        availability.stream_id;
    """).fetchall()

    con.close()
    return rows


def fetch_stream_daily_bins():
    con = connect(read_only=True)

    rows = con.execute("""
    SELECT
        stream_id,
        CAST(date_trunc('day', "timestamp") AS DATE) AS observation_day,
        count(*) AS observation_count,
        min(value) AS min_value,
        max(value) AS max_value,
        avg(value) AS avg_value,
        sum(value) AS value_sum,
        sum(value * value) AS value_square_sum
    FROM observations
    GROUP BY stream_id, observation_day
    ORDER BY stream_id, observation_day;
    """).fetchall()

    con.close()
    return rows


def fetch_stream_hourly_bins():
    con = connect(read_only=True)

    rows = con.execute("""
    SELECT
        stream_id,
        date_trunc('hour', "timestamp") AS observation_hour,
        count(*) AS observation_count,
        min(value) AS min_value,
        max(value) AS max_value,
        avg(value) AS avg_value,
        sum(value) AS value_sum,
        sum(value * value) AS value_square_sum
    FROM observations
    GROUP BY stream_id, observation_hour
    ORDER BY stream_id, observation_hour;
    """).fetchall()

    con.close()
    return rows


def format_value(value):
    if value is None:
        return ""
    return html.escape(str(value))


def json_number(value):
    if value is None:
        return None

    return round(float(value), 6)


def timestamp_text(value):
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ")

    return str(value)


def date_text(value):
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


def scope_display_label(scope_type, scope_id, description, variable):
    fallback = f"{scope_type} {scope_id}"

    if not description:
        return fallback

    suffix = f" - {variable}"
    if description.endswith(suffix):
        name = description[:-len(suffix)].strip()
        if name:
            return f"{scope_id} / {name}"

    return fallback


def build_stream_report_data():
    rows = fetch_stream_availability()
    observed_rows = [
        row for row in rows
        if row[6] is not None and row[7] is not None and row[8] > 0
    ]

    if observed_rows:
        timeline_start = min(row[6] for row in observed_rows)
        timeline_end = max(row[7] for row in observed_rows)
    else:
        timeline_start = None
        timeline_end = None

    total_seconds = 0
    if timeline_start is not None and timeline_end is not None:
        total_seconds = (timeline_end - timeline_start).total_seconds()

    start_day = timeline_start.date() if timeline_start is not None else None
    end_day = timeline_end.date() if timeline_end is not None else None
    start_hour = (
        datetime.combine(start_day, datetime.min.time())
        if start_day is not None
        else None
    )
    day_count = 0
    if start_day is not None and end_day is not None:
        day_count = (end_day - start_day).days + 1

    streams = []
    for row in rows:
        (
            stream_id,
            variable,
            scope_type,
            scope_id,
            unit,
            description,
            first_observation,
            last_observation,
            observation_count,
            min_value,
            max_value,
            avg_value,
        ) = row

        loaded = observation_count > 0
        start_percent = None
        width_percent = None
        if loaded and timeline_start is not None and total_seconds > 0:
            start_percent = (
                100
                * (first_observation - timeline_start).total_seconds()
                / total_seconds
            )
            end_percent = (
                100
                * (last_observation - timeline_start).total_seconds()
                / total_seconds
            )
            width_percent = max(end_percent - start_percent, 0.3)
        elif loaded:
            start_percent = 0
            width_percent = 100

        last_age_days = None
        if loaded and timeline_end is not None:
            last_age_days = round(
                (timeline_end - last_observation).total_seconds() / 86400,
                1,
            )

        streams.append({
            "id": stream_id,
            "variable": variable,
            "scopeType": scope_type,
            "scopeId": scope_id,
            "scopeLabel": scope_display_label(
                scope_type,
                scope_id,
                description,
                variable,
            ),
            "unit": unit,
            "description": description,
            "first": timestamp_text(first_observation),
            "last": timestamp_text(last_observation),
            "count": int(observation_count),
            "loaded": loaded,
            "startPercent": json_number(start_percent),
            "widthPercent": json_number(width_percent),
            "lastAgeDays": last_age_days,
            "minValue": json_number(min_value),
            "maxValue": json_number(max_value),
            "avgValue": json_number(avg_value),
        })

    daily_bins = {}
    if start_day is not None:
        for (
            stream_id,
            observation_day,
            observation_count,
            min_value,
            max_value,
            avg_value,
            value_sum,
            value_square_sum,
        ) in fetch_stream_daily_bins():
            if hasattr(observation_day, "date"):
                observation_day = observation_day.date()

            day_index = (observation_day - start_day).days
            if day_index < 0 or day_index >= day_count:
                continue

            daily_bins.setdefault(stream_id, []).append([
                day_index,
                int(observation_count),
                json_number(min_value),
                json_number(max_value),
                json_number(avg_value),
                json_number(value_sum),
                json_number(value_square_sum),
            ])

    hourly_bins = {}
    if start_hour is not None:
        for (
            stream_id,
            observation_hour,
            observation_count,
            min_value,
            max_value,
            avg_value,
            value_sum,
            value_square_sum,
        ) in fetch_stream_hourly_bins():
            hour_index = int((observation_hour - start_hour).total_seconds() // 3600)
            if hour_index < 0 or hour_index >= day_count * 24:
                continue

            hourly_bins.setdefault(stream_id, []).append([
                hour_index,
                int(observation_count),
                json_number(min_value),
                json_number(max_value),
                json_number(avg_value),
                json_number(value_sum),
                json_number(value_square_sum),
            ])

    total_streams = len(streams)
    loaded_streams = sum(1 for stream in streams if stream["loaded"])
    total_observations = sum(stream["count"] for stream in streams)

    return {
        "summary": {
            "generatedAt": timestamp_text(datetime.now()),
            "totalStreams": total_streams,
            "loadedStreams": loaded_streams,
            "missingStreams": total_streams - loaded_streams,
            "observations": total_observations,
            "timelineStart": timestamp_text(timeline_start),
            "timelineEnd": timestamp_text(timeline_end),
            "dayStart": date_text(start_day),
            "dayCount": day_count,
            "staleDays": 30,
        },
        "streams": streams,
        "bins": daily_bins,
        "hourBins": hourly_bins,
    }


def report_data_json(report_data):
    return json.dumps(
        report_data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")


def write_stream_timeline():
    report_data = build_stream_report_data()
    data_json = report_data_json(report_data)
    html_text = STREAM_AVAILABILITY_HTML.replace("__REPORT_DATA__", data_json)

    with open(TIMELINE_PATH, "w", encoding="utf-8") as file:
        file.write(html_text)

    print("wrote", TIMELINE_PATH)


def write_stream_availability_csv():
    con = connect()

    con.execute("""
    COPY (
        SELECT
            stream_id,
            variable,
            scope_type,
            scope_id,
            unit,
            first_observation,
            last_observation,
            observation_count
        FROM stream_availability
        ORDER BY scope_type, scope_id, variable, stream_id
    )
    TO ?
    WITH (HEADER, DELIMITER ',');
    """, [AVAILABILITY_CSV_PATH])

    con.close()

    print("wrote", AVAILABILITY_CSV_PATH)


def main():
    if MODE == "init":
        init_db()
    elif MODE == "load_stream_metadata":
        load_stream_metadata()
    elif MODE == "show_stream_availability":
        show_stream_availability()
    elif MODE == "write_stream_timeline":
        write_stream_timeline()
    elif MODE == "write_stream_availability_csv":
        write_stream_availability_csv()
    else:
        print("unknown MODE:", MODE)


if __name__ == "__main__":
    main()
