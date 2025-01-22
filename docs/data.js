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

    // Append the cleaned group to the new SVG
    newDrawingGroup.appendChild(newGroup);


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
            mousePosition = getMousePosition();
            d3.select("#tooltip")
                .style("left", `${mousePosition.x + 5}px`)
                .style("top", `${mousePosition.y - 28}px`);
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

function setupTooltip() {
    // Setup tooltip
    const tooltip = d3.select("#tooltip");

    // Attach tooltip functionality to all path elements during initialization
    Object.keys(roomDataAndState).forEach(key => {
        const roomTooltipData = roomDataAndState[key]; // Access the value using the key

        d3.select("#" + roomTooltipData.roomID)
            .on("mouseover.tooltip", function (event) {
                if (roomTooltipData.temp != null) {
                    tooltip.transition().duration(200).style("visibility", "visible");
                    tooltip.html(
                        roomTooltipData.name + "<br>" +
                        roomTooltipData.temp + (!isNaN(roomTooltipData.temp) ? " °C" : "") +
                        (roomTooltipData.set != null ? "<br>(" + roomTooltipData.set + (!isNaN(roomTooltipData.set) ? " °C)" : ")") : "")
                    )
                        .style("left", (event.pageX + 5) + "px")
                        .style("top", (event.pageY - 28) + "px");
                }
                else {
                    tooltip.transition().duration(200).style("visibility", "hidden");
                }
            })
            .on("mousemove.tooltip", function (event) {
                tooltip.style("left", (event.pageX + 5) + "px")
                    .style("top", (event.pageY - 28) + "px");
            })
            .on("mouseout.tooltip", function () {
                tooltip.transition().duration(500).style("visibility", "hidden");
            })
    });
}

let condensedSchedule, requestLists;

function getDataFromFirebase() {
    const url = "https://kazanfutes-71b78-default-rtdb.europe-west1.firebasedatabase.app/.json";
    fetchJSONEndpoint(url)
        .then(fullFirebaseDataJSON => {
            const systemJSON = fullFirebaseDataJSON.system;
            const scheduleJSON = fullFirebaseDataJSON.schedule;
            const updateJSON = fullFirebaseDataJSON.update;

            condensedSchedule = scheduleJSON.condensed_schedule;
            requestLists = scheduleJSON.request_lists;


            // Update rooms
            const roomNums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            let controlDiffs = {};
            let totalControlDiff = 0;
            let averagerCount = 0;
            roomNums.forEach(roomNum => {
                const roomLastUpdated = systemJSON.state['sensor_last_updated'][roomNum];
                roomDataAndState[roomNum].lastUpdated = roomLastUpdated;

                const roomTemp = roundTo(systemJSON.state['measured_temps'][roomNum], 0.1);
                const timeSinceLastSensorUpdate = timePassedSince(dateFromTimestamp(roomLastUpdated));
                if (timeSinceLastSensorUpdate > 2 * 60) {
                    roomDataAndState[roomNum].temp = "szenzor hiba";
                }
                else {
                    roomDataAndState[roomNum].temp = (roomTemp.toFixed(2).slice(0, 4));
                }

                updateRoomColor(systemJSON.setup.rooms[roomNum].name, roomTemp, roomLastUpdated);

                const roomSet = systemJSON.state['set_temps'][roomNum];
                roomDataAndState[roomNum].set = roomSet;

                if (timeSinceLastSensorUpdate > 2 * 60) {
                    controlDiffs[roomNum] = "missing";

                }
                else {
                    controlDiffs[roomNum] = roomTemp - roomSet;
                    totalControlDiff += controlDiffs[roomNum];
                    averagerCount++;
                }
            });
            let averageControlDiff = (totalControlDiff - (isValidNumber(controlDiffs[10]) ? controlDiffs[10] : 0)) / (averagerCount - 1);

            const roomTemp = roundTo((systemJSON.state['oktopusz_keramia'][1] + systemJSON.state['oktopusz_keramia'][2]) / 2, 0.1);
            //const roomTemp = roundTo(systemJSON.state['oktopusz_keramia'][1],0.1);
            updateRoomColor("OktopuszKeramia", roomTemp, timestamp());
            roomDataAndState[11].temp = (roomTemp.toFixed(2).slice(0, 4));

            // Update piping
            const cycles = [1, 2, 3, 4];
            let states = 0;
            cycles.forEach(cycleNum => {
                const cycleState = systemJSON.state.pump_states[cycleNum];
                states += cycleState;
                updateCycleColor(cycleNum, cycleState);
            }
            );
            updateBoilerColor(states > 0 ? 1 : 0);

            // Update infoboxes
            let onCycles = [];
            cycles.forEach(cycleNum => {
                systemJSON.state.pump_states[cycleNum] == 1 ? onCycles.push(cycleNum) : "";
            });

            let lastControlRan = dateFromTimestamp(systemJSON.state.last_updated);
            let timeSinceControlLastRan = timePassedSince(lastControlRan, 'seconds');
            let lastControlRanGranularity = ' másodperce.'
            if (timeSinceControlLastRan > 90) {
                timeSinceControlLastRan = roundTo(timeSinceControlLastRan / 60, 0.1);
                lastControlRanGranularity = ' perce.'
            }
            else if (timeSinceControlLastRan > 90 * 30) {
                timeSinceControlLastRan = roundTo(timeSinceControlLastRan / 60 * 60, 0.1);
                lastControlRanGranularity = ' órája.'
            }
            if (timeSinceControlLastRan < 0) {
                timeSinceControlLastRan = 0
            }

            let lastScheduleUpdate = dateFromTimestamp(scheduleJSON.last_updated)
            let timeSinceLastScheduleUpdate = timePassedSince(lastScheduleUpdate, 'minutes');
            let schedLastUpdateGranularity = ' perce.';

            if (timeSinceLastScheduleUpdate > 90) {
                timeSinceLastScheduleUpdate = roundTo(timeSinceLastScheduleUpdate / 60, 0.1);
                schedLastUpdateGranularity = ' órája.'
            }

            let timeSinceLastRequest = Math.min(
                timePassedSince(dateFromTimestamp(updateJSON.override_rooms.last_update_timestamp)),
                timePassedSince(dateFromTimestamp(updateJSON.override_rooms_qr.last_update_timestamp))
            )
            timeSinceLastRequestGranularity = 'perce'
            if (timeSinceLastRequest > 90) {
                timeSinceLastRequest = roundTo(timeSinceLastRequest / 60, 0.5);
                timeSinceLastRequestGranularity = 'órája'
            }

            let requestOrigin = timePassedSince(dateFromTimestamp(updateJSON.override_rooms.last_update_timestamp))
                > timePassedSince(dateFromTimestamp(updateJSON.override_rooms_qr.last_update_timestamp)) ? "QR" : "form"
            let requestTarget = requestOrigin == "QR" ? updateJSON.override_rooms_qr.room_name : updateJSON.override_rooms.room_name

            let lastRequestHourStamp = hourStamp(requestOrigin == "QR" ? dateFromTimestamp(updateJSON.override_rooms_qr.last_update_timestamp) : dateFromTimestamp(updateJSON.override_rooms.last_update_timestamp));

            updateGeneralInfobox(
                {
                    cyclesOn: onCycles.length > 0 ? "Bekapcsolt körök: " + onCycles.join(", ") + "." : "Senki nem kér fűtést.",
                    externalTemp: "Külső hőmérséklet: " + systemJSON.state.external_temp + " °C.",
                    controlLastRan: "Vezérlés lefutott: " + hourStamp(lastControlRan,true)+".",
                    latestRequest: { target: requestTarget, origin: requestOrigin, timeSince: timeSinceLastRequest, granularity: timeSinceLastRequestGranularity, hourStamp: lastRequestHourStamp },
                    scheduleLastUpdated: "Beállítások frissítve: " + hourStamp(lastScheduleUpdate)+".",
                    averageControlDiff: averageControlDiff
                }
            );

            cycles.forEach(cycleNum => {
                let roomsOnCycle = systemJSON.setup.cycles[cycleNum].rooms;
                let roomsThatWantHeating = [];
                let totalControlDiffOnCycle = 0;
                roomsOnCycle.forEach(roomNum => {
                    systemJSON.control.rooms[roomNum].vote == 1 ? roomsThatWantHeating.push(systemJSON.setup.rooms[roomNum].name) : "";
                    totalControlDiffOnCycle = controlDiffs[roomNum] == "missing" ? totalControlDiffOnCycle : totalControlDiffOnCycle + controlDiffs[roomNum];
                });

                updateCycleInfobox(
                    cycleNum,
                    {
                        state: systemJSON.state.pump_states[cycleNum],
                        set: systemJSON.control.cycles[cycleNum],
                        rooms: roomsOnCycle,
                        wantHeating: roomsThatWantHeating,
                        totalControlDiff: totalControlDiffOnCycle
                    }
                );

                // Update misc data
                let newGasUsageRate = roundTo(0.1 / (systemJSON.state.gas.dial_turn_secs / 3600), 0.1);
                currentGasUsageRate = isValidNumber(newGasUsageRate) ? newGasUsageRate : currentGasUsageRate
            });
        })
        .catch(error => {
            console.error('Error fetching data from Firebase:', error);
        });
}

function extractRoomScheduleFromCondensedSchedule(roomNum) {
    if (condensedSchedule === undefined) { return undefined }
    else {
        let roomSchedule = [];
        condensedSchedule[roomNum][getUnixDay()].forEach((setTemp, hour) => {
            roomSchedule.push(
                {
                    "h_of_day_frac": hour,
                    "set_temp": setTemp
                }
            );
            roomSchedule.push(
                {
                    "h_of_day_frac": hour + 0.999,
                    "set_temp": setTemp
                }
            );
            if (hour == 23) {
                roomSchedule.push(
                    {
                        "h_of_day_frac": 24,
                        "set_temp": setTemp
                    }
                );
            }
        });
        return roomSchedule
    }
}

function convertTimestamps(dataJSON, day) {
    const parseTime = d3.timeParse("%Y-%m-%d-%H-%M-%S");
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
            if (parsedDate.getDay() !== new Date(day).getDay()) {
                return null;
            }

            // If kept, compute fractional hour
            d.h_of_day_frac = parsedDate.getHours() + parsedDate.getMinutes() / 60;
            return d;
        })
        // Filter out the nulls (mismatched days or unparsable timestamps)
        .filter(Boolean);
}

function collectDataFromGitHub(day, dataTypes, drawFunction) {
    // We'll store our results here:
    const dataCollected = {};

    // Recursive function to handle fetching each type one by one
    function fetchNextType(index) {
        if (index >= dataTypes.length) {
            // Once all data is fetched and processed, call the draw function
            drawFunction(dataCollected);
            return;
        }

        const currentType = dataTypes[index];
        const url = "https://raw.githubusercontent.com/markusbenjamin/kazanfutes/refs/heads/main/data/formatted/"
            + day + "/" + currentType + ".json";

        fetchJSONEndpoint(url)
            .then(dataJSON => {
                // Convert timestamps if needed
                if (Array.isArray(dataJSON)) {
                    dataCollected[currentType] = convertTimestamps(dataJSON, day);

                }
                else {
                    dataCollected[currentType] = dataJSON;
                }
                // Move on to the next type
                fetchNextType(index + 1);
            })
        //.catch(error => {
        //    console.error(`Error fetching data from GitHub for ${currentType}:`, error);
        //});
    }

    // Start fetching from the first type
    fetchNextType(0);
}

function drawPlot(plotData, userOptions) {
    //plotData instanceof Promise ? console.log("promise") : "";
    //plotData === undefined ? console.log("undefined") : "";
    var defaultOptions = {
        dev: false,
        parentId: "background",
        centered: true,
        positioning: { x: 0.5, y: 0.5, w: 1, h: 1 }, // Relative positioning and size compared to parent
        margins: { top: 0.1, right: 0.1, bottom: 0.1, left: 0.1 }, // Affecting the plot elements within the content element

        background: { show: true, col: "white" },
        plotStyle: { joined: false, col: "gray", thickness: "0.25", startCap: true, endCap: true, smoothCurve: true },
        domain: { bottom: null, left: null },
        smoothing: { bottom: 0, left: 0 },
        axes: { top: false, right: false, left: true, bottom: true },
        tickVals: { top: false, right: false, left: false, bottom: false },

        axesLabel: { top: false, right: false, left: "", bottom: "" },
        plotLabel: "",
        now: { show: false, pos: null },
        segment: { do: false, gap: null },
        curveEndText: { show: false, fontSize: null, text: null, col: null, xOffset: 13, yOffset: 3 },
        markers: false //Usage: markers: {when: "before", list:[{pos: 12, h: 2}], col: "#ff0000", thickness: 2, dashed: false, dashing: "4,4", endCap: true, thickness: 5}
    }
    ops = deepObjectMerger(defaultOptions, userOptions);

    // Find parent element
    const parentElement = d3.select(`#${ops.parentId}`);
    if (parentElement.empty()) {
        throw new Error(`No element found with id: ${ops.parentId}`);
    }

    // Create wrapper (needed because only gs can show nested content)
    let wrapperDims = getBBoxDrawingDimensions(ops.parentId); //Same dimensions as parent
    let wrapperElement = d3.select(parentElement.node().parentNode)
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
        containerElement.append("rect")
            .attr("width", containerDims.w)
            .attr("height", containerDims.h)
            .attr("fill", ops.background.col)
    }

    // Create the main plotting area using margins
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

    let bottomScale, bottomAxis;

    bottomScale = d3.scaleLinear()
        .domain(ops.domain.bottom ? ops.domain.bottom : d3.extent(plotData, d => d[ops.dataKeys.bottom]))
        .range([0, plotDims.w]);

    if (ops.axes.bottom) {
        // Add bottom axis
        bottomAxis = plotElement.append("g")
            .attr("transform", `translate(0, ${plotDims.h})`)
            .call(d3.axisBottom(bottomScale)
                .tickSize(2) // Set tick length
                .tickValues(ops.tickVals.bottom ? ops.tickVals.bottom : bottomScale.ticks(12)) // Set the number of ticks (12 for 0, 2, 4, ..., 24)
                .tickFormat(ops.tickVals.bottom ?
                    (ops.tickVals.bottom.some(d => !Number.isInteger(d)) ? d => d : d => d.toFixed(0))
                    : d => d.toFixed(0))
            );

        // Style the X-axis
        bottomAxis.select(".domain") // Select the axis line
            .style("stroke-width", "0.5px"); // Set the axis line thickness

        bottomAxis.selectAll(".tick line") // Select all tick lines
            .attr("stroke-width", "0.5px") // Set tick line thickness
            .attr("y2", "2"); // Adjust tick length (positive increases length)

        bottomAxis.selectAll("text") // Select tick labels
            .attr("dy", "3")
            .style("font-family", "Consolas")
            .style("font-size", "5px"); // Set font size for tick labels

        // bottom axis label
        plotElement.append("text")
            .attr("x", plotDims.w / 2)
            .attr("y", plotDims.h + plotDims.h * ops.margins.bottom * 1.8)
            .style("text-anchor", "middle")
            .style("font-size", "6px")
            .style("font-family", "Consolas")
            .text(ops.axesLabel.bottom);
    }

    let leftScale, leftAxis;

    leftScale = d3.scaleLinear()
        .domain(ops.domain.left ? ops.domain.left : d3.extent(plotData, d => d[ops.dataKeys.left]))
        .nice()
        .range([plotDims.h, 0]);

    if (ops.axes.left) {
        leftAxis = plotElement.append("g")
            .call(d3.axisLeft(leftScale)
                .tickSize(2)
                .tickValues(ops.tickVals.left ? ops.tickVals.left : leftScale.ticks(10))
                .tickFormat(ops.tickVals.left ?
                    (ops.tickVals.left.some(d => !Number.isInteger(d)) ? d => d : d => d.toFixed(0))
                    : d => d.toFixed(0))
            );

        // Style the Y-axis
        leftAxis.select(".domain") // Customize the domain path to match the tick range
            .style("stroke-width", "0.5px");

        leftAxis.selectAll(".tick line")
            .attr("stroke-width", "0.5px") // Set tick line thickness
            .attr("x2", "-2"); // Adjust tick length (negative for left-side ticks)

        leftAxis.selectAll("text")
            .attr("dx", "0")
            .style("font-size", "5px")
            .style("font-family", "Consolas")
            .style("text-anchor", "end"); // Set font size for tick labels

        // left-axis label
        plotElement.append("text")
            .attr("transform", `rotate(-90)`)
            .attr("x", -plotDims.h / 2)
            .attr("y", -plotDims.w * ops.margins.left * 0.9)
            .style("text-anchor", "middle")
            .style("font-size", "6px")
            .style("font-family", "Consolas")
            .text(ops.axesLabel.left);
    }

    if (ops.plotLabel != "") {
        // Plot label
        plotElement.append("text")
            .attr("x", plotDims.w / 2)
            .attr("y", -plotDims.h * ops.margins.top * 0.5)
            .style("text-anchor", "middle")
            .style("font-size", "7px")
            .style("font-family", "Consolas")
            .text(ops.plotLabel);
    }

    if (plotData === undefined) {
        plotElement.append("text")
            .attr("x", plotDims.w / 2)
            .attr("y", plotDims.h / 2)
            .style("text-anchor", "middle")
            .style("font-size", "7px")
            .style("font-family", "Consolas")
            .text("Adat betöltése.");
    }
    else {
        if (ops.smoothing.bottom > 0) {
            plotData = calculateMovingAverage(plotData, ops.dataKeys.bottom, ops.smoothing.bottom); //move to segmentation... DEV
        }
        if (ops.smoothing.left > 0) {
            plotData = calculateMovingAverage(plotData, ops.dataKeys.left, ops.smoothing.left);
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

        if (ops.plotStyle.joined) {
            const line = d3.line()
                .x(d => bottomScale(d[ops.dataKeys.bottom]))
                .y(d => leftScale(d[ops.dataKeys.left]))
                .curve(ops.plotStyle.smoothCurve ? d3.curveBasis : d3.curveStep);

            const segments = ops.segment.do ? splitDataIntoSegments(plotData, ops.dataKeys.bottom, ops.segment.gap) : [plotData];

            // Draw a path for each segment
            segments.forEach((segment, index) => {
                if (!segment || segment.length === 0) return;

                // Draw the segment as a line
                plotElement.append("path")
                    .datum(segment)
                    .attr("fill", "none")
                    .attr("stroke", ops.plotStyle.col)
                    .attr("stroke-width", ops.plotStyle.thickness)
                    .attr("d", line);

                // Optionally cap the end of each segment (rather than just the very last one)
                if (ops.plotStyle.startCap) {
                    const lastPoint = segment[0];
                    plotElement.append("circle")
                        .attr("cx", bottomScale(lastPoint[ops.dataKeys.bottom]))
                        .attr("cy", leftScale(lastPoint[ops.dataKeys.left]))
                        .attr("r", ops.plotStyle.thickness * 1.05)
                        .attr("fill", ops.plotStyle.col);
                }

                if (ops.plotStyle.endCap) {
                    const lastPoint = segment[segment.length - 1];
                    plotElement.append("circle")
                        .attr("cx", bottomScale(lastPoint[ops.dataKeys.bottom]))
                        .attr("cy", leftScale(lastPoint[ops.dataKeys.left]))
                        .attr("r", ops.plotStyle.thickness * 1.05)
                        .attr("fill", ops.plotStyle.col);
                }

                if (ops.curveEndText.show && index === segments.length - 1) { // Only draw end text at the last segment
                    const lastPoint = segment[segment.length - 1];
                    plotElement.append("text")
                        .attr("x", bottomScale(lastPoint[ops.dataKeys.bottom]) + ops.curveEndText.xOffset)
                        .attr("y", leftScale(lastPoint[ops.dataKeys.left]) + ops.curveEndText.yOffset)
                        .style("text-anchor", "middle")
                        .style("font-size", ops.curveEndText.fontSize + "px")
                        .style("font-family", "Consolas")
                        .style("fill", ops.curveEndText.col ? ops.curveEndText.col : "black")
                        .text(ops.curveEndText.text);
                }
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

        if (ops.markers && ops.markers.when == "after") {
            drawMarkers()
        }

        if (ops.now.show) {
            plotElement.append("line")
                .attr("x1", bottomScale(ops.now.pos))
                .attr("y1", 0)
                .attr("x2", bottomScale(ops.now.pos))
                .attr("y2", plotDims.h)
                .attr("stroke", "gray")
                .attr("stroke-width", 0.5)
                .attr("stroke-dasharray", "1 2");
        }
    }
}

function clearMainGraphs() {
    d3.selectAll(".main-graph-instance").remove();
}

const roomDataAndState = {
    1: { roomID: "Oktopusz", name: "Oktopusz szita", temp: null, set: null, lastUpdated: null },
    2: { roomID: "Gólyafészek", name: "Gólyafészek", temp: null, set: null, lastUpdated: null },
    3: { roomID: "PK", name: "PK", temp: null, set: null, lastUpdated: null },
    4: { roomID: "SZGK", name: "SZGK", temp: null, set: null, lastUpdated: null },
    5: { roomID: "Mérce", name: "Mérce", temp: null, set: null, lastUpdated: null },
    6: { roomID: "Lahmacun", name: "Lahmacun", temp: null, set: null, lastUpdated: null },
    7: { roomID: "Gólyairoda", name: "Gólyairoda", temp: null, set: null, lastUpdated: null },
    8: { roomID: "kisterem", name: "kisterem", temp: null, set: null, lastUpdated: null },
    9: { roomID: "vendégtér", name: "vendégtér", temp: null, set: null, lastUpdated: null },
    10: { roomID: "Trafóház", name: "Trafóház", temp: null, set: null, lastUpdated: null },
    11: { roomID: "OktopuszKeramia", name: "Oktopusz kerámia", temp: null, set: null, lastUpdated: null }
};

function updateRoomColor(roomId, temp, lastUpdated) {
    if (timePassedSince(dateFromTimestamp(lastUpdated)) > 2 * 60) {
        d3.select("#" + roomId).style("fill", "rgb(31, 31, 32,0.8)");
    }
    else {
        // Create a color scale
        const colorScale = d3.scaleSequential(d3.interpolateRgb("blue", "red"))
            .domain([15, 25]); // Set the input domain (10°C to 30°C)
        d3.select("#" + roomId).style("fill", colorScale(temp));
    }
}

function updateCycleColor(cycle, state) {
    d3.select("#cycle" + cycle).style("stroke", state == 1 ? "rgba(255,0,0,0.75)" : "rgba(0,0,200,0.75)");
    d3.select("#cycle" + cycle).style("stroke-opacity", "1");

    d3.select("#cycle" + cycle + "_radiators").selectAll("*").style("fill", state == 1 ? "rgba(255,0,0,1)" : "rgba(0,0,200,1)");
    d3.select("#cycle" + cycle + "_radiators").selectAll("*").style("fill-opacity", "1");
}

let boilerState = null;

function updateBoilerColor(state) {
    d3.select("#boiler").style("stroke-opacity", "0");

    d3.select("#flame_nest").style("fill", "rgba(0.2,0.2,0.2,1)");
    d3.select("#flame_nest").style("fill-opacity", "1");

    d3.select("#boiler_body").style("stroke", state == 1 ? "rgba(255,0,0,1)" : "rgba(0,0,255,1)");
    d3.select("#boiler_body").style("stroke-opacity", "1");
    boilerState = state;
}


let currentGasUsageRate, currentGasTotal;

function writeGasUsageToDial(gasData = null) {
    if (gasData == null) {
        collectDataFromGitHub(dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), ["gas_usage"], writeGasUsageToDial);
    }
    else {
        gasData = gasData["gas_usage"];
        d3.select("#gas_piping").style("stroke", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_piping").style("stroke-opacity", "1");
        d3.select("#gas_meter").style("fill", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_meter").style("fill-opacity", "1");
        d3.select("#gas_meter2").style("fill", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_meter2").style("fill-opacity", "1");

        currentGasTotal = roundTo(gasData[gasData.length - 1].burnt_volume, 0.1);
        if (currentGasTotal == NaN) { currentGasTotal = 0 };

        if (isValidNumber(currentGasUsageRate) == false) {
            currentGasUsageRate = roundTo(gasData[gasData.length - 1].burn_rate_in_m3_per_h, 0.1);
        }

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
        d3.selectAll("#gas_dial_text").remove();
        d3.select("#drawing")
            .append("text")
            .attr("id", "gas_dial_text")
            .attr("x", dialBoxBB.x + dialBoxBB.width * textXOffsetFactor)
            .attr("y", dialBoxBB.y + dialBoxBB.height * 0.7)
            .text(gasTotal)
            .style("font-family", "Consolas")
            .style("font-size", "6.5px")
            .style("fill", "black");
        d3.select("#drawing")
            .append("text")
            .attr("id", "gas_dial_text")
            .attr("x", dialBoxBB.x + dialBoxBB.width * 0.732)
            .attr("y", dialBoxBB.y + dialBoxBB.height * 0.69)
            .text(" m³")
            .style("font-family", "Consolas")
            .style("font-size", "5px")
            .style("fill", "black");
        d3.select("#drawing")
            .append("rect")
            .attr("id", "gas_dial_hover_area")
            .attr("x", dialBoxBB.x)
            .attr("y", dialBoxBB.y)
            .attr("width", dialBoxBB.w)
            .attr("height", dialBoxBB.h)
            .style("fill", "transparent")
            .style("pointer-events", "all");
    }
}

function initializeCycleMarkers() {
    for (let cycle = 1; cycle < 5; cycle++) {
        const markerBB = getBBoxDrawingDimensions("cycle" + cycle + "_marker");
        d3.select("#cycle" + cycle + "_marker")
            .style("stroke", "black")
            .style("stroke-opacity", "1")
            .style("fill", "white")
            .style("fill-opacity", "1");

        d3.select("#drawing")
            .append("text")
            .attr("x", markerBB.x + markerBB.width * 0.25)
            .attr("y", markerBB.y + markerBB.height * 0.75)
            .text(cycle)
            .style("font-family", "Consolas")
            .style("font-size", "2.5px")
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
    d3.select("#cycles_infobox")
        .style("fill", "rgba(250,250,250,1)")
        .style("fill-opacity", "1")
        .style("stroke", "rgba(250,250,250,1)")
        .style("stroke-opacity", "1")
        .style("stroke-width", "3");
}

let roomAbbreviations = {
    "Oktopusz": "Okt.",
    "Gólyafészek": "Gólyaf.",
    "PK": "PK",
    "SZGK": "SZGK",
    "Mérce": "Mérce",
    "Gólyairoda": "Gólyai.",
    "Lahmacun": "Lahma.",
    "vendégtér": "vendégt.",
    "kisterem": "kist.",
    "Trafóház": "Traf."
}

function updateGeneralInfobox(info) {
    boxDims = getBBoxDrawingDimensions("general_infobox");

    d3.selectAll(".general-infobox-content").remove();

    function addLineToBox(message, xFactor, yFactor, fontSize) {
        return d3.select("#drawing")
            .append("text")
            .attr("class", "general-infobox-content")
            .attr("x", boxDims.x + boxDims.width * xFactor)
            .attr("y", boxDims.y + boxDims.height * 0.025 + boxDims.height * yFactor)
            .text(message)
            .style("font-family", "Consolas")
            .style("font-size", fontSize + "px");
    }

    // Draw title
    addLineToBox("Rendszerállapot", 0.02, 0.045, 9)
        .style("text-decoration", "underline");

    // Draw content

    let lineFontSize = 6.5;
    let lineHeight = 0.065;
    let lineShift = 0;

    addLineToBox(info.externalTemp, 0.02, lineHeight * 2, lineFontSize);

    addLineToBox(info.controlLastRan, 0.02, lineHeight * 3.5, lineFontSize);

    let latestRequestString = "Utolsó kérés: " + info.latestRequest.hourStamp + ", " + info.latestRequest.origin + ", " + info.latestRequest.target + "."
    if (info.latestRequest.granularity == "órája" && info.latestRequest.timeSince > getFractionalHourOfDay()) {
        latestRequestString = "Ma még nem érkezett kérés."
    }
    if (latestRequestString.length > 35) {
        latestRequestString = "Utolsó kérés: " + info.latestRequest.hourStamp + ", " + info.latestRequest.origin + ", " + roomAbbreviations[info.latestRequest.target] + ".";
    }
    addLineToBox(latestRequestString, 0.02, lineHeight * 4.5, lineFontSize);


    addLineToBox(info.scheduleLastUpdated, 0.02, lineHeight * (5.5 + lineShift), lineFontSize);
    if (info.averageControlDiff != 0.0) {
        let reportedControlDiff = roundTo(info.averageControlDiff, 0.1);
        let averageControlDiffPre = reportedControlDiff == 0.0 ? "" : (reportedControlDiff < 0 ? "" : "+");
        addLineToBox("Átlagos eltérés: " + averageControlDiffPre + reportedControlDiff + " °C.", 0.02, lineHeight * (6.5 + lineShift), lineFontSize);
    }

    addLineToBox(info.cyclesOn, 0.02, lineHeight * (8 + lineShift), lineFontSize);
    addLineToBox("Gázfogyasztási ráta: " + (isValidNumber(currentGasUsageRate) ? currentGasUsageRate : "") + (isValidNumber(currentGasUsageRate) ? " m³/h." : ""), 0.02, lineHeight * (9 + lineShift), lineFontSize);
    if (isValidNumber(currentGasTotal)) {
        let gasTotalString = currentGasTotal;
        if (Number.isInteger(gasTotalString)) {
            gasTotalString += ".0";
        }
        addLineToBox("Összes elégett gáz: " + gasTotalString + " m³.", 0.02, lineHeight * (10 + lineShift), lineFontSize);
        addLineToBox("Összköltség kb. " + roundTo(currentGasTotal * 350 / 1000, 0.1) + " eFt.", 0.02, lineHeight * (11 + lineShift), lineFontSize);
    }
}

function updateCycleInfobox(cycle, info) {
    boxDims = getBBoxDrawingDimensions("cycle" + cycle + "_infobox");

    d3.selectAll(".cycle" + cycle + "-infobox-content").remove();

    function addLineToBox(message, xFactor, yFactor, fontSize) {
        return d3.select("#drawing")
            .append("text")
            .attr("class", "cycle" + cycle + "-infobox-content")
            .attr("x", boxDims.x + boxDims.width * xFactor)
            .attr("y", boxDims.y + boxDims.width * 0.025 + boxDims.width * yFactor)
            .text(message)
            .style("font-family", "Consolas")
            .style("font-size", fontSize + "px");
    }

    addLineToBox(cycle + ["-es", "-es", "-mas", "-es"][cycle - 1] + " kör: " + ["ki", "be"][info.state], 0.08, 0.13, 7)
        .style("text-decoration", "underline");

    addLineToBox(cycle < 4 ? "Átlagos eltérés:" : "Eltérés:", 0.08, 0.13 * 2.1, 5.5)
    if (isValidNumber(info.totalControlDiff)) {
        let reportedControlDiff = roundTo(info.totalControlDiff / info.rooms.length, 0.1)
        let reportedeControlDiffPre = reportedControlDiff == 0.0 ? "" : (reportedControlDiff < 0 ? "" : "+");
        addLineToBox(reportedeControlDiffPre + reportedControlDiff + " °C", 0.2, 0.13 * 3.1, 5.5)
    }
    else {
        addLineToBox("?", 0.25, 0.13 * 3, 5.5)
    }

    if (cycle < 4) {
        if (info.wantHeating) {
            if (info.wantHeating.length > 0) {
                addLineToBox("Fűtést kér:", 0.08, 0.13 * 4.5, 5.5);
                let lineNum = 1;
                info.wantHeating.forEach(roomName => {
                    addLineToBox("- " + roomName, 0.12, 0.13 * (4.5 + lineNum), 5.5);
                    lineNum++;
                });
            } else {
                addLineToBox("Nem kér fűtést.", 0.08, 0.13 * 4.5, 5.5);
            }
        }
    }
    else {
        addLineToBox(["Nem kér fűtést.", "Fűtést kér."][info.set], 0.08, 0.13 * 4.5, 5.5);
    }
}

let dataWaitTime = 30;
let dayDataNotAvailable = false;

const mainGraphDefaultSetting = {
    title: "heating_state",
    types: ["heating_state"],
    day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime)
};

let mainGraphSetting = mainGraphDefaultSetting;

let mainGraphContentLocked = false;

const elementToGrapSettingMapping = {
    "gas_dial_hover_area": { title: "gas_usage", types: ["gas_usage"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime) },
    "Oktopusz": { title: "room_plot", types: ["room_1_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 1 },
    "Gólyafészek": { title: "room_plot", types: ["room_2_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 2 },
    "PK": { title: "room_plot", types: ["room_3_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 3 },
    "SZGK": { title: "room_plot", types: ["room_4_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 4 },
    "Mérce": { title: "room_plot", types: ["room_5_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 5 },
    "Lahmacun": { title: "room_plot", types: ["room_6_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 6 },
    "Gólyairoda": { title: "room_plot", types: ["room_7_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 7 },
    "kisterem": { title: "room_plot", types: ["room_8_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 8 },
    "vendégtér": { title: "room_plot", types: ["room_9_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 9 },
    "Trafóház": { title: "room_plot", types: ["room_10_measurements", "override_requests"], day: dayStamp(new Date(), dayDataNotAvailable, dataWaitTime), roomNumToPlot: 10 },
    "background": mainGraphDefaultSetting
};

function joinMainGrapDataSourceToElements() {
    d3.selectAll(Object.keys(elementToGrapSettingMapping).map(id => `#${id}`).join(","))
        .on("mouseover.maingraph", function (event) {
            if (mainGraphContentLocked == false) {
                mainGraphSetting = elementToGrapSettingMapping[this.id]; // Set based on mapping
                resetMainGraph();
            }
        })
        .on("mouseout.maingraph", function () {
            if (mainGraphContentLocked == false) {
                mainGraphSetting = mainGraphDefaultSetting; // Reset on mouseout
                resetMainGraph();
            }
        })
        .on("click.maingraph", function (event) {
            event.stopPropagation();
            mainGraphContentLocked = !mainGraphContentLocked;
        });
    d3.select("body")
        .on("click", function (event) {
            if (mainGraphContentLocked) {
                mainGraphContentLocked = false;
                mainGraphSetting = mainGraphDefaultSetting;
                resetMainGraph();
            }
        });
}

function resetMainGraph() {
    runOnceThenSetInterval(drawMainGraph, 60 * 1000);
}

function drawMainGraph(graphData = null) {
    if (graphData == null) {
        collectDataFromGitHub(mainGraphSetting.day, mainGraphSetting.types, drawMainGraph);
    }
    else {
        clearMainGraphs();
        if (mainGraphSetting.types.length == Object.keys(graphData).length) {
            switch (mainGraphSetting.title) {
                case "gas_usage":
                    drawPlot(
                        graphData["gas_usage"],
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 0 },
                            domain: { bottom: [0, 24], left: [0, 10] },
                            dataKeys: { bottom: "h_of_day_frac", left: "burn_rate_in_m3_per_h" },
                            axesLabel: { bottom: "óra", left: "ráta (m³/h)" },
                            plotLabel: "mai gázfogyasztás",
                        }
                    );
                    drawPlot(
                        graphData["gas_usage"],
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 25 },
                            domain: { bottom: [0, 24], left: [0, 10] },
                            dataKeys: { bottom: "h_of_day_frac", left: "burn_rate_in_m3_per_h" },
                            background: { show: false },
                            plotStyle: { joined: true, col: "rgb(0, 0, 0)", thickness: "2", startCap: false }
                        }
                    );
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
                            cycleOnData,
                            {
                                parentId: "graph",
                                axes: { left: cycle == 1, bottom: cycle == 1 },
                                domain: { bottom: [0, 24], left: [0.5, 4.5] },
                                dataKeys: { bottom: "h_of_day_frac", left: "cycle_state" },
                                background: { show: cycle == 1, col: "white" },
                                plotStyle: { joined: true, col: "rgba(255, 64, 0, 0.75)", thickness: "8", startCap: false, endCap: false },
                                tickVals: { left: [1, 2, 3, 4] },
                                axesLabel: { bottom: cycle == 1 ? "óra" : false, left: cycle == 1 ? "kör" : false },
                                plotLabel: cycle == 1 ? "körök kapcsolási mintázata" : false,
                                now: { show: cycle == 1, pos: maxHFrac },
                                segment: { do: true, gap: 30 / (24 * 60) }
                            }
                        );
                        drawPlot(
                            cycleOffData,
                            {
                                parentId: "graph",
                                domain: { bottom: [0, 24], left: [0.5, 4.5] },
                                dataKeys: { bottom: "h_of_day_frac", left: "cycle_state" },
                                background: { show: false, col: "white" },
                                tickVals: { left: [1, 2, 3, 4] },
                                plotStyle: { joined: true, col: "rgba(8, 86, 222, 0.23)", thickness: "6", startCap: false, endCap: false },
                                segment: { do: true, gap: 100 / (24 * 60) }
                            }
                        );
                    }
                    break;
                case "room_plot":
                    let roomOverrides = graphData["override_requests"][mainGraphSetting.roomNumToPlot];
                    roomOverrides = requestLists[mainGraphSetting.roomNumToPlot];
                    console.log(roomOverrides);
                    requestMarkers = [];
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
                    drawPlot(
                        extractRoomScheduleFromCondensedSchedule(mainGraphSetting.roomNumToPlot),
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 0 },
                            domain: { bottom: [0, 24], left: [10, 24] },
                            dataKeys: { bottom: "h_of_day_frac", left: "set_temp" },
                            axesLabel: { bottom: "óra", left: "°C" },
                            plotStyle: { joined: true, col: "rgba(28, 185, 0,0.5)", thickness: "3", startCap: false, endCap: false, smoothCurve: false },
                            plotLabel: roomDataAndState[mainGraphSetting.roomNumToPlot].name + " kért és mért hőmérséklet",
                            markers: { when: "after", list: requestMarkers, col: "rgba(245,245,0,1)", thickness: 1.5, dashed: true, dashing: "6,3", endCap: true, endCapSize: 2 }
                        }
                    );
                    drawPlot(
                        graphData["room_" + mainGraphSetting.roomNumToPlot + "_measurements"],
                        {
                            parentId: "graph",
                            background: { show: false },
                            smoothing: { bottom: 0, left: 10 },
                            domain: { bottom: [0, 24], left: [10, 24] },
                            dataKeys: { bottom: "h_of_day_frac", left: "temp" },
                            plotStyle: { joined: true, col: "rgba(255,0,0,1)", thickness: "2", startCap: false, endCap: true },
                            curveEndText: { show: false, fontSize: 10, text: "bla", col: "red" } //DEV
                        }
                    );
                    break;
            }
            d3.select("#graph").style("fill", "rgba(0,0,0,0)");
            d3.select("#graph").style("fill-opacity", "0");
        }
    }
}

function rescueMainGraph() {
    if (d3.select(".main-graph-instance").size() == 0) {
        resetMainGraph()
    }
}

let isMobile, smallerDimension, initialZoom, initialPos;

function setViewParameters(centeredId) {
    const width = window.innerWidth;
    const height = window.innerHeight;

    smallerDimension = Math.min(width, height);
    isMobile = /Mobi|Android/i.test(navigator.userAgent);
    params = new URLSearchParams(window.location.search);
    fromRequest = params.get("ref_source") == "qr" || params.get("ref_source") == "form";

    let centeringOffsetFactor = { x: 1, y: 1 }
    if (isMobile) {
        initialZoom = smallerDimension * 0.006;
        centeredId = "general_infobox";
        centeringOffsetFactor.y = 1.2;
    }
    /*else if (fromRequest) {
        initialZoom = smallerDimension * 0.003;
        centeredId = "general_infobox";
        centeringOffsetFactor.y = 1.1;
    }*/
    else {
        initialZoom = smallerDimension * 0.003;
    }
    let centeredDims = getBBoxRelativeDimensions(centeredId);
    initialPos = { x: centeredDims.cx * centeringOffsetFactor.x, y: centeredDims.cy * centeringOffsetFactor.y };
}

d3.xml("canvas.svg").then(fileData => {
    insertCanvasFromFile(fileData);
    setViewParameters("background");
    centerAndZoomRelativePointOfCanvas(initialPos.x, initialPos.y, initialZoom);
    setupTooltip();
    initializeCycleMarkers();
    initializeInfoboxes();

    runOnceThenSetInterval(joinMainGrapDataSourceToElements, 10);
    runOnceThenSetInterval(writeGasUsageToDial, 60 * 1000);
    runOnceThenSetInterval(getDataFromFirebase, 5 * 1000);
    runOnceThenSetInterval(drawMainGraph, 60 * 1000);

    runOnceThenSetInterval(rescueMainGraph, 100);
});