let canvasInserted = false;

function insertCanvasFromFile(fileData) {
    // Extract the original SVG element
    const drawingFile = fileData.documentElement;

    // Create a new SVG element
    const newDrawingGroup = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    newDrawingGroup.id = "canvas";
    newDrawingGroup.setAttribute("originalWidth", drawingFile.getAttribute("width"))
    newDrawingGroup.setAttribute("originalHeight", drawingFile.getAttribute("height"))
    newDrawingGroup.setAttribute("viewBox", `0 0 ${window.innerWidth} ${window.innerHeight}`);
    newDrawingGroup.setAttribute("width", "100%");  // Make SVG cover the viewport
    newDrawingGroup.setAttribute("height", "100%");

    // Select the drawing <g> element in the original SVG file
    const originalDrawingGroup = drawingFile.getElementById("drawing");
    const idioticShift = originalDrawingGroup.getAttribute("transform").match(/-?\d+\.\d+/g).map(num => Math.floor(parseFloat(num)));

    // Create a new <g> element
    const newGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");

    // Set the new group ID based on `inkscape:label`
    newGroup.id = originalDrawingGroup.getAttribute("inkscape:label"); // Use inkscape:label as the ID
    newGroup.setAttribute("idioticShiftX", idioticShift[0]); // To counteract the idiotic & unnecessary export shift of Inkscape
    newGroup.setAttribute("idioticShiftY", idioticShift[1]);

    // Clone child nodes (like paths, shapes) and append them to the new group
    originalDrawingGroup.childNodes.forEach(child => {
        if (child.nodeType === 1) {
            child.id = child.getAttribute("inkscape:label");
        }
        newGroup.appendChild(child.cloneNode(true));
    });
    initializeAmbientAreas(newGroup);

    // Room fills belong below the circuit pipes, including shapes added later.
    const children = Array.from(newGroup.children);
    const firstPipe = children.find(node => /^cycle[1-4](?:_2)?$/.test(node.id));
    if (firstPipe) {
        const pipeIndex = children.indexOf(firstPipe);
        children.forEach((node, index) => {
            if (index > pipeIndex && (/^room_\d+$/.test(node.id) || node.id === 'controlled_rooms')) {
                newGroup.insertBefore(node, firstPipe);
            }
        });
    }

    // Append the cleaned group to the new SVG
    newDrawingGroup.appendChild(newGroup);
    // Localise static SVG lettering without changing IDs or drawing geometry.
    newGroup.querySelectorAll('text, tspan').forEach(node => {
        if (!node.children.length) node.textContent = dashboardText(node.textContent);
    });


    const p5jsDrawing = document.createElementNS("http://www.w3.org/2000/svg", "g");
    p5jsDrawing.id = "p5jsDrawing";
    newDrawingGroup.appendChild(p5jsDrawing);

    // Append the new SVG to the container in the HTML
    document.getElementById("container").appendChild(newDrawingGroup);
    canvasInserted = true;
    console.log("Canvas inserted from file.");
}

function getCanvasDimensions() {
    const container = d3.select("#container");
    const canvas = container.select("#canvas")
    const drawing = canvas.select("#drawing");  // Select the inner layer using layerReference

    const zeroPositionShiftX = parseInt(drawing.node().getAttribute("idioticShiftX"))
    const zeroPositionShiftY = parseInt(drawing.node().getAttribute("idioticShiftY"))
    const canvasWidth = parseInt(canvas.node().getAttribute("originalWidth"))
    const canvasHeight = parseInt(canvas.node().getAttribute("originalHeight"))
    return {
        idioticShift: [zeroPositionShiftX, zeroPositionShiftY],
        size: [canvasWidth, canvasHeight]
    }
}

function centerAndZoomRelativePointOfCanvas(targetX, targetY, zoomLevel, duration = 10) {
    const container = d3.select("#container");

    const canvasDimensions = getCanvasDimensions();
    const scalingCorrection = [
        (window.innerWidth - canvasDimensions.size[0] * zoomLevel) / 2,
        (window.innerHeight - canvasDimensions.size[1] * zoomLevel) / 2
    ]
    const target = [
        targetX * canvasDimensions.size[0], // In original canvas coordinates!
        targetY * canvasDimensions.size[1]
    ]

    const canvas = container.select("#canvas")
    const drawing = canvas.select("#drawing");
    const p5jsDrawing = canvas.select("#p5jsDrawing");

    const zoom = d3.zoom()
        .scaleExtent([0.1, 50])
        .on("zoom", ({ transform }) => {
            drawing.attr("transform", transform);

            p5jsDrawing.attr("transform", transform);

            // Also update tooltip
            if (!isMobile) {
                mousePosition = getMousePosition();
                d3.select("#tooltip")
                    .style("left", `${mousePosition.x + 5}px`)
                    .style("top", `${mousePosition.y - 28}px`);
            }
            else {
                d3.select("#tooltip").transition().duration(200).style("visibility", "hidden");
            }
        });

    container.call(zoom);

    // Then programmatically set the transform once at startup
    container.call(
        zoom.transform,
        d3.zoomIdentity
            .translate(
                canvasDimensions.idioticShift[0] * zoomLevel + scalingCorrection[0] + (canvasDimensions.size[0] / 2 - target[0]) * zoomLevel,
                canvasDimensions.idioticShift[1] * zoomLevel + scalingCorrection[1] + (canvasDimensions.size[1] / 2 - target[1]) * zoomLevel)
            .scale(zoomLevel)
    );
}

function setupTooltip() { setupRoomV2Tooltip(); }

let condensedSchedule, requestLists;

const reasonMapping = {
    none: { type: 'none', original: 'None given', message: '' },
    t_on: { type: 't_on', original: 'Timed on', message: 'Idővezérelt be.' },
    t_off: { type: 't_off', original: 'Timed off', message: 'Idővezérelt ki.' },

    below: { type: 'below', original: 'Below set temp', message: 'Beállított alatt.' },
    above: { type: 'above', original: 'Above set temp', message: 'Beállított felett.' },
    h_off: { type: 'h_off', original: 'Off hysteresis', message: 'Felső hiszterézis.' },
    h_on: { type: 'h_on', original: 'On hysteresis', message: 'Alsó hiszterézis.' },

    d_low: { type: 'd_low', original: 'Closed valves', message: 'Szelepek zárva.' },
    d_high: { type: 'd_high', original: 'Open valves', message: 'Szelepek nyitva.' },
    d_h_off: { type: 'd_h_off', original: 'Closed hysteresis', message: 'Zárt hiszterézis.' },
    d_h_on: { type: 'd_h_on', original: 'Open hysteresis', message: 'Nyitott hiszterézis.' },

    r_m_on: { type: 'r_m_on', original: 'Room master ON', message: 'Szoba be.' },
    r_m_off: { type: 'r_m_off', original: 'Room master OFF', message: 'Szoba ki.' },
    c_s_m_off: { type: 'c_s_m_off', original: 'Cycle scheduled master OFF', message: 'Kör időzítetten lekapcsolva.' },
    c_m_on: { type: 'c_m_on', original: 'Cycle master ON', message: 'Kör manuálisan bekapcsolva.' },
    c_m_off: { type: 'c_m_off', original: 'Cycle master OFF', message: 'Kör manuálisan lekapcsolva.' }
};

let systemOn;
let systemNode;
let newGasUsageRate;

function getDataFromFirebase() {
    const url = "https://kazanfutes-71b78-default-rtdb.europe-west1.firebasedatabase.app/.json";
    fetchJSONEndpoint(url)
        .then(fullFirebaseDataJSON => {
            replayLatestLive = fullFirebaseDataJSON;
            if (!dashboardReplayActive()) renderDashboardState(fullFirebaseDataJSON);
        })
        .catch(error => {
            console.error('Error fetching data from Firebase:', error);
        });
}

function renderDashboardState(fullFirebaseDataJSON, options = {}) {
            const systemJSON = fullFirebaseDataJSON.system;
            const scheduleJSON = fullFirebaseDataJSON.schedule;
            const updateJSON = fullFirebaseDataJSON.update;

            if (!options.replay) updateAdminMessage(dashboardAdminMessage(systemJSON.dashboard));

            systemOn = systemJSON['switch']['system'] == 1 ? true : false;
            systemNode = systemJSON;
            updateRadiatorLiveState(systemJSON);
            updateBoilerPowerMarkers(systemJSON.state.boiler_plugs);

            condensedSchedule = scheduleJSON.condensed_schedule;
            requestLists = scheduleJSON.request_lists;

            // Update piping
            const cycles = [1, 2, 3, 4];
            let states = 0;
            cycles.forEach(cycleNum => {
                const cycleState = systemJSON.state.pump_states[cycleNum];
                states += cycleState;
                updateCycleColor(cycleNum, cycleState, cycleSupplyTemperature(systemJSON, cycleNum));
            }
            );
            updateBoilerColor(states > 0 ? 1 : 0, boilerWaterTooCold(systemJSON));

            roomV2UpdateRooms(systemJSON);
            updateAmbientAreas(systemJSON);

            // Update general infobox
            let cyclesOn = [];
            cycles.forEach(cycleNum => {
                systemJSON.state.pump_states[cycleNum] == 1 ? cyclesOn.push(cycleNum) : "";
            });

            let lastControlRun = dateFromTimestamp(systemJSON.state.last_updated);
            let timeSinceLastControlRun = timePassedSince(lastControlRun, 'seconds');

            let lastControlRunGranularity = ' másodperce'
            if (timeSinceLastControlRun > 90) {
                timeSinceLastControlRun = roundTo(timeSinceLastControlRun / 60, 0.1);
                lastControlRunGranularity = ' perce'
            }
            else if (timeSinceLastControlRun > 90 * 30) {
                timeSinceLastControlRun = roundTo(timeSinceLastControlRun / 60 * 60, 0.1);
                lastControlRunGranularity = ' órája'
            }
            if (timeSinceLastControlRun < 0) {
                timeSinceLastControlRun = 0
            }

            let lastScheduleUpdate = dateFromTimestamp(scheduleJSON.last_updated)
            let timeSinceLastScheduleUpdate = timePassedSince(lastScheduleUpdate, 'minutes');
            let schedLastUpdateGranularity = ' perce';
            if (timeSinceLastScheduleUpdate > 90) {
                timeSinceLastScheduleUpdate = roundTo(timeSinceLastScheduleUpdate / 60, 0.1);
                schedLastUpdateGranularity = ' órája'
            }

            if (!options.replay && timeSinceLastScheduleUpdate < 1) { // Urge redraw if a schedule update is recent
                drawMainGraph();
            }

            // QR is retired: legacy webhook writes must not affect this notification.
            const requestedRoom = String(updateJSON.override_rooms?.room_id || '');
            let timeSinceLastRequest = roomsDataAndState[requestedRoom] ? timePassedSince(dateFromTimestamp(updateJSON.override_rooms.last_update_timestamp)) : Infinity;
            lastRequestGranularity = 'perce'
            if (timeSinceLastRequest > 90) {
                timeSinceLastRequest = roundTo(timeSinceLastRequest / 60, 0.5);
                lastRequestGranularity = 'órája'
            }

            let requestOrigin = "form";
            let requestTarget = roomV2Name(requestedRoom);

            if (!options.replay && fromRequest && !initialLockDone && roomsDataAndState[requestedRoom]) {
                mainGraphContentLocked = true;
                mainGraphSetting = elementToMainGraphSettingMapping['room_' + requestedRoom];
                initialLockDone = true;
            }

            let lastRequestHourStamp = roomsDataAndState[requestedRoom] ? hourStamp(dateFromTimestamp(updateJSON.override_rooms.last_update_timestamp)) : '';

            externalTemp = Number.isFinite(systemJSON.state.external_temp) ? systemJSON.state.external_temp : null;

            let controlError = systemJSON['control']['error']['error'];
            let secondsSinceControlError = timePassedSince(dateFromTimestamp(systemJSON['control']['last_updated']), 'seconds')
            let controlErrorSource = systemJSON['control']['error']['where']
            let lastErrorGranularity = ' másodperce'
            if (secondsSinceControlError > 90) {
                secondsSinceControlError = roundTo(secondsSinceControlError / 60, 0.1);
                lastErrorGranularity = ' perce'
            }
            else if (secondsSinceControlError > 90 * 30) {
                secondsSinceControlError = roundTo(secondsSinceControlError / 60 * 60, 0.1);
                lastErrorGranularity = ' órája'
            }

            updateGeneralInfobox(
                {
                    heatingOn: systemJSON.switch.system,
                    cyclesOn: cyclesOn,
                    lastControlRun: { timeSince: timeSinceLastControlRun, granularity: lastControlRunGranularity },
                    lastRequest: { target: requestTarget, origin: requestOrigin, timeSince: timeSinceLastRequest, granularity: lastRequestGranularity, hourStamp: lastRequestHourStamp },
                    scheduleLastUpdated: lastScheduleUpdate,
                    waterTemp: infoboxCirculatedWaterTemperature(systemJSON),
                    boilerError: boilerColdWaterError,
                    error: { error: controlError, timeSince: secondsSinceControlError, granularity: lastErrorGranularity, source: controlErrorSource }
                }
            );

            // Update cycle infoboxes
            cycles.forEach(cycleNum => {
                let roomsOnCycle = allControlledRooms.filter(id => roomsDataAndState[id].cycle === cycleNum);
                let roomsThatWantHeating = [];
                roomsOnCycle.forEach(roomNum => {
                    if (roomsDataAndState[roomNum].controlled) {
                        systemJSON.control.rooms?.[roomNum]?.vote == 1 ? roomsThatWantHeating.push({ type: roomsDataAndState[roomNum].type, name: roomsDataAndState[roomNum].name, reason: roomsDataAndState[roomNum].reason }) : "";
                    }
                });

                cyclesDataAndState[cycleNum].state = systemJSON.state.pump_states[cycleNum];

                updateCycleInfobox(
                    cycleNum,
                    {
                        state: cyclesDataAndState[cycleNum].state,
                        enabled: systemJSON.switch.cycles[cycleNum] !== -1,
                        waterTemp: cycleSupplyTemperature(systemJSON, cycleNum),
                        roomTemp: infoboxRoomTemperature(systemJSON, roomsOnCycle),
                        set: systemJSON.control.cycles[cycleNum],
                        rooms: roomsOnCycle,
                        wantHeating: roomsThatWantHeating,
                    }
                );

                // Update misc data
                newGasUsageRate = options.replay ? currentGasUsageRate : roundTo(0.1 / (systemJSON.state.gas.dial_turn_secs / 3600), 0.1);
                if (!currentGasUsageRate) {
                    currentGasUsageRate = newGasUsageRate;
                }
                else if (isValidNumber(newGasUsageRate) && Math.abs(newGasUsageRate - currentGasUsageRate) > 0.05) {
                    prevGasUsageRate = currentGasUsageRate;
                    currentGasUsageRate = newGasUsageRate;
                    if (lastGasUpdate) {
                        timeItTookToUpdateGasUsage = new Date() - lastGasUpdate
                        lastGasUpdate = new Date();
                    }
                    else {
                        lastGasUpdate = new Date();
                    }
                }
                //console.log(lastGasUpdate)
                //console.log(currentGasUsageRate)
                //console.log(timeItTookToUpdateGasUsage)
            });
            if (!options.replay) refreshMainPlotLiveEndpoint();
}

let lastGasUpdate, timeItTookToUpdateGasUsage, prevGasUsageRate;

function extractHeatingPeriodsFromHeatingState(cycleNum, heatingState, day = mainGraphSetting.day) {
    const samples = (heatingState || []).filter(sample => sample.cycle_states);
    if (cycleNum > 0) return extractCyclePumpOnPeriods(cycleNum, samples, day === dayStamp() ? getFractionalHourOfDay() : 24);

    let heatingPeriods = [];
    let prevHeatingState = -1;
    samples.forEach(timepoint => {
        if (timepoint.cycle_states) {
            let numOfCyclesOn = cycleNum == 0 ? d3.sum(Object.values(timepoint.cycle_states)) : timepoint.cycle_states[cycleNum]
            let currentHeatingState = Math.ceil(numOfCyclesOn / 4);
            //console.log(timepoint.timestamp + ": " + numOfCyclesOn + ", " + currentHeatingState)
            if (prevHeatingState == -1) {
                prevHeatingState = currentHeatingState;
            }
            else {
                let currentHeatingSwitch = currentHeatingState - prevHeatingState;
                if (currentHeatingState == 1 && currentHeatingSwitch == 1) { // Heating on, start of rect
                    if (!heatingPeriods) { heatingPeriods = [] };
                    heatingPeriods.push({
                        "x1": timepoint.h_of_day_frac
                    })
                }
                if (currentHeatingState == 0 && currentHeatingSwitch == -1) {
                    if (!heatingPeriods || heatingPeriods.length == 0) {
                        heatingPeriods = [];
                        heatingPeriods.push({
                            "x2": timepoint.h_of_day_frac
                        })
                    }
                    else {
                        heatingPeriods[heatingPeriods.length - 1].x2 = timepoint.h_of_day_frac;
                    }
                }
                prevHeatingState = currentHeatingState;
            }
            //console.log("timepoint: " + timepoint.timestamp + ", heating state: " + currentHeatingState)
        }
    });

    if (heatingPeriods.length > 0) {
        if (!heatingPeriods[0].x1) {
            heatingPeriods[0].x1 = 0;
        }
        if (!heatingPeriods[heatingPeriods.length - 1].x2) {
            heatingPeriods[heatingPeriods.length - 1].x2 = day === dayStamp() ? getFractionalHourOfDay() : 24;
        }
    }
    return heatingPeriods;
}

function extractCyclePumpOnPeriods(cycleNum, heatingState, endHour) {
    const periods = [];
    let startedAt = null;
    const samples = (heatingState || [])
        .filter(sample => sample.cycle_states && Number.isFinite(sample.h_of_day_frac))
        .slice().sort((a, b) => a.h_of_day_frac - b.h_of_day_frac);
    samples.forEach(sample => {
        const hour = sample.h_of_day_frac;
        if (hour < 0 || hour > endHour) return;
        if (sample.cycle_states[cycleNum] === 1) {
            if (startedAt === null) startedAt = hour;
        } else {
            if (startedAt !== null && hour > startedAt) periods.push({ x1: startedAt, x2: hour });
            startedAt = null;
        }
    });
    if (startedAt !== null && endHour > startedAt) periods.push({ x1: startedAt, x2: endHour });
    return periods;
}

function roomControlSetTemperature(state, roomNum) {
    const nominal = state.set_temps[roomNum];
    return Math.max(nominal, state.set_temps_interp?.[roomNum] ?? nominal);
}

// Keep this calculation aligned with utils/set_temperature.py.
function interpolateRoomSetTemperature(schedule, day, hour, fraction) {
    const valueAt = offset => {
        const absoluteHour = hour + offset;
        return schedule?.[day + Math.floor(absoluteHour / 24)]?.[((absoluteHour % 24) + 24) % 24] ?? null;
    };
    const current = valueAt(0);
    let ahead, following;
    for (ahead = 1; ahead <= 24; ahead++) {
        following = valueAt(ahead);
        if (following === null) return current;
        if (following !== current) break;
    }
    if (ahead > 24 || following <= current) return current;
    let plateauStart = 0;
    for (let back = 1; back <= 3; back++) {
        if (valueAt(-back) !== current) break;
        plateauStart = -back;
    }
    const rampStart = Math.max(ahead - 3, plateauStart);
    const progress = Math.max(0, Math.min(1, (fraction - rampStart) / (ahead - rampStart)));
    return current + (following - current) * progress;
}

function roomScheduleWithRecentHistory(schedule, history, day, hour) {
    const combined = Object.fromEntries(Object.entries(schedule).map(([key, values]) => [key, {...values}]));
    for (let back = 1; back <= 3; back++) {
        const absoluteHour = day * 24 + hour - back;
        const previousDay = Math.floor(absoluteHour / 24);
        const slot = ((absoluteHour % 24) + 24) % 24;
        combined[previousDay] ??= {};
        if (combined[previousDay][slot] == null && history?.[absoluteHour] != null) {
            combined[previousDay][slot] = history[absoluteHour];
        }
    }
    return combined;
}

function projectedRoomControlSchedule(schedule, day, nowHour) {
    const points = [];
    for (let hour = Math.floor(nowHour); hour < 24; hour++) {
        // Both sides of each boundary preserve immediate downward steps.
        for (const fraction of [Math.max(0, nowHour - hour), 1]) {
            const value = interpolateRoomSetTemperature(schedule, day, hour, fraction);
            if (value === null) continue;
            points.push({h_of_day_frac: hour + fraction, set_temp: value, temp: value});
        }
    }
    return points;
}

function extractRoomScheduleFromCondensedSchedule(roomNum, setTempsData, day = dayStamp()) {
    const recorded = (setTempsData || []).slice().sort((a, b) => a.h_of_day_frac - b.h_of_day_frac);
    if (day !== dayStamp() || !recorded.length || !condensedSchedule?.[roomNum]?.[getUnixDay()]) {
        return {roomSchedule: recorded, roomScheduleAsOfYet: recorded, roomScheduleRestOfDay: []};
    }
    const nowHour = getFractionalHourOfDay();
    const roomScheduleAsOfYet = recorded.filter(item => item.h_of_day_frac <= nowHour);
    const schedule = roomScheduleWithRecentHistory(condensedSchedule[roomNum],
        systemNode?.state?.set_temp_schedule_history?.[roomNum], getUnixDay(), Math.floor(nowHour));
    const roomScheduleRestOfDay = projectedRoomControlSchedule(schedule, getUnixDay(), nowHour);
    return {
        roomSchedule: roomScheduleAsOfYet.concat(roomScheduleRestOfDay),
        roomScheduleAsOfYet,
        roomScheduleRestOfDay
    };
}

function convertTimestamps(dataJSON, day) {
    const parseTime = d3.timeParse("%Y-%m-%d-%H-%M-%S");
    const formatDay = d3.timeFormat("%Y-%m-%d");
    if (!Array.isArray(dataJSON)) {
        return [];
    }
    if (!dataJSON || !dataJSON.length) {
        return [];
    }
    return dataJSON
        .map(d => {
            const parsedDate = parseTime(d.timestamp);
            if (!parsedDate) return null;

            // Keep only items that match the day in 'day'
            if (formatDay(parsedDate) !== day) {
                return null;
            }

            // If kept, compute fractional hour
            return {
                ...d,
                h_of_day_frac: parsedDate.getHours() + parsedDate.getMinutes() / 60 + parsedDate.getSeconds() / 3600
            };
        })
        // Filter out the nulls (mismatched days or unparsable timestamps)
        .filter(Boolean)
        .sort((a, b) => a.h_of_day_frac - b.h_of_day_frac);
}

let loadedData = {};
let dataExpiry = 5; //Minutes

function collectDataFromGitHub(dataToCollect, drawFunction, options = {}) {
    // We'll collect final results here in the same shape as loadedData => dataCollected[day][type]
    const dataCollected = {};

    // Recursive function to handle each item in dataToCollect
    function fetchNext(index) {
        if (index >= dataToCollect.length) {
            // Once all data is fetched/collected, call the draw function
            drawFunction(options.unclipped ? dataCollected : replayPlotPayload(dataCollected));
            return;
        }

        const { day, type } = dataToCollect[index];

        // Ensure we have a day object in loadedData
        if (!loadedData[day]) {
            loadedData[day] = {};
        }
        // Also ensure dataCollected structure for returning results
        if (!dataCollected[day]) {
            dataCollected[day] = {};
        }

        const existingDataEntry = loadedData[day][type];
        const now = new Date();
        if (!options.unclipped && dashboardReplayActive() && replayDay?.day === day && Object.hasOwn(replayDay.plots, type)) {
            dataCollected[day][type] = replayDay.plots[type];
            fetchNext(index + 1);
            return;
        }

        // Determine if existing data is "fresh"
        let isFresh = false;
        if (existingDataEntry && existingDataEntry.timestamp) {
            const lastLoadedTime = new Date(existingDataEntry.timestamp);
            const ageInMinutes = (now - lastLoadedTime) / (1000 * 60);

            if (ageInMinutes < dataExpiry) {
                isFresh = true;
            }
        }

        if (isFresh) {
            // Use cached data
            dataCollected[day][type] = existingDataEntry.data;
            fetchNext(index + 1);
        } else {
            // Not fresh (or doesn't exist) -> fetch from GitHub
            // Keep the new power/flow stream separate from cached pre-power trial responses.
            const newMetricStream = type.startsWith('radiator_') || type.endsWith('_water_temps') || type.endsWith('_heat_delivery') || type.endsWith('_environment') || type.endsWith('_phase_points') || type === 'weather_station' || type === 'room_control_kpis' || type === 'room_control_errors' || type === 'heating_demand';
            const dataRef = newMetricStream ? 'main' : 'refs/heads/main';
            const url = "https://raw.githubusercontent.com/markusbenjamin/kazanfutes/" + dataRef + "/data/formatted/"
                + day + "/" + type + ".json"
                // Newly introduced files may have cached 404s before their first upload.
                // The existing loadedData expiry still limits successful heat/flow fetches.
                + (newMetricStream ? '?updated=' + now.getTime() : '');

            fetchJSONEndpoint(url)
                .then(dataJSON => {
                    let finalData;

                    // If you need to convert timestamps in arrays, do so
                    if (Array.isArray(dataJSON)) {
                        finalData = convertTimestamps(dataJSON, day);
                    } else {
                        finalData = dataJSON;
                    }

                    // Put data into dataCollected
                    dataCollected[day][type] = finalData;

                    // Update loadedData with fresh data + timestamp
                    loadedData[day][type] = {
                        data: finalData,
                        timestamp: now.toISOString()
                    };

                    // Move on
                    fetchNext(index + 1);
                })
                .catch(err => {
                    console.error("Error fetching or processing data: " + day + "/" + type, err);
                    // Even if error, we proceed to the next item
                    fetchNext(index + 1);
                });
        }
    }

    // Start with the first item
    fetchNext(0);
}

function dataToCollectGenerator(startDate, endDate, dataTypes) {
    // Convert input date strings to Date objects
    const start = new Date(startDate);
    const end = new Date(endDate);

    const result = [];

    // A helper to format a Date -> "YYYY-MM-DD"
    function formatDate(dateObj) {
        const year = dateObj.getFullYear();
        const month = String(dateObj.getMonth() + 1).padStart(2, '0');
        const day = String(dateObj.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    // Iterate from start to end date, inclusive
    let current = new Date(start);
    while (current <= end) {
        const dayString = formatDate(current);
        // For each day, add each data type
        dataTypes.forEach(type => {
            result.push({ day: dayString, type });
        });

        // Move current date by +1 day
        current.setDate(current.getDate() + 1);
    }

    return result;
}

// Room sensors do not necessarily publish at the logger cadence.  Build a
// regular display-only series between nearby observations so the moving
// average is based on elapsed time rather than on how often one device happens
// to report.  Do not bridge a longer missing-data interval.
const ROOM_TEMPERATURE_DISPLAY_STEP_HOURS = 5 / 60;
const ROOM_TEMPERATURE_INTERPOLATION_MAX_GAP_HOURS = 2;
const ROOM_TEMPERATURE_SPARSE_UPDATE_INTERVAL_HOURS = 0.5;

function resampleRoomTemperatureForDisplay(
    readings,
    stepHours = ROOM_TEMPERATURE_DISPLAY_STEP_HOURS,
    maxGapHours = ROOM_TEMPERATURE_INTERPOLATION_MAX_GAP_HOURS,
    minGapHours = 0
) {
    if (!Array.isArray(readings)) return readings;

    const sortedReadings = readings
        .filter(reading => reading?.h_of_day_frac != null && reading?.temp != null && Number.isFinite(Number(reading.h_of_day_frac)) && Number.isFinite(Number(reading.temp)))
        .map(reading => ({
            h_of_day_frac: Number(reading.h_of_day_frac),
            temp: Number(reading.temp),
            ...(reading.live === true ? {live: true} : {})
        }))
        .sort((a, b) => a.h_of_day_frac - b.h_of_day_frac);

    const uniqueReadings = [];
    sortedReadings.forEach(reading => {
        const previous = uniqueReadings.at(-1);
        if (previous && Math.abs(previous.h_of_day_frac - reading.h_of_day_frac) < 1e-9) {
            previous.temp = (previous.temp * previous.count + reading.temp) / (previous.count + 1);
            previous.count += 1;
        }
        else {
            uniqueReadings.push({ ...reading, count: 1 });
        }
    });

    const displayReadings = [];
    uniqueReadings.forEach((reading, index) => {
        if (index === 0) {
            displayReadings.push(reading);
            return;
        }

        const previous = uniqueReadings[index - 1];
        const gapHours = reading.h_of_day_frac - previous.h_of_day_frac;
        if (gapHours > minGapHours && gapHours <= maxGapHours) {
            const firstGridIndex = Math.ceil((previous.h_of_day_frac + 1e-9) / stepHours);
            const lastGridIndex = Math.floor((reading.h_of_day_frac - 1e-9) / stepHours);
            for (let gridIndex = firstGridIndex; gridIndex <= lastGridIndex; gridIndex += 1) {
                const hour = gridIndex * stepHours;
                const fraction = (hour - previous.h_of_day_frac) / gapHours;
                displayReadings.push({
                    h_of_day_frac: hour,
                    temp: previous.temp + (reading.temp - previous.temp) * fraction
                });
            }
        }
        displayReadings.push(reading);
    });

    return displayReadings.map(({ count, ...reading }) => reading);
}

function prepareRoomTemperatureForDisplay(readings) {
    return resampleRoomTemperatureForDisplay(
        readings,
        ROOM_TEMPERATURE_DISPLAY_STEP_HOURS,
        ROOM_TEMPERATURE_INTERPOLATION_MAX_GAP_HOURS,
        ROOM_TEMPERATURE_SPARSE_UPDATE_INTERVAL_HOURS
    );
}

function drawPlot(plotData, userOptions) {
    //plotData instanceof Promise ? console.log("promise") : "";
    //plotData === undefined ? console.log("undefined") : "";
    var defaultOptions = {
        dev: false,
        parentId: "background",
        centered: true,
        positioning: { x: 0.5, y: 0.5, w: 1, h: 1 }, // Relative positioning and size compared to parent
        margins: { top: 0.1, right: 0.03, bottom: 0.15, left: 0.1 }, // Affecting the plot elements within the content element

        background: { show: true, col: "white" },
        plotStyle: { joined: false, col: "gray", thickness: "0.25", startCap: true, endCap: true, smoothCurve: true, hoverableCurve: false, dashed: false },
        domain: { bottom: null, left: null },
        smoothing: { bottom: 0, left: 0 },
        axes: { top: false, right: false, left: true, bottom: true },
        tickVals: { top: false, right: false, left: false, bottom: false },
        tickFormat: {bottom: null},

        axesLabel: { top: false, right: false, left: "", bottom: "" },
        plotLabel: "",
        plotLabelTabs: false,
        plotDateNavigation: false,
        curveTooltip: '',
        emptyMessage: '',
        showLockLabel: true,
        now: { show: false, pos: null },
        segment: { do: false, gap: null },
        curveEndText: { show: false, fontSize: null, text: null, col: null, xOffset: 13, yOffset: 3 },
        rects: false, //Usage: rects: {when: "before", list:[{x1: 0, y1: 0, x2: 1, y2: 1, col:  fill: "#ff0000", stroke:"#ff0000", strokeWeight: 2, dashed: false, dashing: "4,4"}, {}...]}
        markers: false //Usage: markers: {when: "before", list:[{pos: 12, h: 2}], col: "#ff0000", thickness: 2, dashed: false, dashing: "4,4", endCap: true, thickness: 5}
    }
    ops = deepObjectMerger(defaultOptions, userOptions);
    if (isMobile) {
        ops.plotStyle.thickness *= 2;
        ops.curveEndText.xOffset *= 2;
        ops.curveEndText.fontSize *= 2;
        ops.margins.left = 0.09;
    }

    // Find parent element
    const parentElement = d3.select(`#${ops.parentId}`);
    if (parentElement.empty()) {
        throw new Error(`No element found with id: ${ops.parentId}`);
    }

    let parentDims = getBBoxDrawingDimensions(ops.parentId);

    // Get collector for graphs laid over the same parent
    let collectorElement = d3.select("#" + ops.parentId + "-graphs-collector");
    if (collectorElement.empty()) { //Check if exists, if not, create it
        collectorElement = d3.select(parentElement.node().parentNode)
            .append("g")
            .attr("id", ops.parentId + "-graphs-collector");
    }

    // Create wrapper g (to be able to show nested content)
    let wrapperDims = parentDims; //Same dimensions as parent
    let wrapperElement = collectorElement
        .append("g")
        .attr("class", "main-graph-instance")
        .attr("transform", `translate(${wrapperDims.x}, ${wrapperDims.y})`); // Position within canvas coordinate system

    // Show wrapper element during dev
    if (ops.dev) {
        wrapperElement.append("rect")
            .attr("width", wrapperDims.w)
            .attr("height", wrapperDims.h)
            .attr("stroke", "rgba(0,255,0,0.5)")
            .attr("fill", "rgba(0,0,0,0)")
    }

    // Create container element
    let containerDims = ops.centered ?
        {
            x: wrapperDims.w * ops.positioning.x - wrapperDims.w * ops.positioning.w / 2,
            y: wrapperDims.h * ops.positioning.y - wrapperDims.h * ops.positioning.h / 2,
            w: wrapperDims.w * ops.positioning.w,
            h: wrapperDims.h * ops.positioning.h
        } :
        {
            x: wrapperDims.w * ops.positioning.x,
            y: wrapperDims.h * ops.positioning.y,
            w: wrapperDims.w * ops.positioning.w,
            h: wrapperDims.h * ops.positioning.h
        };

    let containerElement = wrapperElement.append("g")
        .attr("transform", `translate(${containerDims.x}, ${containerDims.y})`);  // Position within wrapper coordinate system

    // Show container element during dev
    if (ops.dev) {
        containerElement.append("rect")
            .attr("width", containerDims.w)
            .attr("height", containerDims.h)
            .attr("stroke", "rgba(0,0,255,0.5)")
            .attr("fill", "rgba(0,0,0,0)")
    }

    if (ops.background.show) {
        let backgroundRect = containerElement.append("rect")
            .attr("width", containerDims.w)
            .attr("height", containerDims.h)
            .attr("fill", mainGraphContentLocked ? "rgb(253, 253, 253)" : ops.background.col)
            .attr("opacity", ops.background.show ? 1 : 0);

        if (ops.parentId === 'graph' && mainGraphContentLocked) {
            backgroundRect
                .attr("stroke", "black")         // Set border color to gray
                .attr("stroke-width", 0.25)       // Set border thickness
                .attr("stroke-dasharray", "0.5,1"); // Define dash pattern: 4px dash, 2px gap
            let bracketStroke = "rgb(50,50,50)";
            let bracketStrokeWidth = 2.5;
            let bracketShift = bracketStrokeWidth / 2;

            containerElement.append("line")
                .attr("x1", containerDims.x - bracketShift)
                .attr("y1", containerDims.y + containerDims.h)
                .attr("x2", containerDims.x + containerDims.w * 0.05)
                .attr("y2", containerDims.y + containerDims.h)
                .attr("stroke", bracketStroke)
                .attr("stroke-width", bracketStrokeWidth);

            containerElement.append("line")
                .attr("x1", containerDims.x)
                .attr("y1", containerDims.y + containerDims.h - bracketShift)
                .attr("x2", containerDims.x)
                .attr("y2", containerDims.y + containerDims.h - containerDims.w * 0.05)
                .attr("stroke", bracketStroke)
                .attr("stroke-width", bracketStrokeWidth);

            containerElement.append("line")
                .attr("x1", containerDims.x + containerDims.w + bracketShift)
                .attr("y1", containerDims.y)
                .attr("x2", containerDims.x + containerDims.w - containerDims.w * 0.05)
                .attr("y2", containerDims.y)
                .attr("stroke", bracketStroke)
                .attr("stroke-width", bracketStrokeWidth);
            containerElement.append("line")
                .attr("x1", containerDims.x + containerDims.w)
                .attr("y1", containerDims.y)
                .attr("x2", containerDims.x + containerDims.w)
                .attr("y2", containerDims.y + containerDims.w * 0.05)
                .attr("stroke", bracketStroke)
                .attr("stroke-width", bracketStrokeWidth);
        }
    }

    const primaryMainPlot = ops.parentId === 'graph' && ops.background?.show && ops.showLockLabel;
    const mobileViews = ops.parentId === 'graph' ? mobilePlotViewOptions() : null;
    if (mobileViews) containerElement.on('click.mobile-views', event => event.stopPropagation());
    const mobileSelectorWidth = primaryMainPlot && mobileViews
        ? drawMobilePlotViewSelector(containerElement, containerDims, mobileViews) : 0;

    // View controls sit above the frame and do not change the plotting geometry.
    let plotDims = {
        x: containerDims.w * ops.margins.left,
        y: containerDims.h * ops.margins.top,
        w: containerDims.w - containerDims.w * (ops.margins.left + ops.margins.right),
        h: containerDims.h - containerDims.h * (ops.margins.top + ops.margins.bottom)
    }

    let plotElement = containerElement.append("g").attr("transform", `translate(${plotDims.x},${plotDims.y})`);

    if (ops.dev) {
        plotElement.append("rect")
            .attr("width", plotDims.w)
            .attr("height", plotDims.h)
            .attr("stroke", "rgba(255,0,0,0.5)")
            .attr("fill", "rgba(0,0,0,0)")
    }

    let mobileViewScaler = 1.8;

    let bottomScale, bottomAxis;

    bottomScale = d3.scaleLinear()
        .domain(ops.domain.bottom ? ops.domain.bottom : d3.extent(plotData, d => d[ops.dataKeys.bottom]))
        .range([0, plotDims.w]);

    if (ops.axes.bottom) {
        // Add bottom axis
        bottomAxis = plotElement.append("g")
            .attr("transform", `translate(0, ${plotDims.h})`)
            .call(
                d3.axisBottom(bottomScale)
                    .tickSize(isMobile ? 2 * mobileViewScaler : 2)
                    .tickValues(
                        (Array.isArray(ops.tickVals?.bottom) ? ops.tickVals.bottom : bottomScale.ticks(12))
                            .filter(Number.isInteger)
                    )
                    .tickFormat(ops.tickFormat.bottom || (d => d.toFixed(0)))
            );


        // Style the X-axis
        bottomAxis.select(".domain") // Select the axis line
            .style("stroke-width", (isMobile ? 0.5 * mobileViewScaler : 0.5) + "px"); // Set the axis line thickness

        bottomAxis.selectAll(".tick line") // Select all tick lines
            .attr("stroke-width", (isMobile ? 0.5 * mobileViewScaler : 0.5) + "px") // Set tick line thickness
            .attr("y1", (isMobile ? 0.3 * mobileViewScaler : 0.3))
            .attr("y2", (isMobile ? 2.3 * mobileViewScaler : 2.3)); // Adjust tick length (positive increases length)

        bottomAxis.selectAll("text") // Select tick labels
            .attr("dy", (isMobile ? 3 * mobileViewScaler : 3))
            .style("font-family", dashboardFont)
            .style("font-size", (isMobile ? 5 * mobileViewScaler : 5) + "px"); // Set font size for tick labels

        // bottom axis label
        plotElement.append("text")
            .attr("x", plotDims.w / 2)
            .attr("y", plotDims.h + plotDims.h * ops.margins.bottom * 1.05)
            .style("text-anchor", "middle")
            .style("font-size", (isMobile ? 6 * mobileViewScaler : 6) + "px")
            .style("font-family", dashboardFont)
            .text(dashboardText(ops.axesLabel.bottom));
    }

    let leftScale, leftAxis;

    leftScale = d3.scaleLinear()
        .domain(ops.domain.left ? ops.domain.left : d3.extent(plotData, d => d[ops.dataKeys.left]))
        .range([plotDims.h, 0]);
    if (ops.domain.niceLeft !== false) leftScale.nice();

    if (ops.axes.left) {
        leftAxis = plotElement.append("g")
            .call(
                d3.axisLeft(leftScale)
                    .tickSize(isMobile ? 2 * mobileViewScaler : 2)
                    .tickValues(
                        (Array.isArray(ops.tickVals?.left) ? ops.tickVals.left : leftScale.ticks(10))
                            .filter(Number.isInteger)
                    )
                    .tickFormat(typeof ops.tickFormat?.left === 'function' ? ops.tickFormat.left : d => d.toFixed(0))
            );


        // Style the Y-axis
        leftAxis.select(".domain") // Customize the domain path to match the tick range
            .style("stroke-width", (isMobile ? 0.5 * mobileViewScaler : 0.5) + "px");

        leftAxis.selectAll(".tick line")
            .attr("stroke-width", (isMobile ? 0.5 * mobileViewScaler : 0.5) + "px") // Set tick line thickness
            .attr("x1", (isMobile ? 0.2 * mobileViewScaler : 0.2))
            .attr("x2", (isMobile ? -1.8 * mobileViewScaler : -1.8)); // Adjust tick length (negative for left-side ticks)

        leftAxis.selectAll("text")
            .attr("dx", (isMobile ? 0 * mobileViewScaler : 0))
            .style("font-size", (isMobile ? 5 * mobileViewScaler : 5) + "px")
            .style("font-family", dashboardFont)
            .style("text-anchor", "end"); // Set font size for tick labels

        // left-axis label
        plotElement.append("text")
            .attr("transform", `rotate(-90)`)
            .attr("x", -plotDims.h / 2)
            .attr("y", -plotDims.w * ops.margins.left * 0.8)//(0.725 + mobileViewScaler *0.36))
            .style("text-anchor", "middle")
            .style("font-size", (isMobile ? 6 * mobileViewScaler : 6) + "px")
            .style("font-family", dashboardFont)
            .text(dashboardText(ops.axesLabel.left));
    }

    if (ops.plotLabelTabs) {
        drawPlotTitleSelector(plotElement, plotDims, ops.plotLabelTabs, isMobile ? 7 * mobileViewScaler : 7);
    }
    else if (ops.plotLabel != "") {
        // Plot label
        plotElement.append("text")
            .attr("x", plotDims.w / 2)
            .attr("y", -plotDims.h * ops.margins.top * 0.35)
            .style("text-anchor", "middle")
            .style("font-size", (isMobile ? 7 * mobileViewScaler : 7) + "px")
            .style("font-family", dashboardFont)
            .text(dashboardText(ops.plotLabel));
    }

    const dateNavigation = ops.plotDateNavigation || (ops.plotLabelTabs?.day ? ops.plotLabelTabs :
        primaryMainPlot ? {day: mainGraphSetting.day, onDayChange: navigateMainPlotDay} : false);
    if (dateNavigation) {
        drawPlotDateNavigation(containerElement, {...containerDims, labelRight: containerDims.w - mobileSelectorWidth}, dateNavigation, isMobile ? 6 * mobileViewScaler : 6,
            mainGraphContentLocked && ops.showLockLabel);
    }
    else if (mainGraphContentLocked && ops.showLockLabel && ops.background?.show) {
        plotElement.append("text")
            //.attr("x", plotDims.w * 0.87125)
            .attr("x", -plotDims.w * ops.margins.left * 1.03)
            .attr("y", -plotDims.h * ops.margins.top * (isMobile ? 1.5 : 1.58))
            .style("text-anchor", "right")
            .style("font-size", (isMobile ? 6 * mobileViewScaler : 6) + "px")
            .style("font-family", dashboardFont)
            .style("fill", "rgba(230,230,230,1)")
            .text(dashboardText("rögzítve"));
    }

    if (plotData === undefined) {
        setPlotEmptyMessage(plotElement.append("text")
            .attr("x", plotDims.w / 2)
            .attr("y", plotDims.h / 2)
            .style("text-anchor", "middle")
            .style("font-size", (isMobile ? 7 * mobileViewScaler : 7) + "px")
            .style("font-family", dashboardFont), 'Az adott napra nincs adat.');
    }
    else {
        if (ops.smoothing.bottom > 0) {
            plotData = calculateMovingAverage(plotData, ops.dataKeys.bottom, ops.smoothing.bottom);
        }
        if (ops.smoothing.left > 0) {
            plotData = calculateMovingAverage(plotData, ops.dataKeys.left, ops.smoothing.left);
        }

        function drawRects() {
            ops.rects.list.forEach(rect => {
                plotElement.append("rect")
                    .attr("x", bottomScale(rect.x1))
                    .attr("y", leftScale(rect.y2))
                    .attr("width", bottomScale(rect.x2) - bottomScale(rect.x1)) // Calculate width
                    .attr("height", leftScale(rect.y1) - leftScale(rect.y2))//leftScale(rect.y2) - leftScale(rect.y1)) // Calculate height
                    .style("fill", rect.fill || "none") // Default to no fill if not specified
                    .style("stroke", rect.stroke || "none") // Default to no stroke if not specified
                    .style("stroke-width", rect.strokeWeight || 0) // Default to 0 if not specified
                    .style("stroke-dasharray", rect.dashed ? rect.dashing : null); // Set dashing if dashed is true
            });
        }

        if (ops.rects && ops.rects.when == "before") {
            drawRects();
        }
        if (ops.emptyMessage) {
            setPlotEmptyMessage(plotElement.append('text').attr('x', plotDims.w / 2).attr('y', plotDims.h / 2)
                .style('text-anchor', 'middle').style('font-family', dashboardFont)
                .style('font-size', '6px').style('fill', '#555'), ops.emptyMessage);
        }

        function drawMarkers() {
            ops.markers.list.forEach(marker => {
                let markerElement = plotElement.append("line")
                    .attr("x1", bottomScale(marker.pos ? marker.pos : marker.x1))
                    .attr("y1", leftScale(ops.domain.left[0]))
                    .attr("x2", bottomScale(marker.pos ? marker.pos : marker.x2))
                    .attr("y2", leftScale(marker.h))
                    .attr("stroke", ops.markers.col)
                    .attr("stroke-width", ops.markers.thickness);
                if (ops.markers.dashed) { markerElement.attr("stroke-dasharray", ops.markers.dashing); }
                if (ops.markers.endCap) {
                    plotElement.append("circle")
                        .attr("cx", bottomScale(marker.pos ? marker.pos : marker.x2))
                        .attr("cy", leftScale(marker.h))
                        .attr("r", ops.markers.thickness * ops.markers.endCapSize)
                        .attr("fill", ops.markers.col);
                }
            });
        }

        if (ops.markers && ops.markers.when == "before") {
            drawMarkers();
        }

        if (ops.dataKeys.left == 'external_temp' && ops.domain.left[0] < 0) {
            plotElement.append("line")
                .attr("x1", bottomScale(ops.domain.bottom[0]))
                .attr("y1", leftScale(0))
                .attr("x2", bottomScale(ops.domain.bottom[1]))
                .attr("y2", leftScale(0))
                .attr("stroke", "rgba(150,150,150,1)")
                .attr("stroke-width", 0.5)
                .attr("stroke-dasharray", "4,4");
        }

        if (ops.plotStyle.joined) {
            const line = d3.line()
                .x(d => bottomScale(d[ops.dataKeys.bottom]))
                .y(d => leftScale(d[ops.dataKeys.left]))
                .curve(ops.plotStyle.stepAfter ? d3.curveStepAfter : ops.plotStyle.monotone ? d3.curveMonotoneX : ops.plotStyle.linear ? d3.curveLinear
                    : ops.plotStyle.smoothCurve ? d3.curveBasis : d3.curveStep);

            const segments = joinLivePlotTail(ops.segment.do ? splitDataIntoSegments(plotData, ops.dataKeys.bottom, ops.segment.gap) : [plotData]);

            // Draw a path for each segment
            segments.forEach((segment, segmentIndex) => {
                if (!segment || segment.length === 0) return;

                let startCap;
                if (ops.plotStyle.startCap && segmentIndex == 0) {
                    const firstPoint = segment[0];
                    startCap = plotElement.append("circle")
                        .attr("cx", bottomScale(firstPoint[ops.dataKeys.bottom]))
                        .attr("cy", leftScale(firstPoint[ops.dataKeys.left]))
                        .attr("r", ops.plotStyle.thickness * 1.05)
                        .attr("fill", ops.plotStyle.col);
                }

                let endCap;
                if (ops.plotStyle.endCap && segmentIndex == segments.length - 1) {
                    const lastPoint = segment[segment.length - 1];
                    endCap = plotElement.append("circle")
                        .attr("cx", bottomScale(lastPoint[ops.dataKeys.bottom]))
                        .attr("cy", leftScale(lastPoint[ops.dataKeys.left]))
                        .attr("r", ops.plotStyle.thickness * 1.05)
                        .attr("fill", ops.plotStyle.col);
                }

                if (ops.segment.startCaps && segmentIndex > 0) {
                    const firstPoint = segment[0];
                    startCap = plotElement.append("circle")
                        .attr("cx", bottomScale(firstPoint[ops.dataKeys.bottom]))
                        .attr("cy", leftScale(firstPoint[ops.dataKeys.left]))
                        .attr("r", ops.plotStyle.thickness * 1.05)
                        .attr("fill", ops.plotStyle.col);
                }

                if (ops.segment.endCaps && segmentIndex < segments.length - 1) {
                    const lastPoint = segment[segment.length - 1];
                    endCap = plotElement.append("circle")
                        .attr("cx", bottomScale(lastPoint[ops.dataKeys.bottom]))
                        .attr("cy", leftScale(lastPoint[ops.dataKeys.left]))
                        .attr("r", ops.plotStyle.thickness * 1.05)
                        .attr("fill", ops.plotStyle.col);
                }

                let endTextRect, endText;
                if (ops.curveEndText.show && segmentIndex == segments.length - 1) { // Only draw end text at the last segment
                    const lastPoint = segment[segment.length - 1];

                    // Add the text element
                    endText = plotElement.append("text")
                        .attr("x", bottomScale(lastPoint[ops.dataKeys.bottom]) + ops.curveEndText.xOffset)
                        .attr("y", leftScale(lastPoint[ops.dataKeys.left]) + ops.curveEndText.yOffset)
                        .style("text-anchor", "left")
                        .style("font-size", ops.curveEndText.fontSize + "px")
                        .style("font-family", dashboardFont)
                        .style("fill", ops.curveEndText.col ? ops.curveEndText.col : "black")
                        .text(dashboardText(ops.curveEndText.text));

                    const bbox = endText.node().getBBox();

                    // Add the background rect directly behind the text
                    endTextRect = plotElement.append("rect")
                        .attr("x", bbox.x - 1) // Add padding
                        .attr("y", bbox.y - 1)
                        .attr("width", bbox.width + 2 * 1 + ops.curveEndText.text.length * 0.05) // Add padding
                        .attr("height", bbox.height + 2 * 1)
                        .style("fill", "rgba(255,255,255)")
                        .style("fill-opacity", "0");

                    // Ensure the rect appears behind the text
                    endTextRect.lower();
                }

                // Draw the segment as a line
                const curve = plotElement.append("path")
                    .datum(segment)
                    .attr("fill", "none")
                    .attr(
                        ops.plotStyle.dashed ? "stroke-dasharray" : "fill",
                        ops.plotStyle.dashed ? ops.plotStyle.dashing : "none"
                    )
                    .attr("stroke", ops.plotStyle.col)
                    .attr("stroke-width", ops.plotStyle.thickness)
                    .attr("stroke-linecap", "butt")
                    .attr("d", line)
                    .attr("has-endtext", "0")
                    .classed("hoverable-curve", ops.plotStyle.hoverableCurve)
                    .on("mouseover", ops.plotStyle.hoverableCurve ? function (event) {
                        let curveElement = d3.select(this);
                        let curveClone = plotElement.append(() => curveElement.node().cloneNode(true));

                        curveElement
                            .attr("stroke-width", ops.plotStyle.thickness * 2);
                        wrapperElement.raise();
                        curveClone
                            .attr("stroke", "rgba(255,255,255,0.5)")
                            .attr("stroke-width", ops.plotStyle.thickness * 3)
                            .attr("class", "curve-clone");
                        curveClone.raise();
                        curveClone.lower();

                        if (startCap) {
                            startCap.attr("r", ops.plotStyle.thickness * 1.05 * 2);
                        }
                        if (endCap) {
                            endCap.attr("r", ops.plotStyle.thickness * 1.05 * 2);
                        }
                        if (endText) {
                            endText.style("font-weight", "bold")
                                .style("font-size", (ops.curveEndText.fontSize * 1.25) + "px")
                            endTextRect.style("fill-opacity", "0.5");
                            let baseWidth = endTextRect.attr("width");
                            endTextRect.attr("width", baseWidth * 1.25);
                        }
                    } : null)
                    .on("mouseout", ops.plotStyle.hoverableCurve ? function (event) {
                        d3.select(this)
                            .attr("stroke-width", ops.plotStyle.thickness);
                        d3.selectAll(".curve-clone").remove();

                        if (startCap) {
                            startCap.attr("r", ops.plotStyle.thickness * 1.05);
                        }
                        if (endCap) {
                            endCap.attr("r", ops.plotStyle.thickness * 1.05);
                        }
                        if (endText) {
                            endText.style("font-weight", "normal")
                                .style("font-size", ops.curveEndText.fontSize + "px")
                            endTextRect.style("fill-opacity", "0");
                            let emphasisWidth = endTextRect.attr("width");
                            endTextRect.attr("width", emphasisWidth / 1.25);
                        }
                    } : null);
                if (ops.curveTooltip) bindPlotCurveTooltip(curve, ops.curveTooltip, isMobile ? 7 * mobileViewScaler : 7);
            });
        }
        else {
            plotElement.selectAll(".dot")
                .data(plotData)
                .enter().append("circle")
                .attr("cx", d => bottomScale(d[ops.dataKeys.bottom]))
                .attr("cy", d => leftScale(d[ops.dataKeys.left]))
                .attr("r", ops.plotStyle.thickness)
                .attr("fill", ops.plotStyle.col);
        }

        if (ops.rects && ops.rects.when == "after") {
            drawRects();
        }

        if (ops.markers && ops.markers.when == "after") {
            drawMarkers()
        }

        if (ops.now.show) {
            plotElement.append("line")
                .attr("x1", bottomScale(ops.now.pos))
                .attr("y1", 0)
                .attr("x2", bottomScale(ops.now.pos))
                .attr("y2", plotDims.h)
                .attr("stroke", ops.now.color || "gray")
                .attr("stroke-width", ops.now.thickness ?? 0.5)
                .attr("stroke-dasharray", ops.now.dash || "1 2");
        }
    }
    return { plotElement, plotDims };
}

function clearMainGraphs() {
    hidePlotCurveTooltip();
    d3.selectAll(".main-graph-instance").remove();
}

const roomsDataAndState = roomV2RuntimeStates();

function updateRoomColor(roomId, temp, lastUpdated, roomValveInfo, roomOccupancy) {
    // Reconcile occupancy on every refresh, independently of temperature freshness.
    // Unknown or cleared presence must also remove a previously applied pattern.
    const maskDef = roomOccupancy === true || roomOccupancy === 1
        ? "repeating-linear-gradient(125deg, rgba(0,0,0,0.8) 0 0.25px, rgba(0,0,0,1) 0.05px 4px)"
        : null;
    d3.select("#" + roomId).style("mask", maskDef).style("-webkit-mask", maskDef);
    const readingAge = lastUpdated == null ? NaN : timePassedSince(dateFromTimestamp(lastUpdated), 'seconds');
    if (!Number.isFinite(temp) || !Number.isFinite(readingAge) || readingAge < -5 || readingAge > 7200) {
        // Always clear an earlier temperature colour, including on backwards
        // replay seeks. Retaining a live/SVG fill falsely suggests valid data.
        d3.select("#" + roomId).style("fill", "rgba(31,31,32,0.8)").style("fill-opacity", "1");
    }
    else {
        // Create a color scale
        const colorScale = d3.scaleSequential(d3.interpolateRgb("rgba(0,0,200,1)", "red")).domain([14, 26]); // Set the input domain (10°C to 30°C)
        d3.select("#" + roomId).style("fill", colorScale(temp)).style("fill-opacity", "1");
        // Radiator colours and per-TRV interactions are managed by radiator_plots.js.
    }
}

function updateCycleColor(cycle, state, supplyTemperature) {
    const pipeColor = state === 1 ? heatingTemperatureColor(supplyTemperature) : 'rgb(0,0,200)';
    d3.select("#cycle" + cycle).style("stroke", pipeColor);
    d3.select("#cycle" + cycle).style("stroke-opacity", "1");

    // Radiators independently choose probe temperature, TRV percentage, then piping colour.
    if (cycle == 1) {
        d3.select("#cycle" + cycle + "_2").style("stroke", pipeColor);
        d3.select("#cycle" + cycle + "_2").style("stroke-opacity", "1");
    }

}

let boilerState = null;
let boilerColdWaterError = false;

function boilerWaterTooCold(system) {
    const temperatures = [1,2,3,4].map(cycle=>cycleSupplyTemperature(system,cycle))
        .filter(value=>Number.isFinite(value) && value>0 && value<100);
    return temperatures.length>0 && Math.max(...temperatures)<25;
}

function updateBoilerColor(state, coldWaterError = false) {
    boilerColdWaterError = coldWaterError;
    d3.select("#boiler_body")
        .style("stroke-opacity", "0")
        .style("fill", "white")

    d3.select("#flame_nest").style("fill", "rgba(0.2,0.2,0.2,1)");
    d3.select("#flame_nest").style("fill-opacity", "1");

    d3.select("#boiler_body").style("stroke", coldWaterError ? "black" : state == 1 ? "rgba(255,0,0,1)" : "rgba(0,0,255,1)");
    d3.select("#boiler_body").style("stroke-opacity", "1");
    boilerState = state;
}

let pastNDaysAverageRoomTemps = {}

function extractPastNDaysAverage(roomNum) {
    const n = 3;

    function calculateDaysAverage(data) {
        const binWidthHours = 0.25;                                     // 15‑min bins
        const bins = Array.from({ length: 96 }, () => ({ sum: 0, n: 0 }));

        for (const day of Object.values(data)) {
            const readings = Object.values(day).find(Array.isArray);      // first room_* array
            if (!readings) continue;

            for (const { h_of_day_frac: h, temp } of readings) {
                if (h == null || temp == null) continue;
                const idx = Math.min(95, Math.floor(h / binWidthHours));    // 0‑95
                bins[idx].sum += temp;
                bins[idx].n += 1;
            }
        }

        const avgTemp = [];
        for (let i = 0; i < 96; i++) {
            if (bins[i].n) avgTemp.push({ h_of_day_frac: i * binWidthHours, temp: bins[i].sum / bins[i].n });
        }                                           // daily average curve

        pastNDaysAverageRoomTemps[roomNum] = avgTemp;
    }

    if (!pastNDaysAverageRoomTemps[roomNum]) {
        collectDataFromGitHub(
            dataToCollectGenerator(
                dayStamp(addTimeToDate(new Date(), -n, "days"), false, 0),
                dayStamp(),
                ["room_" + roomNum + "_measurements"]
            ),
            calculateDaysAverage,
        )
    }
}

function addKPIsToTooltip(kpiData = null) {
    if (kpiData == null) {
        collectDataFromGitHub(
            dataToCollectGenerator(
                dayStamp(addTimeToDate(new Date(), -7, "days"), false, 0),
                dayStamp(),
                ["room_KPIs"]
            ),
            addKPIsToTooltip,
        );
    }
    else {
        let daysWithKPIData = Object.keys(kpiData)
        for (room of allControlledRooms) {
            let roomKPIData = [];
            for (day of daysWithKPIData) {
                roomKPIData.push(kpiData[day].room_KPIs[room])
            }

            // Validity
            let validity = normalize(roomKPIData.map(dayData => dayData.validity_ratio).slice(0, -1));

            // Below
            let below = roomKPIData.map(dayData => dayData.below);
            let belowAvg = dot(validity, below.slice(0, -1));
            let belowToday = below[below.length - 1];
            roomsDataAndState[room].below = {
                avg: belowAvg,
                today: belowToday
            }

            // Above
            let above = roomKPIData.map(dayData => dayData.above);
            let aboveAvg = dot(validity, above.slice(0, -1));
            let aboveToday = above[above.length - 1];
            roomsDataAndState[room].above = {
                avg: aboveAvg,
                today: aboveToday
            }

            // Turnon
            let turnon = roomKPIData.map(dayData => dayData.turn_on_ratio);
            let turnonAvg = dot(validity, turnon.slice(0, -1));
            let turnonToday = turnon[turnon.length - 1];
            roomsDataAndState[room].turnon = {
                avg: turnonAvg,
                today: turnonToday
            }
        }
    }
}

let currentGasUsageRate, currentGasTotal;

function writeGasUsageToDial(gasData = null, replaying = false) {
    if (dashboardReplayActive() && !replaying) return;
    if (gasData == null) {
        collectDataFromGitHub(
            [
                {
                    day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime),
                    type: "gas_usage"
                }
            ],
            writeGasUsageToDial
        );
    }
    else {
        gasData = gasData[dayStamp(replaying ? dashboardNow() : new Date(), !replaying && dayDataNotAvailable, dataWaitTime)]?.gas_usage;
        if (!gasData?.length) return;
        d3.select("#gas_piping").style("stroke", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_piping").style("stroke-opacity", "1");
        d3.select("#gas_meter").style("fill", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_meter").style("fill-opacity", "1");
        d3.select("#gas_meter2").style("fill", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_meter2").style("fill-opacity", "1");

        currentGasTotal = roundTo(gasData[gasData.length - 1].burnt_volume, 0.1);
        //console.log(currentGasTotal)
        if (!isValidNumber(currentGasTotal)) { currentGasTotal = 0 };

        //if (isValidNumber(currentGasUsageRate) == false) {
        //    currentGasUsageRate = roundTo(gasData[gasData.length - 1].burn_rate_in_m3_per_h, 0.1);
        //}

        const dialBoxBB = getBBoxDrawingDimensions("gas_dial");
        let textXOffsetFactor;
        gasTotal = roundTo(gasData[gasData.length - 1].burnt_volume, 0.1);
        if (Number.isInteger(gasTotal)) {
            gasTotal += ".0";
        }
        if (gasTotal < 10) {
            textXOffsetFactor = 0.16;
        }
        else {
            textXOffsetFactor = 0.05;
        }
        d3.selectAll(".gas_dial_text").remove();
        d3.select("#drawing")
            .append("text")
            .attr("class", "gas_dial_text clickthrough")
            .attr("x", dialBoxBB.x + dialBoxBB.width * textXOffsetFactor)
            .attr("y", dialBoxBB.y + dialBoxBB.height * 0.7)
            .text(gasTotal)
            .style("font-family", dashboardFont)
            .style("font-size", "6.5px")
            .style("fill", "black");
        d3.select("#drawing")
            .append("text")
            .attr("class", "gas_dial_text clickthrough")
            .attr("x", dialBoxBB.x + dialBoxBB.width * 0.732)
            .attr("y", dialBoxBB.y + dialBoxBB.height * 0.69)
            .text(" m³")
            .style("font-family", dashboardFont)
            .style("font-size", "5px")
            .style("fill", "black");
        //d3.select("#drawing")
        //    .append("rect")
        //    .attr("id", "gas_dial_hover_area")
        //    .attr("x", dialBoxBB.x)
        //    .attr("y", dialBoxBB.y)
        //    .attr("width", dialBoxBB.w)
        //    .attr("height", dialBoxBB.h)
        //    .style("fill", "transparent")
        //    .style("pointer-events", "all");
    }
}

let externalTemp;
function initializeExternalThermometer() {
    d3.select("#external_thermometer")
        .style("fill", "rgba(253,253,253,1)")
        .style("fill-opacity", 1)
        .style("stroke", "rgba(0,0,0,0.75)")
        .style("stroke-opacity", 1)
        .style("stroke-width", 0.5);
}

function initializeCycleMarkers() {
    for (let cycle = 1; cycle < 5; cycle++) {
        const markerBB = getBBoxDrawingDimensions("cycle" + cycle + "_marker");
        d3.select("#cycle" + cycle + "_marker_border")
            .style("stroke", "black")
            .style("stroke-opacity", "1")
            .style("fill", "black")
            .style("fill-opacity", "1");

        d3.select("#drawing")
            .append("text")
            .attr("class", "cycle" + cycle + "_marker clickthrough")
            .attr("x", markerBB.x + markerBB.width * 0.05)
            .attr("y", markerBB.y + markerBB.height * 0.8)
            .text(cycle + "|")
            .style("font-family", dashboardFont)
            .style("font-size", "4.5px")
            .style("fill", "black");
    }
}

let lastKnownPumpPowers = [null, null, null, null];

function writePumpPowerToCycleMarkers(pumpsPowerData) {
    for (let cycle = 1; cycle < 5; cycle++) {
        let currentPower = lastKnownPumpPowers[cycle - 1]

        if (!currentPower) {
            if (systemNode) {
                currentPower = systemNode['state']['pumps']['power'][cycle];
            }
            else {
                if (pumpsPowerData == null) {
                    collectDataFromGitHub(
                        [
                            {
                                day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime),
                                type: "pumps_power"
                            }
                        ],
                        writePumpPowerToCycleMarkers
                    );
                }
                else {
                    pumpsPowerData = pumpsPowerData[dayStamp(new Date(), dayDataNotAvailable, dataWaitTime)]["pumps_power"];
                    currentPower = pumpsPowerData[pumpsPowerData.length - 1]['pump_' + cycle + '_power'];
                }
            }

            currentPower = roundTo(currentPower, 1);
        }

        const markerBB = getBBoxDrawingDimensions("cycle" + cycle + "_marker");
        d3.selectAll(".cycle" + cycle + "_marker_text").remove();

        let textXOffsetFactor;
        if (currentPower < 10) {
            textXOffsetFactor = 1.44;
        }
        else {
            textXOffsetFactor = 1;
        }

        d3.select("#drawing")
            .append("text")
            .attr("class", "cycle" + cycle + "_marker_text clickthrough")
            .attr("x", markerBB.x + markerBB.width * 0.42 * textXOffsetFactor)
            .attr("y", markerBB.y + markerBB.height * 0.8)
            .text(currentPower)
            .style("font-family", dashboardFont)
            .style("font-size", "4.5px")
            .style("fill", "black");

        d3.select("#drawing")
            .append("text")
            .attr("class", "cycle" + cycle + "_marker_text clickthrough")
            .attr("x", markerBB.x + markerBB.width * 0.86)
            .attr("y", markerBB.y + markerBB.height * 0.75)
            .text(" W")
            .style("font-family", dashboardFont)
            .style("font-size", "2.25px")
            .style("fill", "black");
    }
}

function initializeInfoboxes() {
    d3.select("#general_infobox")
        .style("fill", "rgba(250,250,250,1)")
        .style("fill-opacity", "1")
        .style("stroke", "rgba(250,250,250,1)")
        .style("stroke-opacity", "1")
        .style("stroke-width", "3");

    if (isMobile) {
        for (let cycleNum = 1; cycleNum < 5; cycleNum++) {
            d3.select("#cycle" + cycleNum + "_infobox")
                .style("fill", "rgba(250,250,250,1)")
                .style("fill-opacity", "1")
                .style("stroke", "rgba(250,250,250,1)")
                .style("stroke-opacity", "1")
                .style("stroke-width", "3");
        }
    }
    else {
        d3.select("#cycles_infobox")
            .style("fill", "rgba(250,250,250,1)")
            .style("fill-opacity", "1")
            .style("stroke", "rgba(250,250,250,1)")
            .style("stroke-opacity", "1")
            .style("stroke-width", "3");
    }
}

function initializeMainGraphArea() {
    let graphDims = getBBoxDrawingDimensions("graph");
    d3.select("#graph").style("fill-opacity", "0")

    d3.select("#drawing").append("text")
        .attr("x", graphDims.cx) // X-coordinate
        .attr("y", graphDims.cy) // Y-coordinate
        .attr("text-anchor", "middle") // Horizontally center
        .attr("dominant-baseline", "middle") // Vertically center
        .text(dashboardText("Adatok betöltése.")) // Text content
        .attr("fill", "black") // Text color (SVG uses `fill` for text color)
        .style("font-family", dashboardFont) // Font family
        .style("font-size", "10px"); // Font size
}

let roomAbbreviations = {
    "Oktopusz": "Okt.",
    "Oktopusz szita": "Okt.sz.",
    "Oktopusz kerámia": "Okt.k.",
    "Gólyafészek": "Gólyaf.",
    "PK": "PK",
    "SZGK": "SZGK",
    "Mérce": "Mérce",
    "Gólyairoda": "Gólyai.",
    "Lahmacun": "Lahma.",
    "vendégtér": "vendégt.",
    "kisterem": "kist.",
    "Trafóház": "Traf.",
    "Diós Edit": "D.E."
}

function addLineToBox(boxId, message, xPosFactor, yPosFactor, fontSize, centered = false) {
    let boxDims = getBBoxDrawingDimensions(boxId);
    let x = boxDims.x;
    let y = boxDims.y;
    let w = boxDims.w;
    let h = boxDims.h;
    return d3.select("#drawing")
        .append("text")
        .attr("class", boxId + "-content clickthrough")
        .attr("x", x + (centered ? w * 0.5 : 0) + w * xPosFactor)
        .attr("y", y + h * yPosFactor)
        .text(dashboardText(message))
        .style("text-anchor", centered ? "middle" : "left")
        .style("font-family", dashboardFont)
        .style("font-size", fontSize + "px");
}

function infoboxRoomTemperature(system, rooms, now = typeof dashboardNow === 'function' ? dashboardNow() : new Date()) {
    const state = system.state || {};
    const values = rooms.filter(room => livePlotFresh(state.sensor_last_updated?.[room],7200,now))
        .map(room => state.measured_temps?.[room]).filter(Number.isFinite);
    return values.length ? d3.mean(values) : null;
}

function infoboxCirculatedWaterTemperature(system) {
    const cycles = [1,2,3,4];
    const running = cycles.filter(cycle => system.state?.pump_states?.[cycle] === 1);
    const values = (running.length ? running : cycles)
        .map(cycle => cycleSupplyTemperature(system,cycle)).filter(Number.isFinite);
    return values.length ? d3.mean(values) : null;
}

function updateGeneralInfobox(info) {
    d3.selectAll(".general_infobox-content").remove();
    let boxDims = getBBoxDrawingDimensions("general_infobox");

    let allCentered = false;
    let lineFontSize = isMobile ? 13 : 6.5;
    let lineHeight = isMobile ? 0.135 : 0.067;
    let lineXOffset = isMobile ? 10 / boxDims.w : 2 / boxDims.w;
    let indentLineXOffset = isMobile ? 0.05 : 0;
    let lineYOffset = isMobile ? 0.03 : 0;

    // Draw title
    let titleXPos = isMobile ? 0.015 : 0.025;
    let titleYPos = isMobile ? 0.1 : 0.065;
    let titleLine = addLineToBox("general_infobox", "Rendszerállapot", lineXOffset + titleXPos, lineYOffset + titleYPos, lineFontSize * 1.1, allCentered);
    if (info.boilerError) {
        addLineToBox("general_infobox", "kazán hiba!",
            lineXOffset + titleXPos + (titleLine.node().getComputedTextLength() + lineFontSize*.6) / boxDims.w,
            lineYOffset + titleYPos, lineFontSize * 1.1, false)
            .style('fill','red').style('font-weight','normal').classed('boiler-error-warning',true);
    }
    if (isMobile) {
        titleLine.style("font-weight", "bold");
    }
    else {
        titleLine.style("text-decoration", "underline");
    }

    let lines = []; 
    if (info.heatingOn == 1) {
        // Generate lines from incoming info
        if (!isMobile) {
            lines.push({lineXOffset:0, text:(info.cyclesOn.length ? "Keringetett fűtővíz: " : "Készenléti fűtővíz: ")
                + (Number.isFinite(info.waterTemp) ? Math.round(info.waterTemp) + " °C" : "—")});
            let cyclesOnLine = info.cyclesOn.length > 0 ? "Keringetett körök: " + info.cyclesOn.join(", ") + "." : "Senki nem kér fűtést.";
            lines.push(
                {
                    lineXOffset: 0,
                    text: cyclesOnLine
                }
            );
            lines.push(
                {
                    lineXOffset: 0,
                    text: ""
                }
            );
        }

        if (isMobile) {
            if (info.lastRequest.granularity == "órája" && info.lastRequest.timeSince > getFractionalHourOfDay()) {
                lines.push(
                    {
                        lineXOffset: 0,
                        text: "Ma még nem érkezett kérés."
                    }
                );
                lines.push(
                    {
                        lineXOffset: 0,
                        text: ""
                    }
                );
            } else {
                let lastRequestLine1 = "Utolsó kérés:";
                let lastRequestLine2 = "- " + info.lastRequest.hourStamp + ", " + info.lastRequest.origin + ", " + info.lastRequest.target + ".";
                lines.push(
                    {
                        lineXOffset: 0,
                        text: lastRequestLine1
                    }
                );
                lines.push(
                    {
                        lineXOffset: indentLineXOffset,
                        text: lastRequestLine2
                    }
                );
            }
        } else {
            let lastRequestLine = "Utolsó kérés: " + info.lastRequest.hourStamp + ", " + info.lastRequest.origin + ", " + info.lastRequest.target + ".";
            if (info.lastRequest.granularity == "órája" && info.lastRequest.timeSince > getFractionalHourOfDay()) {
                lastRequestLine = "Ma még nem érkezett kérés.";
            }
            if (lastRequestLine.length > 36) {
                lastRequestLine = "Utolsó kérés: " + info.lastRequest.hourStamp + ", " + info.lastRequest.origin + ", " + (roomAbbreviations[info.lastRequest.target] || info.lastRequest.target) + ".";
            }
            lines.push(
                {
                    lineXOffset: 0,
                    text: lastRequestLine
                }
            );
        }

        if (isMobile) {
            let scheduleLastUpdatedLine1 = "Beállítások frissítve: ";
            let scheduleLastUpdatedLine2 = "- " + hourStamp(info.scheduleLastUpdated) + ".";
            lines.push(
                {
                    lineXOffset: 0,
                    text: scheduleLastUpdatedLine1
                }
            );
            lines.push(
                {
                    lineXOffset: indentLineXOffset,
                    text: scheduleLastUpdatedLine2
                }
            );
        } else {
            let scheduleLastUpdatedLine = "Beállítások frissítve: " + hourStamp(info.scheduleLastUpdated) + ".";
            lines.push(
                {
                    lineXOffset: 0,
                    text: scheduleLastUpdatedLine
                }
            );
        }

        if (isMobile) {
            let controlLastRunLine1 = "Vezérlés lefutott:";
            let controlLastRunLine2 = "- " + info.lastControlRun.timeSince + " " + info.lastControlRun.granularity + ".";
            lines.push(
                {
                    lineXOffset: 0,
                    text: controlLastRunLine1
                }
            );
            lines.push(
                {
                    lineXOffset: indentLineXOffset,
                    text: controlLastRunLine2
                }
            );
        } else {
            let controlLastRunLine = "Vezérlés lefutott: " + info.lastControlRun.timeSince + " " + info.lastControlRun.granularity + ".";
            //error: { error: controlError, timeSince: secondsSinceControlError, granularity: lastErrorGranularity, source: controlErrorSource }
            if (info.error.error || (info.lastControlRun.granularity == " perce" && info.lastControlRun.timeSince > 5)) {
                let errorFill, errorStroke;
                if (info.error.error) {
                    errorFill = "rgba(248, 212, 0, 0.05)";
                    errorStroke = "rgba(248, 212, 8, 1)";
                    controlLastRunLine = "Vezérlés: <" + info.error.source + "> hiba!";
                }
                else {
                    errorFill = "rgba(255,0,0,0.05)";
                    errorStroke = "rgba(250,0,0,1)";
                    controlLastRunLine = "Vezérlés: " + info.lastControlRun.timeSince + " " + info.lastControlRun.granularity + " áll!";
                }
                d3.select("#general_infobox")
                    .style("fill", errorFill)
                    .style("fill-opacity", "1")
                    .style("stroke", errorStroke)
                    .style("stroke-opacity", "0.5")
                    .style("stroke-width", "0.5");
            }
            else {
                d3.select("#general_infobox")
                    .style("fill", "rgba(250,250,250,1)")
                    .style("fill-opacity", "1")
                    .style("stroke", "rgba(250,250,250,1)")
                    .style("stroke-opacity", "1")
                    .style("stroke-width", "3");
            }
            lines.push(
                {
                    lineXOffset: 0,
                    text: controlLastRunLine
                }
            );
        }

        if (!isMobile) {
            lines.push(
                {
                    lineXOffset: 0,
                    text: ""
                }
            );

            let externalTempLine = "Külső hőmérséklet: " + (externalTemp ?? "—") + " °C.";
            lines.push(
                {
                    lineXOffset: 0,
                    text: externalTempLine
                }
            );

            let gasUsageLine = "Gázfogyasztási ráta: " + (isValidNumber(currentGasUsageRate) ? roundTo(currentGasUsageRate, 0.1) : "") + (isValidNumber(currentGasUsageRate) ? " m³/h." : "");
            lines.push(
                {
                    lineXOffset: 0,
                    text: gasUsageLine
                }
            );

            if (isValidNumber(currentGasTotal)) {
                let gasTotalString = currentGasTotal;
                if (Number.isInteger(gasTotalString)) {
                    gasTotalString += ".0";
                }
                lines.push(
                    {
                        lineXOffset: 0,
                        text: "Összes elégett gáz: " + gasTotalString + " m³."
                    }
                );

                let totalCost = currentGasTotal * 650;
                lines.push(
                    {
                        lineXOffset: 0,
                        text: "Összköltség kb. " + (totalCost < 1000 ? (roundTo(totalCost, 100) + " Ft.") : (roundTo(totalCost / 1000, 0.1) + " eFt.")
                        )
                    }
                );
            }
        }

        // Draw lines
        for (let line = 1; line <= lines.length; line++) {
            addLineToBox(
                "general_infobox",
                lines[line - 1].text,
                titleXPos + lineXOffset + lines[line - 1].lineXOffset,
                titleYPos + lineYOffset + lineHeight * line,
                lineFontSize, allCentered
            );
        }
    }
    else {
        addLineToBox(
            "general_infobox",
            "Fűtés kikapcsolva.",
            titleXPos + lineXOffset,
            titleYPos + lineYOffset + lineHeight * 1.5,
            lineFontSize, allCentered
        );
    }
}

function updateCycleInfobox(cycle, info) {
    let boxDims = getBBoxDrawingDimensions("cycle" + cycle + "_infobox");
    d3.selectAll(".cycle" + cycle + "_infobox-content").remove();

    let xOffset = isMobile ? 5 / boxDims.w : 2 / boxDims.w;
    let yOffset = isMobile ? -5 / boxDims.h : 1.5 / boxDims.h;
    let lineHeight = isMobile ? 20 / boxDims.h : 8 / boxDims.h;
    let lineFontSize = isMobile ? 13 : 6;
    let lineNum = 1;
    let lineNumShift = 0;
    let allCentered = isMobile ? false : false;

    // Draw title
    let cycleName = ["Kazán 1", "Kazán 2", "Presszó", "Trafóház"][cycle - 1];
    let titleLine = addLineToBox("cycle" + cycle + "_infobox", cycleName + ":", xOffset, yOffset + lineHeight * (lineNum + lineNumShift), lineFontSize * 1.1, false)
    if (isMobile) {
        titleLine.style("font-weight", "bold");
    }
    else {
        titleLine.style("text-decoration", "underline");
    }
    const cycleStatus = info.enabled === false ? "kör ki" : info.state === 1 ? "kering" : "áll";
    addLineToBox("cycle" + cycle + "_infobox", "\u00a0" + cycleStatus,
        xOffset + titleLine.node().getComputedTextLength() / boxDims.w,
        yOffset + lineHeight * (lineNum + lineNumShift), lineFontSize * 1.1, false);
    lineNum++;

    // Draw cycle details
    lineNumShift += 0.2;
    if (!isMobile) {
        const roomText = Number.isFinite(info.roomTemp) ? Number(info.roomTemp.toFixed(1)) + " °C" : "—";
        const waterText = Number.isFinite(info.waterTemp) ? Math.round(info.waterTemp) + " °C" : "—";
        addLineToBox("cycle" + cycle + "_infobox", "Szobák: " + roomText,
            xOffset, yOffset + lineHeight * (lineNum + lineNumShift), lineFontSize, allCentered);
        lineNum++;
        lineNumShift += 0.05;
        addLineToBox("cycle" + cycle + "_infobox", "Fűtővíz: " + waterText,
            xOffset, yOffset + lineHeight * (lineNum + lineNumShift), lineFontSize, allCentered);
    }

    lineNumShift = isMobile ? 0.25 : 1.5;
    let xOffsetShift = isMobile ? 0.04 : 0;
    if (cycle < 4) {
        if (info.wantHeating) {
            if (info.wantHeating.length > 0) {
                addLineToBox("cycle" + cycle + "_infobox", "Fűtést kér:", xOffset, yOffset + lineHeight * (lineNum + lineNumShift), lineFontSize, allCentered);
                lineNum++;
                info.wantHeating.forEach(roomInfo => {
                    addLineToBox("cycle" + cycle + "_infobox", "- " + roomInfo.name, xOffset + xOffsetShift, yOffset + lineHeight * (lineNum + lineNumShift), lineFontSize, allCentered);
                    lineNum++;
                    lineNumShift += 0.05;
                });
            } else {
                addLineToBox("cycle" + cycle + "_infobox", "Nem kér fűtést.", xOffset, yOffset + lineHeight * (lineNum + lineNumShift), lineFontSize, allCentered);
            }
        }
    }
    else {
        addLineToBox("cycle" + cycle + "_infobox", ["Nem kér fűtést.", "Fűtést kér."][info.set], xOffset, yOffset + lineHeight * (lineNum + lineNumShift), lineFontSize, allCentered);
    }
}

let dataWaitTime = 10;
let dayDataNotAvailable = false;

let allMeasuredRooms = roomV2IncludedRooms();
let allControlledRooms = roomV2ControlledRooms();
let allEmphasisRooms = allControlledRooms;

const elementToMainGraphSettingMapping = {
    "gas_dial": { title: "gas_usage", types: ["gas_usage", "heating_state"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), conditionals: [] },
    "cycle1_marker": { title: "pumps_power", types: ["pumps_power", "heating_state"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), conditionals: [], hoveredPump: 1 },
    "cycle2_marker": { title: "pumps_power", types: ["pumps_power", "heating_state"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), conditionals: [], hoveredPump: 2 },
    "cycle3_marker": { title: "pumps_power", types: ["pumps_power", "heating_state"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), conditionals: [], hoveredPump: 3 },
    "cycle4_marker": { title: "pumps_power", types: ["pumps_power", "heating_state"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), conditionals: [], hoveredPump: 4 },
    "external_thermometer": { title: "external_temp", types: ["external_temp"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), conditionals: [] },
    "boiler_body": {
        title: "heating_state",
        types: ["heating_state"],
        day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime),
        conditionals: [systemOn]
    },
    "background": { // Default
        title: "all_rooms",
        types: allMeasuredRooms.map(room => `room_${room}_measurements`).concat(["heating_state"]),
        day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime),
        roomNumsToPlot: allMeasuredRooms,
        hoveredCycle: 0,
        conditionals: []
    }
};

Object.assign(elementToMainGraphSettingMapping, roomV2PlotSettings());
// Kisudvar shares the outdoor thermometer's plots and detailed weather access.
elementToMainGraphSettingMapping.kisudvar = elementToMainGraphSettingMapping.external_thermometer;

for (let cycle = 1; cycle <= 4; cycle++) {
    const waterTemperatureSetting = createCycleHeatPlotSetting(cycle, "cycle" + cycle);
    elementToMainGraphSettingMapping["cycle" + cycle] = waterTemperatureSetting;
    elementToMainGraphSettingMapping['cycle' + cycle + '_marker'] = createCycleHeatPlotSetting(cycle, 'cycle' + cycle + '_marker');
    if (cycle === 1) {
        elementToMainGraphSettingMapping["cycle1_2"] = createCycleHeatPlotSetting(cycle, "cycle1_2");
    }
}

registerBoilerPowerPlots(elementToMainGraphSettingMapping);

let mainGraphContentLocked = false;
const mainGraphDefaultSetting = elementToMainGraphSettingMapping["background"]; // Save so it can be reset
let mainGraphSetting = mainGraphDefaultSetting;

function joinMainGrapDataSourceToElements() {
    d3.selectAll(Object.keys(elementToMainGraphSettingMapping).map(id => `#${id}`).join(","))
        .on("mouseover", function (event) {
            if (mainGraphContentLocked == false) {
                mainGraphSetting = elementToMainGraphSettingMapping[this.id]; // Set based on mapping
                drawMainGraph();
            }
        })
        .on("mouseout", function () {
            if (mainGraphContentLocked == false) {
                mainGraphSetting = mainGraphDefaultSetting; // Reset on mouseout
                drawMainGraph();
            }
        })
        .on("click.maingraph", function (event) {
            event.stopPropagation();
            const elementId = this.id === 'kisudvar' ? 'external_thermometer' : this.id;
            if (openRoomControlPlot(event, elementId)) return;
            if (openWeatherMetricPlot(event, elementId)) return;
            if (openCycleHeatPlot(event, elementId)) return;
            if (openRoomMetricPlot(event, elementId)) return;
            if (openBoilerMetricPlot(event, elementId)) return;
            if (openMobilePlotTarget(event, elementId)) return;
            mainGraphContentLocked = !mainGraphContentLocked;
            resetAllRoomsPlotToAllCycles(); // Workaround so that all_rooms plot is reset to default even if a mouseout was not activated on the cycle infoboxes

            mainGraphSetting = elementToMainGraphSettingMapping[elementId];
            drawMainGraph();
        });
    d3.select("body")
        .on("click", function (event) {
            if (mainGraphContentLocked) {
                mainGraphContentLocked = false;
                resetAllRoomsPlotToAllCycles(); // Workaround so that all_rooms plot is reset to default even if a mouseout was not activated on the cycle infoboxes
                drawMainGraph();
            }
        });
}

let cyclesDataAndState = Object.fromEntries([1,2,3,4].map(cycle => [cycle, {rooms: allMeasuredRooms.filter(id => roomsDataAndState[id].cycle === cycle)}]));

function resetAllRoomsPlotToAllCycles(showAllRoomHovers = false) {
    clearMobilePlotContext();
    mainGraphSetting = mainGraphDefaultSetting;
    mainGraphSetting.roomNumsToPlot = allMeasuredRooms;
    mainGraphSetting.hoveredCycle = 0;
    redrawRoomHovers(allEmphasisRooms, showAllRoomHovers);
}

function redrawInfoboxRoomHovers(rooms, emphasis) {
    redrawRoomHovers(rooms.filter(room => roomsDataAndState[room]?.controlled), emphasis);
}

function setInfoboxHovers() {
    for (let cycleNum = 1; cycleNum < 5; cycleNum++) {
        d3.select("#cycle" + cycleNum + "_infobox")
            .on("mouseover", function (event) {
                if (mainGraphSetting.title == 'all_rooms' && !mainGraphContentLocked) {
                    mainGraphSetting.hoveredCycle = cycleNum;
                    mainGraphSetting.roomNumsToPlot = cyclesDataAndState[cycleNum].rooms
                    drawMainGraph();
                    redrawInfoboxRoomHovers(mainGraphSetting.roomNumsToPlot, true);
                }
            })
            .on("mouseout", function () {
                if (mainGraphSetting.title == 'all_rooms' && !mainGraphContentLocked) {
                    resetAllRoomsPlotToAllCycles()
                    drawMainGraph();
                }
            })
            .on("click", function (event) {
                event.stopPropagation();
                if (openRoomControlPlot(event, this.id)) return;
                if (openMobilePlotTarget(event, this.id)) return;
                mainGraphContentLocked = !mainGraphContentLocked;
                redrawInfoboxRoomHovers(mainGraphSetting.roomNumsToPlot, false);
                mainGraphSetting.hoveredCycle = cycleNum;
                mainGraphSetting.roomNumsToPlot = cyclesDataAndState[cycleNum].rooms
                redrawInfoboxRoomHovers(mainGraphSetting.roomNumsToPlot, true);
                drawMainGraph();
            });
    }
    d3.select("#general_infobox")
        .on("mouseover", function (event) {
            if (mainGraphSetting.title == 'all_rooms' && !mainGraphContentLocked) {
                resetAllRoomsPlotToAllCycles(true)
                drawMainGraph();
            }
        })
        .on("mouseout", function () {
            if (mainGraphSetting.title == 'all_rooms' && !mainGraphContentLocked) {
                resetAllRoomsPlotToAllCycles(false)
                drawMainGraph();
            }
        })
        .on("click.general_infobox", function (event) {
            event.stopPropagation();
            if (openRoomControlPlot(event, this.id)) return;
            if (openMobilePlotTarget(event, this.id)) return;
            mainGraphContentLocked = !mainGraphContentLocked;
            resetAllRoomsPlotToAllCycles(true)
            drawMainGraph();
        });
}

const roomsColorScale = d3.scaleLinear().domain([1, 12]).range(["green", "orange"]); // Ha újabb szobát kell hozzáadni, akkor kell majd egy mapping a szobaszámok és a szín között, ami nem lineáris
const roomsColorRemap = [4, 5, 6, 7, 8, 1, 2, 10, 11, 12, -1, 9, 3]

let roomTextOffsets = roomV2TextOffsets();

function redrawRoomHovers(rooms, emphasis) {
    d3.selectAll(".room-emphasis").remove();
    rooms.forEach(roomNum => {
        if (roomsDataAndState[roomNum]) {
            let roomID = roomsDataAndState[roomNum].roomID;
            let roomName = roomsDataAndState[roomNum].name;
            let roomTemp = roomsDataAndState[roomNum].temp;
            let roomColor = d3.color(roomsColorScale(roomColorValue(roomNum)));
            let roomElement = d3.select("#" + roomID);
            if (roomElement.empty()) return;
            let roomBox = getBBoxDrawingDimensions(roomID);
            let parentParentElement = d3.select("#drawing");
            // Clone the roomElement
            let clonedElement = parentParentElement.append(() => roomV2CloneForEmphasis(roomElement.node()));

            // Style the cloned element
            clonedElement
                .style("fill", "none")
                .style("fill-opacity", "0")
                .style("stroke", emphasis ? roomColor : "black")
                .style("stroke-width", emphasis ? "2.5" : "0.25")
                .attr("class", "room-emphasis clickthrough")
                .raise();
            clonedElement.selectAll('*').style('fill', 'none').style('fill-opacity', '0');
            if (emphasis) {
                parentParentElement.append("text")
                    .attr("x", roomBox.x + roomBox.w / 2 + roomBox.w * roomTextOffsets[roomID].x) // Center horizontally
                    .attr("y", roomBox.y + roomBox.h / 2 + roomBox.h * roomTextOffsets[roomID].y) // Center vertically
                    .attr("text-anchor", "middle") // Align the text center horizontally
                    .attr("dominant-baseline", "middle") // Align the text center vertically
                    .style("fill", "white")
                    .style("font-size", roomNum == 7 ? "6" : "6")
                    .text(roomTemp)
                    .attr("class", "room-emphasis clickthrough")
                    .raise();

            }
        }
    });

    if (!emphasis) {
        d3.selectAll(".room-emphasis").remove();
    }
}

function drawRoomInfo(roomNum) {//IN DEVELOPMENT
    let roomID = roomsDataAndState[roomNum].roomID;
    let roomName = roomsDataAndState[roomNum].name;
    let roomTemp = roomsDataAndState[roomNum].temp;
    let roomColor = d3.color(roomsColorScale(roomColorValue(roomNum)));
    let roomElement = d3.select("#" + roomID);
            if (roomElement.empty()) return;
    let roomBox = getBBoxDrawingDimensions(roomID);
    let parentElement = d3.select(roomElement.node().parentNode);
    let parentParentElement = d3.select("#drawing");

    let roomInfo = roomName;
    //roomElement.raise();
    parentElement.append("text")
        .attr("x", roomBox.x + roomBox.w / 2 + roomBox.w * roomTextOffsets[roomID].x) // Center horizontally
        .attr("y", roomBox.y + roomBox.h / 2 + roomBox.h * roomTextOffsets[roomID].y) // Center vertically
        .attr("text-anchor", "middle") // Align the text center horizontally
        .attr("dominant-baseline", "middle") // Align the text center vertically
        .style("fill", "white")
        .style("font-size", roomNum == 7 ? "6" : "6")
        .text(dashboardText(roomInfo))
        .attr("class", "room-info clickthrough")
        .raise();
}

function drawMainGraph(graphData = null) {
    const changed = beginMainPlotLoading(mainGraphSetting);
    if (changed && graphData === null) {
        clearMainGraphs();
        drawPlot(undefined, {parentId: 'graph', domain: {bottom: [0, 24], left: [0, 1]},
            dataKeys: {bottom: 'x', left: 'y'}, axes: {left: false, bottom: false},
            plotLabel: '', curveEndText: {show: false}});
    }
    if (mainGraphSetting.title === 'boiler_kpi') {
        drawBoilerKPIView(graphData);
        return;
    }
    if (isRoomControlView(mainGraphSetting)) {
        drawRoomControlView(graphData);
        return;
    }
    if (graphData == null) {
        const requestedSetting = mainGraphSetting;
        collectDataFromGitHub(
            requestedSetting.types.map(type => ({
                day: requestedSetting.day,
                type: type
            })),
            data => {
                // A slower response for a previous hover must not replace the current cycle.
                if (mainGraphSetting === requestedSetting) drawMainGraph(data);
            },
        );
    }
    else {
        mainPlotLivePayload = {setting: mainGraphSetting, data: graphData};
        graphData = dashboardReplayActive() ? replayPlotPayload(graphData) : withLivePlotReadings(graphData, mainGraphSetting,
            typeof systemNode === 'undefined' ? null : systemNode);
        graphData = {...(graphData[mainGraphSetting.day] || {})};
        const ordinary = !['radiator', 'cycle_water_temp', 'room_metrics', 'weather_metrics', 'boiler_metrics'].includes(mainGraphSetting.title);
        const temperatureType = mainGraphSetting.title === 'room_plot' ? 'room_' + mainGraphSetting.roomNumToPlot + '_measurements' : null;
        const required = temperatureType ? [temperatureType] : mainGraphSetting.types.filter(type => !['override_requests', 'heating_state'].includes(type));
        if (ordinary && !required.some(type => Array.isArray(graphData[type]) && graphData[type].length) &&
            !(mainGraphSetting.title === 'heating_state' && graphData.heating_state?.length)) {
            clearMainGraphs();
            drawPlot([], {parentId: 'graph', domain: {bottom: [0, 24], left: [0, 1]},
                dataKeys: {bottom: 'x', left: 'y'}, axes: {left: false, bottom: false},
                plotLabel: '', emptyMessage: 'Az adott napra nincs adat.', curveEndText: {show: false}});
            return;
        }
        mainGraphSetting.types.forEach(type => {if (!graphData[type]) graphData[type] = [];});
        {
            clearMainGraphs();
            let range;
            switch (mainGraphSetting.title) {
                case 'boiler_metrics':
                    drawBoilerMetricPlot(graphData, mainGraphSetting);
                    break;
                case 'radiator':
                    drawRadiatorPlot(graphData, mainGraphSetting);
                    break;
                case "gas_usage":
                    range = [0, 10];

                    let heatingPeriodsForAllCycles = []
                    for (let cycleNum = 1; cycleNum < 5; cycleNum++) {
                        heatingPeriodsForAllCycles.push(extractHeatingPeriodsFromHeatingState(cycleNum, graphData["heating_state"]));
                    }

                    heatingPeriodsForAllCycles = heatingPeriodsForAllCycles.flat();

                    heatingPeriodsForAllCycles.forEach(period => {
                        period.y1 = Math.floor(range[0]);
                        period.y2 = Math.ceil(range[1]);
                        period.fill = "rgba(255,0,0,0.05)";
                        period.stroke = "rgba(255,0,0,0)";
                        period.strokeWeight = 0.25;
                        period.dashed = false;
                        period.dashing = "0.5,1";
                    });
                    //graphData["gas_usage"].pop();
                    //graphData["gas_usage"].push({ 'burn_rate_in_m3_per_h': currentGasUsageRate, 'h_of_day_frac': getFractionalHourOfDay(dateFromTimestamp(systemNode['state']['last_updated'])) })

                    drawPlot(
                        graphData["gas_usage"],
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 0 },
                            domain: { bottom: [0, 24], left: range },
                            tickVals: { bottom: false, left: [...Array(11).keys()] },
                            dataKeys: { bottom: "h_of_day_frac", left: "burn_rate_in_m3_per_h" },
                            axesLabel: { bottom: "óra", left: "ráta (m³/h)" },
                            plotLabel: (mainGraphSetting.day === dayStamp() ? 'mai' : 'napi') + " gázfogyasztás",
                            rects: { when: "before", list: heatingPeriodsForAllCycles }
                        }
                    );
                    drawPlot(
                        graphData["gas_usage"],
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 25 },
                            domain: { bottom: [0, 24], left: range },
                            tickVals: { bottom: false, left: [...Array(10).keys()] },
                            dataKeys: { bottom: "h_of_day_frac", left: "burn_rate_in_m3_per_h" },
                            background: { show: false },
                            plotStyle: { joined: true, col: "rgb(0, 0, 0)", thickness: "2", startCap: true, endCap: true },
                            segment: { do: true, gap: 2, endCaps: true, startCaps: true },
                            curveEndText: { show: true, fontSize: 5, text: ((graphData.gas_usage.slice(-10).reduce((s, e) => s + e.burn_rate_in_m3_per_h, 0) / graphData.gas_usage.slice(-10).length).toFixed(1).replace(/\.0$/, '')) + " m³/h", col: "rgba(50,50,50,1)", xOffset: 3, yOffset: 1.75 }
                        }
                    );
                    break;
                case "pumps_power":
                    cycleNum = mainGraphSetting.hoveredPump;
                    let latestPowerDataForCycle = graphData["pumps_power"].map(
                        item => ({
                            power: item['pump_' + cycleNum + '_power'],
                            h_of_day_frac: item.h_of_day_frac
                        })
                    );

                    let currentPower = latestPowerDataForCycle.at(-1)?.power;

                    const maxPower = Math.max(...latestPowerDataForCycle.map(item => item.power));
                    range = [0, maxPower + 1];

                    let heatingPeriodsForThisCycle = extractHeatingPeriodsFromHeatingState(cycleNum, graphData["heating_state"])
                    heatingPeriodsForThisCycle.forEach(period => {
                        period.y1 = Math.floor(range[0]);
                        period.y2 = Math.ceil(range[1]);
                        period.fill = "rgba(255,0,0,0.05)";
                        period.stroke = "rgba(255,0,0,0)";
                        period.strokeWeight = 0.25;
                        period.dashed = false;
                        period.dashing = "0.5,1";
                    });

                    const leftTicks = (m => {
                        const s = m < 1 ? 1 : m < 10 ? 2 : m < 100 ? 5 : Math.ceil(m / 10),
                            top = m < 1 ? 1 : Math.ceil(m / s) * s;
                        return Array.from({ length: top / s + 1 }, (_, i) => i * s);
                    })(maxPower);

                    drawPlot(
                        latestPowerDataForCycle,
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 0 },
                            domain: { bottom: [0, 24], left: range },
                            plotStyle: { joined: true, col: "rgba(20,20,20,0.9)", thickness: "1", smoothCurve: false, startCap: false, endCap: true },
                            tickVals: { bottom: false, left: leftTicks },
                            dataKeys: { bottom: "h_of_day_frac", left: "power" },
                            axesLabel: { bottom: "óra", left: "teljesítmény (W)" },
                            plotLabel: cycleNum + ["-es", "-es", "-mas", "-es"][cycleNum - 1] + " szivattyú " + (mainGraphSetting.day === dayStamp() ? 'mai' : 'napi') + " teljesítménygörbéje",
                            rects: { when: "before", list: heatingPeriodsForThisCycle },
                            curveEndText: { show: true, fontSize: 5, text: currentPower + " W", col: "rgba(50,50,50,1)", xOffset: 1.5, yOffset: 1.75 }
                        }
                    );
                    latestPowerDataForCycle.pop();
                    break;
                case "boiler_power":
                    drawBoilerPowerPlot(graphData, mainGraphSetting);
                    break;
                case "heating_state":
                    for (let cycle = 1; cycle < 5; cycle++) {
                        let maxHFrac = 0;
                        const cycleOnData = [];
                        const cycleOffData = [];
                        graphData["heating_state"].filter(entry => entry.cycle_states)
                            .forEach(entry => {
                                if (maxHFrac < entry.h_of_day_frac) {
                                    maxHFrac = entry.h_of_day_frac;
                                }
                                if (entry.cycle_states[cycle] == 1) {
                                    cycleOnData.push({
                                        h_of_day_frac: entry.h_of_day_frac,
                                        cycle_state: cycle
                                    });
                                }
                                else {
                                    cycleOffData.push({
                                        h_of_day_frac: entry.h_of_day_frac,
                                        cycle_state: cycle
                                    });
                                }
                            });
                        drawPlot(
                            cycleOffData,
                            {
                                parentId: "graph",
                                axes: { left: cycle == 1, bottom: cycle == 1 },
                                domain: { bottom: [0, 24], left: [0.5, 4.5] },
                                dataKeys: { bottom: "h_of_day_frac", left: "cycle_state" },
                                background: { show: cycle == 1, col: "white" },
                                plotStyle: { joined: true, col: "rgba(8, 86, 222, 0.23)", thickness: "6", startCap: false, endCap: false },
                                tickVals: { left: [1, 2, 3, 4] },
                                axesLabel: { bottom: cycle == 1 ? "óra" : false, left: cycle == 1 ? "kör" : false },
                                plotLabel: cycle == 1 ? "körök " + (mainGraphSetting.day === dayStamp() ? 'mai' : 'napi') + " kapcsolási mintázata" : false,
                                now: { show: cycle == 1, pos: maxHFrac },
                                segment: { do: true, gap: 0.1 }
                            }
                        );
                        drawPlot(
                            cycleOnData,
                            {
                                parentId: "graph",
                                domain: { bottom: [0, 24], left: [0.5, 4.5] },
                                dataKeys: { bottom: "h_of_day_frac", left: "cycle_state" },
                                background: { show: false },
                                tickVals: { left: [1, 2, 3, 4] },
                                plotStyle: { joined: true, col: "rgba(255, 64, 0, 0.75)", thickness: "8", startCap: false, endCap: false },
                                segment: { do: true, gap: 0.1 }
                            }
                        );
                    }
                    break;
                case "weather_metrics":
                    drawWeatherMetricPlot(graphData, mainGraphSetting);
                    break;
                case "room_metrics":
                    drawRoomMetricPlot(graphData, mainGraphSetting);
                    break;
                case "room_plot":
                    if (roomsDataAndState[mainGraphSetting.roomNumToPlot].controlled) {
                        let roomNum = mainGraphSetting.roomNumToPlot;
                        let cycleNum = roomsDataAndState[roomNum].cycle;
                        const isToday = mainGraphSetting.day === dayStamp();
                        let cycleOn = isToday ? systemNode['switch']['cycles'][cycleNum] != -1 : graphData['room_' + roomNum + '_set_temps']?.length > 0;

                        let roomSetTempsData = graphData["room_" + mainGraphSetting.roomNumToPlot + "_set_temps"];
                        let roomScheduleParts = extractRoomScheduleFromCondensedSchedule(mainGraphSetting.roomNumToPlot, roomSetTempsData, mainGraphSetting.day);
                        let roomScheduleData = roomScheduleParts.roomSchedule;
                        if (!cycleOn && isToday) {
                            extractPastNDaysAverage(mainGraphSetting.roomNumToPlot);
                        }
                        let roomMeasurementPastNDaysAverageData = isToday ? (pastNDaysAverageRoomTemps[mainGraphSetting.roomNumToPlot] || []) : [];
                        let roomMeasurementData = graphData["room_" + mainGraphSetting.roomNumToPlot + "_measurements"];
                        let roomMeasurementDisplayData = prepareRoomTemperatureForDisplay(roomMeasurementData);
                        let roomMeasurementPastNDaysAverageDisplayData = resampleRoomTemperatureForDisplay(roomMeasurementPastNDaysAverageData);

                        let hasValve = roomsDataAndState[roomNum].hasValve;
                        let roomValveStateData, roomValveCurrentState;
                        if (hasValve) {
                            roomValveStateData = (graphData["room_" + mainGraphSetting.roomNumToPlot + "_valve_state"] || []).slice();
                            roomValveCurrentState = roomValveStateData.at(-1)?.valve;
                            hasValve = roomValveStateData.length > 0;
                        }

                        if (cycleOn) {
                            //range = d3.extent(roomScheduleData.concat(roomMeasurementData).map(elem => elem['temp']));
                            range = d3.extent(
                                roomScheduleData
                                    .map(d => d.set_temp)
                                    .concat(roomMeasurementData.map(d => d.temp))
                                    .filter(v => v != null && !Number.isNaN(+v))
                                    .map(Number)
                            );

                        }
                        else {
                            range = d3.extent(roomMeasurementPastNDaysAverageData.concat(roomMeasurementData).map(elem => elem['temp']));
                            //range = d3.extent(roomMeasurementData.map(elem => elem['temp']));
                        }
                        //range = [14, 23]

                        let heatingState = graphData["heating_state"];
                        let heatingPeriods = extractHeatingPeriodsFromHeatingState(cycleNum, heatingState);

                        heatingPeriods.forEach(period => {
                            period.y1 = Math.floor(range[0]) - 1;
                            period.y2 = Math.ceil(range[1]) + 1;
                            period.fill = "rgba(255,0,0,0.08)";
                            period.stroke = "none";
                            period.strokeWeight = 0;
                            period.dashed = false;
                        });

                        let roomOverrides;
                        let requestMarkers = [];
                        if (isToday && requestLists) {
                            roomOverrides = requestLists[mainGraphSetting.roomNumToPlot];
                            if (roomOverrides) {
                                roomOverrides.forEach(request => {
                                    if (getUnixDay() == getUnixDay(dateFromTimestamp(request.time)) && getUnixDay() == getUnixDay(dateFromTimestamp(request.timestamp))) {
                                        requestMarkers.push({
                                            //x1: getFractionalHourOfDay(dateFromTimestamp(request.timestamp)),
                                            //x2: getFractionalHourOfDay(dateFromTimestamp(request.time)),
                                            pos: getFractionalHourOfDay(dateFromTimestamp(request.time)),
                                            h: parseInt(request.set_temp)
                                        })
                                    }
                                    else if (getUnixDay() == getUnixDay(dateFromTimestamp(request.time))) {
                                        requestMarkers.push({
                                            pos: getFractionalHourOfDay(dateFromTimestamp(request.time)),
                                            h: parseInt(request.set_temp)
                                        })
                                    }
                                });
                            }
                        }
                        if (cycleOn) {
                            drawPlot(
                                roomScheduleParts.roomScheduleAsOfYet,
                                {
                                    parentId: "graph",
                                    smoothing: { bottom: 0, left: 0 },
                                    domain: { bottom: [0, 24], left: [Math.floor(range[0]) - 1, Math.ceil(range[1]) + 1] },
                                    dataKeys: { bottom: "h_of_day_frac", left: "set_temp" },
                                    axesLabel: { bottom: "óra", left: "°C" },
                                    tickVals: { left: d3.range(Math.floor(range[0]) - 1, Math.ceil(range[1]) + 2, 1).filter(Number.isInteger) },
                                    plotStyle: { joined: true, col: "rgba(44, 213, 14, 0.92)", thickness: "2", startCap: false, endCap: true, linear: true },
                                    curveTooltip: "kért hőmérséklet",
                                    plotLabel: roomsDataAndState[mainGraphSetting.roomNumToPlot].name + " kért és mért hőmérséklet",
                                    rects: { when: "before", list: heatingPeriods },
                                    markers: { when: "after", list: requestMarkers, col: "rgba(245,245,0,1)", thickness: 1.5, dashed: true, dashing: "6,3", endCap: true, endCapSize: 2 }
                                }
                            );
                            drawPlot(
                                roomScheduleParts.roomScheduleRestOfDay,
                                {
                                    parentId: "graph",
                                    background: { show: false },
                                    smoothing: { bottom: 0, left: 0 },
                                    dataKeys: { bottom: "h_of_day_frac", left: "set_temp" },
                                    domain: { bottom: [0, 24], left: [Math.floor(range[0]) - 1, Math.ceil(range[1]) + 1] },
                                    plotStyle: { joined: true, col: "rgba(44, 213, 14, 0.41)", thickness: "2", startCap: false, endCap: false, linear: true, dashed: true, dashing: "5,2" },
                                    curveTooltip: "kért hőmérséklet"
                                }
                            );
                            if (hasValve) {
                                drawPlot(
                                    roomValveStateData,
                                    {
                                        parentId: "graph",
                                        axes: { left: false, bottom: false },
                                        background: { show: false },
                                        smoothing: { bottom: 0, left: 0 },
                                        domain: { bottom: [0, 24], left: [0, 1] },
                                        dataKeys: { bottom: "h_of_day_frac", left: "valve" },
                                        plotStyle: { joined: true, col: "rgba(50,50,50,0.85)", thickness: "0.5", startCap: false, endCap: true },
                                        curveTooltip: "radiátor nyitási százalék",
                                        segment: { do: true, gap: 10, endCaps: true, startCaps: true },
                                        curveEndText: { show: true, fontSize: 5, text: ((roomValveStateData.at(-1).valve * 100).toFixed(1).replace(/\.0$/, '')) + "%", col: "rgba(50,50,50,1)", xOffset: 1.5, yOffset: 1.75 }
                                    }
                                );
                            }
                            drawPlot(
                                roomMeasurementDisplayData,
                                {
                                    parentId: "graph",
                                    axes: { left: false, bottom: false },
                                    background: { show: false },
                                    smoothing: { bottom: 0, left: 10 },
                                    domain: { bottom: [0, 24], left: [Math.floor(range[0]) - 1, Math.ceil(range[1]) + 1] },
                                    dataKeys: { bottom: "h_of_day_frac", left: "temp" },
                                    plotStyle: { joined: true, col: "rgba(255,0,0,1)", thickness: "2", startCap: true, endCap: true },
                                    curveTooltip: "mért hőmérséklet",
                                    segment: { do: false },
                                    curveEndText: { show: true, fontSize: 6, text: ((roomMeasurementDisplayData.at(-1).temp).toFixed(1).replace(/\.0$/, '')) + "°C", col: "rgba(255,0,0,1)", xOffset: 3, yOffset: 1.75 }
                                }
                            );
                        }
                        else {
                            drawPlot(
                                roomMeasurementPastNDaysAverageDisplayData,
                                {
                                    parentId: "graph",
                                    smoothing: { bottom: 0, left: 30 },
                                    domain: { bottom: [0, 24], left: [Math.floor(range[0]), Math.ceil(range[1])] },
                                    dataKeys: { bottom: "h_of_day_frac", left: "temp" },
                                    axesLabel: { bottom: "óra", left: "°C" },
                                    tickVals: { left: d3.range(Math.floor(range[0]) - 0, Math.ceil(range[1]) + 1, 1) },
                                    plotStyle: { joined: true, col: "rgb(255, 154, 154,0.5)", thickness: "3", startCap: false, endCap: false },
                                    curveTooltip: "elmúlt 3 nap átlagos hőmérséklete",
                                    segment: { do: false },
                                    plotLabel: roomsDataAndState[mainGraphSetting.roomNumToPlot].name + " mért hőmérséklet" + (isToday ? " (+ elmúlt 3 nap átlaga)" : ''),
                                }
                            );
                            drawPlot(
                                roomMeasurementDisplayData,
                                {
                                    parentId: "graph",
                                    background: false,
                                    axes: { left: false, bottom: false },
                                    smoothing: { bottom: 0, left: 10 },
                                    domain: { bottom: [0, 24], left: [Math.floor(range[0]), Math.ceil(range[1])] },
                                    dataKeys: { bottom: "h_of_day_frac", left: "temp" },
                                    plotStyle: { joined: true, col: "rgb(255, 0, 0)", thickness: "2", startCap: true, endCap: true },
                                    curveTooltip: "mért hőmérséklet",
                                    segment: { do: false },
                                    curveEndText: { show: true, fontSize: 6, text: ((roomMeasurementDisplayData.at(-1).temp).toFixed(1).replace(/\.0$/, '')) + "°C", col: "rgba(255,0,0,1)", xOffset: 3, yOffset: 1.75 }
                                }
                            );
                        }
                    }
                    else { drawRoomV2MeasuredPlot(graphData, mainGraphSetting); }
                    break;
                case "all_rooms":
                    Object.keys(graphData).forEach(k => Array.isArray(graphData[k]) && (graphData[k] = graphData[k].filter(elem => elem.timestamp?.slice(0, 10) === mainGraphSetting.day)));
                    let drawForSingleCycle = mainGraphSetting.hoveredCycle > 0;
                    const overviewRoomIds = drawForSingleCycle ? allControlledRooms : allMeasuredRooms;
                    const overviewGroups = roomOverviewGroups(graphData, overviewRoomIds,
                        roomsDataAndState, mainGraphSetting.roomNumsToPlot, prepareRoomTemperatureForDisplay);
                    const overviewValues = overviewGroups.flatMap(group => group.data.map(row => row.temp));
                    range = overviewValues.length ? d3.extent(overviewValues) : [15, 25];

                    let heatingState = graphData["heating_state"];
                    let heatingPeriods
                    if (drawForSingleCycle) {
                        heatingPeriods = extractHeatingPeriodsFromHeatingState(mainGraphSetting.hoveredCycle, heatingState);
                        heatingPeriods.forEach(period => {
                            period.y1 = Math.floor(range[0]);
                            period.y2 = Math.ceil(range[1]);
                            period.fill = "rgba(255,0,0,0.1)";
                            period.stroke = "none";
                            period.strokeWeight = 0;
                            period.dashed = false;
                        });
                    }

                    drawPlot(
                        [],
                        {
                            axes: { left: true, bottom: true },
                            axesLabel: { bottom: "óra", left: "°C" },
                            plotLabel: "szobák " + (mainGraphSetting.day === dayStamp() ? 'mai' : 'napi') + " hőmérsékleti görbéje" + (drawForSingleCycle ? " a" + ["z 1-es", " 2-es", " 3-mas", " 4-es"][mainGraphSetting.hoveredCycle - 1] + " körön" : ""),
                            parentId: "graph",
                            background: { show: true },
                            domain: { bottom: [0, 24], left: [Math.floor(range[0]), Math.ceil(range[1])] },
                            tickVals: { left: d3.range(Math.floor(range[0]), Math.ceil(range[1]) + 1, 1) },
                            dataKeys: { bottom: "h_of_day_frac", left: "temp" },
                            plotStyle: { joined: true, col: "rgba(0,0,0,0)", thickness: "1", startCap: false, endCap: true, hoverableCurve: false },
                            segment: { do: false, gap: 0, endCaps: true, startCaps: true },
                            rects: drawForSingleCycle ? { when: "before", list: heatingPeriods } : false
                        }
                    );
                    overviewGroups.forEach(group => {
                        if (!group.data.length) return;
                        let emphasis = group.emphasis;
                        let plotColor = d3.color(roomsColorScale(roomColorValue(group.colorRoom)));
                        let showEndText = true;
                        let endTextColor = "rgba(0,0,0,1)";
                        if (!emphasis) {
                            plotColor.opacity = 0.1;
                            showEndText = false;
                            endTextColor = "rgba(0,0,0,0.25)"
                        }
                        plotColor = plotColor.toString();
                        drawPlot(
                            group.data,
                            {
                                axes: { left: false, bottom: false },
                                axesLabel: { bottom: false, left: false },
                                plotLabel: false,
                                parentId: "graph",
                                background: { show: false },
                                smoothing: { bottom: 0, left: 25 },
                                domain: { bottom: [0, 24], left: [Math.floor(range[0]), Math.ceil(range[1])] },
                                dataKeys: { bottom: "h_of_day_frac", left: "temp" },
                                plotStyle: { joined: true, col: plotColor, thickness: "1.25", startCap: true, endCap: true, hoverableCurve: emphasis },
                                curveEndText: { show: showEndText, fontSize: 5, text: group.name, col: plotColor, xOffset: 2.5, yOffset: 1.5 },
                                segment: { do: false }
                            }
                        );
                    });
                    break;
                case "cycle_water_temp": {
                    drawCycleHeatPlot(graphData, mainGraphSetting);
                    break;
                }
                case "external_temp": {
                    const externalReadings = (graphData.external_temp || []).filter(elem => Number.isFinite(elem.external_temp));
                    let tempRange = externalReadings.length ? d3.extent(externalReadings.map(elem => elem.external_temp)) : [0, 1];
                    drawPlot(
                        externalReadings,
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 10 },
                            domain: { bottom: [0, 24], left: [Math.floor(tempRange[0]) - 1, Math.ceil(tempRange[1]) + 1] },
                            dataKeys: { bottom: "h_of_day_frac", left: "external_temp" },
                            axesLabel: { bottom: "óra", left: "°C" },
                            tickVals: { left: d3.range(Math.floor(tempRange[0]) - 1, Math.ceil(tempRange[1]) + 2, 1) },
                            plotStyle: { joined: true, col: "rgba(28, 3, 252, 0.92)", thickness: "3", startCap: false, endCap: true, smoothCurve: true },
                            plotLabel: (mainGraphSetting.day === dayStamp() ? 'mai' : 'napi') + " külső hőmérséklet",
                            curveEndText: { show: externalReadings.length > 0, fontSize: 6.5, text: externalReadings.length ? externalReadings.at(-1).external_temp.toFixed(1).replace(/\.0$/, '') + "°C" : "", col: "rgba(28, 3, 252, 0.92)", xOffset: 5, yOffset: 1.4 }
                        }
                    );
                    break;
                }
            }
        }
    }
}

function rescueMainGraph() {
    if (d3.selectAll(".main-graph-instance").size() == 0) {
        drawMainGraph();
    }
}

let fromRequest, centeredId, isMobile, forcedZoom;

function extractURLParams() {
    let params = new URLSearchParams(window.location.search);
    fromRequest = params.get("ref_source") == "form";
    centeredId = params.get("centered_id") || "background";
    console.log(params.get("centered_id"));
    isMobile = params.get("mobile") == "true" || getIsMobile();
    forcedZoom = params.get("zoom") || 1;
}

function getIsMobile() {
    //return /Mobi|Android/i.test(navigator.userAgent);
    return false;
}

let initialZoom, initialPos;
let initialLockDone = false; // Used at initial locking of main graph

function setViewParameters() {
    centeredId = d3.select("#" + centeredId).empty() ? "background" : centeredId; // Check if what's asked for in params is actually there, if not, set background

    const width = window.innerWidth;
    const height = window.innerHeight;
    let smallerDimension = Math.min(width, height);

    let baseCenteredDims = getBBoxRelativeDimensions("background");

    let idiosyncraticFactor = 1;
    let centeringOffsetFactor = { x: 1, y: 1 }

    if (isMobile) {
        idiosyncraticFactor = 0.72;
        centeringOffsetFactor = { x: 1, y: 1.25 };
    }

    let centeredDims = getBBoxRelativeDimensions(centeredId);
    let baseZoomFactor = 0.0032; // Empirically determined
    let centeringFactor = baseCenteredDims.w / centeredDims.w * (centeredId == "background" ? 1 : 0.8);

    initialZoom = smallerDimension * baseZoomFactor * centeringFactor * idiosyncraticFactor * forcedZoom;
    initialPos = { x: centeredDims.cx * centeringOffsetFactor.x, y: centeredDims.cy * centeringOffsetFactor.y };
}

let dashboardFont = "Consolas";

function addSpringyEasterEgg(elementId, textId, topLayerId, tooltipId) {
    // Select the elements
    const hidingElement = d3.select(`#${elementId}`);
    const easterEggText = d3.select(`#${textId}`);
    const topLayer = d3.select(`#${topLayerId}`);

    // Hide the text by default
    easterEggText.style("opacity", 0);

    // We'll store:
    //   - anchorX, anchorY: element's original transform
    //   - startX, startY:   pointer's starting position of the drag
    //   - originalParent, nextSibling for DOM re-insertion after drag
    let anchorX = 0,
        anchorY = 0,
        startX = 0,
        startY = 0,
        originalParent = null,
        nextSibling = null;

    // Flag to prevent new drag starts while snapping back
    let isSnapping = false;

    // Helper to parse any existing transform on the element
    function getTransformValues(selection) {
        const transform = selection.attr("transform");
        if (transform) {
            const match = transform.match(/translate\(([-\d.]+),\s*([-\d.]+)\)/);
            if (match) {
                return [parseFloat(match[1]), parseFloat(match[2])];
            }
        }
        return [0, 0];
    }

    const dragBehavior = d3.drag()
        .on("start", function (event) {
            // If the element is still snapping back from a previous drag, ignore a new drag
            if (isSnapping) {
                // Prevent the global drag from picking it up
                event.sourceEvent.stopPropagation();
                return;
            }

            // Hide the tooltip so it won't linger or follow
            d3.select(`#${tooltipId}`).style("opacity", 0);

            // 1) Get the element's current location
            [anchorX, anchorY] = getTransformValues(hidingElement);

            // 2) Record where the pointer started
            startX = event.x;
            startY = event.y;

            // 3) Move this element into a "top layer" so it renders above others
            const node = hidingElement.node();
            originalParent = node.parentNode;
            nextSibling = node.nextSibling;
            topLayer.node().appendChild(node);

            // 4) Show the hidden text
            easterEggText.transition().duration(200).style("opacity", 1);
        })
        .on("drag", function (event) {
            // Move the element smoothly with the pointer
            const dx = event.x - startX;
            const dy = event.y - startY;
            hidingElement.attr("transform", `translate(${anchorX + dx}, ${anchorY + dy})`);
        })
        .on("end", function () {
            // Now we snap back with an elastic easing
            isSnapping = true;
            hidingElement
                .transition()
                .duration(600)
                .ease(d3.easeElastic)
                .attr("transform", `translate(${anchorX}, ${anchorY})`)
                .on("end", function () {
                    // Once snapping completes, restore the element to its original parent in the DOM
                    const node = hidingElement.node();
                    if (nextSibling) {
                        originalParent.insertBefore(node, nextSibling);
                    } else {
                        originalParent.appendChild(node);
                    }
                    isSnapping = false;
                });

            // Hide the hidden text again
            easterEggText.transition().duration(200).style("opacity", 0);

            //Show tooltip again
            d3.select(`#${tooltipId}`).style("opacity", 1);
        });

    // Attach the drag behavior
    hidingElement.call(dragBehavior);

    // Prevent global pan/zoom from taking over on mousedown
    hidingElement.on("mousedown", function (event) {
        event.stopPropagation();
    });
}

extractURLParams();
trackHoveredElementId();
d3.xml("canvas.svg?updated=" + Date.now()).then(fileData => {
    insertCanvasFromFile(fileData);
    setViewParameters();
    centerAndZoomRelativePointOfCanvas(initialPos.x, initialPos.y, initialZoom);

    setupTooltip();
    initializeExternalThermometer();
    initializeCycleMarkers();
    initializeBoilerPowerMarkers();
    initializeInfoboxes();
    initializeMainGraphArea();
    initializeReplayPane();
    initializeReplayClock();
    initializeRadiators();
    setInfoboxHovers();
    if (!isMobile) { // For now only in desktop view
        addSpringyEasterEgg("room_11", "kövek", "drawing", "tooltip");
    }

    runOnceThenSetInterval(joinMainGrapDataSourceToElements, 10);
    if (!isMobile) {
        //runOnceThenSetInterval(addKPIsToTooltip, 10 * 60 * 1000);
    }
    runOnceThenSetInterval(writeGasUsageToDial, 10 * 1000);
    runOnceThenSetInterval(writeCycleEnergyToMarkers, 10 * 1000);
    runOnceThenSetInterval(getDataFromFirebase, 5 * 1000);
    runOnceThenSetInterval(drawMainGraph, 60 * 1000);
    runOnceThenSetInterval(rescueMainGraph, 100);
    setTimeout(() => { if (!dashboardReplayActive()) location.reload(); }, new Date(new Date().getFullYear(), new Date().getMonth(), new Date().getDate() + 1, 0, 0, 1) - Date.now());
});
