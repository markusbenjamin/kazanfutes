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
                    tooltip.html(roomTooltipData.name + "<br>" + roomTooltipData.temp + "°C")
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

function getDataFromFirebase() {
    const url = "https://kazanfutes-71b78-default-rtdb.europe-west1.firebasedatabase.app/system.json";
    fetchJSONEndpoint(url)
        .then(systemJSON => {
            const roomNums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
            roomNums.forEach(roomNum => {
                const roomTemp = roundTo(systemJSON.state['measured_temps'][roomNum], 0.1);
                updateRoomColor(systemJSON.setup.rooms[roomNum].name, roomTemp);
                roomDataAndState[roomNum].temp = (roomTemp.toFixed(2).slice(0, 4));
            });
            const roomTemp = roundTo((systemJSON.state['oktopusz_keramia'][1] + systemJSON.state['oktopusz_keramia'][2]) / 2, 0.1);
            //const roomTemp = roundTo(systemJSON.state['oktopusz_keramia'][1],0.1);
            updateRoomColor("OktopuszKeramia", roomTemp);
            roomDataAndState[11].temp = (roomTemp.toFixed(2).slice(0, 4));

            const cycles = [1, 2, 3, 4];
            let states = 0;
            cycles.forEach(cycleNum => {
                const cycleState = systemJSON.control.cycles[cycleNum];
                states += cycleState;
                updateCycleColor(cycleNum, cycleState);
            }
            );
            updateBoilerColor(states > 0 ? 1 : 0);
        })
        .catch(error => {
            console.error('Error fetching data from Firebase:', error);
        });
}

function collectDataFromGitHub(day, dataTypes, drawFunction) {
    // We'll store our results here:
    const dataCollected = {};

    // A helper to parse timestamps if present
    const parseTime = d3.timeParse("%Y-%m-%d-%H-%M-%S");
    function convertTimestamps(dataJSON) {
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
                dataCollected[currentType] = convertTimestamps(dataJSON);
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
    var defaultOptions = {
        dev: false,
        parentId: "background",
        centered: true,
        positioning: { x: 0.5, y: 0.5, w: 1, h: 1 }, // Relative positioning and size compared to parent
        margins: { top: 0.1, right: 0.1, bottom: 0.1, left: 0.1 }, // Affecting the plot elements within the content element

        background: { present: true, col: "white" },
        plotStyle: { joined: false, col: "gray", thickness: "0.25", endCap: true },
        plotRange: { bottom: null, left: null },
        smoothing: { bottom: 0, left: 0 },
        axes: { top: false, right: false, left: true, bottom: true },
        tickVals: { top: false, right: false, left: false, bottom: false },

        axesLabel: { top: false, right: false, left: "", bottom: "" },
        plotLabel: "",
        present: { show: false },
        segment: { do: false, gap: null }
    }
    //ops = { ...defaultOptions, ...userOptions }; // Fold user ops with default ops
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

    if (ops.background.present) {
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
        .domain(ops.plotRange.bottom ? ops.plotRange.bottom : d3.extent(plotData, d => d[ops.dataKeys.bottom]))
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
        .domain(ops.plotRange.left ? ops.plotRange.left : d3.extent(plotData, d => d[ops.dataKeys.left]))
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
        // Plot title
        plotElement.append("text")
            .attr("x", plotDims.w / 2)
            .attr("y", -plotDims.h * ops.margins.top * 0.75)
            .style("text-anchor", "middle")
            .style("font-size", "7px")
            .style("font-family", "Consolas")
            .text(ops.plotLabel);
    }

    if (ops.smoothing.bottom > 0) {
        plotData = calculateMovingAverage(plotData, ops.dataKeys.bottom, ops.smoothing.bottom); //move to segmentation... DEV
    }
    if (ops.smoothing.left > 0) {
        plotData = calculateMovingAverage(plotData, ops.dataKeys.left, ops.smoothing.left);
    }

    if (ops.plotStyle.joined) {
        const line = d3.line()
            .x(d => bottomScale(d[ops.dataKeys.bottom]))
            .y(d => leftScale(d[ops.dataKeys.left]))
            .curve(d3.curveBasis);

        const segments = ops.segment.do ? splitDataIntoSegments(plotData, ops.dataKeys.bottom, ops.segment.gap) : [plotData];

        // Draw a path for each segment
        segments.forEach(segment => {
            if (!segment || segment.length === 0) return;

            // Draw the segment as a line
            plotElement.append("path")
                .datum(segment)
                .attr("fill", "none")
                .attr("stroke", ops.plotStyle.col)
                .attr("stroke-width", ops.plotStyle.thickness)
                .attr("d", line);

            // Optionally cap the end of each segment (rather than just the very last one)
            if (ops.plotStyle.endCap) {
                const lastPoint = segment[segment.length - 1];
                plotElement.append("circle")
                    .attr("cx", bottomScale(lastPoint[ops.dataKeys.bottom]))
                    .attr("cy", leftScale(lastPoint[ops.dataKeys.left]))
                    .attr("r", ops.plotStyle.thickness * 1.05)
                    .attr("fill", ops.plotStyle.col);
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

    if (ops.present.show) {
        plotElement.append("line")
            .attr("x1", bottomScale(ops.present.pos))
            .attr("y1", 0)
            .attr("x2", bottomScale(ops.present.pos))
            .attr("y2", plotDims.h)
            .attr("stroke", "gray")
            .attr("stroke-width", 0.5)
            .attr("stroke-dasharray", "1 2");
    }
}

function clearMainGraphs() {
    d3.selectAll(".main-graph-instance").remove();
}

const roomDataAndState = {
    1: { roomID: "Oktopusz", name: "Oktopusz szita", temp: null },
    2: { roomID: "Gólyafészek", name: "Gólyafészek", temp: null },
    3: { roomID: "PK", name: "PK", temp: null },
    4: { roomID: "SZGK", name: "SZGK", temp: null },
    5: { roomID: "Mérce", name: "Mérce", temp: null },
    6: { roomID: "Lahmacun", name: "Lahmacun", temp: null },
    7: { roomID: "Gólyairoda", name: "Gólyairoda", temp: null },
    8: { roomID: "kisterem", name: "kisterem", temp: null },
    9: { roomID: "vendégtér", name: "vendégtér", temp: null },
    10: { roomID: "Trafóház", name: "Trafóház", temp: null },
    11: { roomID: "OktopuszKeramia", name: "Oktopusz kerámia", temp: null }
};

function updateRoomColor(roomId, temp) {
    // Create a color scale
    const colorScale = d3.scaleSequential(d3.interpolateRgb("blue", "red"))
        .domain([15, 25]); // Set the input domain (10°C to 30°C)
    d3.select("#" + roomId).style("fill", colorScale(temp));
}

function updateCycleColor(cycle, state) {
    d3.select("#cycle" + cycle).style("stroke", state == 1 ? "rgba(255,0,0,0.75)" : "rgba(0,0,255,0.75)");
    d3.select("#cycle" + cycle).style("stroke-opacity", "1");

    d3.select("#cycle" + cycle + "_radiators").selectAll("*").style("fill", state == 1 ? "rgba(255,0,0,1)" : "rgba(0,0,255,1)");
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

function writeGasUsageToDial(gasData = null) {
    if (gasData == null) {
        collectDataFromGitHub(dayStamp(), ["gas_usage"], writeGasUsageToDial);
    }
    else {
        gasData = gasData["gas_usage"];
        d3.select("#gas_piping").style("stroke", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_piping").style("stroke-opacity", "1");
        d3.select("#gas_meter").style("fill", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_meter").style("fill-opacity", "1");
        d3.select("#gas_meter2").style("fill", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_meter2").style("fill-opacity", "1");

        let gasTotal = Math.round(gasData[gasData.length - 1].burnt_volume);
        if (gasTotal == NaN) { gasTotal = 0 };
        const dialBoxBB = getBBoxDrawingDimensions("gas_dial");
        let textXOffsetFactor = 0.085;
        if (gasTotal < 10) {
            textXOffsetFactor = 0.24;
        }
        d3.selectAll("#gas_dial_text").remove();
        d3.select("#drawing")
            .append("text")
            .attr("id", "gas_dial_text")
            .attr("x", dialBoxBB.x + dialBoxBB.width * textXOffsetFactor)
            .attr("y", dialBoxBB.y + dialBoxBB.height * 0.7)
            .text(gasTotal + " m³")
            .style("font-family", "Consolas")
            .style("font-size", "7px")
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

const mainGraphDefaultSetting = {
    title: "heating_state",
    types: ["heating_state"],
    day: dayStamp()
};

let mainGraphSetting = mainGraphDefaultSetting;

let mainGraphContentLocked = false;

const elementToGrapSettingMapping = {
    "gas_dial_hover_area": { title: "gas_usage", types: ["gas_usage"], day: dayStamp() },
    "Oktopusz": { title: "room_plot", types: ["room_1_measurements", "room_1_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 1 },
    "Gólyafészek": { title: "room_plot", types: ["room_2_measurements", "room_2_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 2 },
    "PK": { title: "room_plot", types: ["room_3_measurements", "room_3_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 3 },
    "SZGK": { title: "room_plot", types: ["room_4_measurements", "room_4_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 4 },
    "Mérce": { title: "room_plot", types: ["room_5_measurements", "room_5_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 5 },
    "Lahmacun": { title: "room_plot", types: ["room_6_measurements", "room_6_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 6 },
    "Gólyairoda": { title: "room_plot", types: ["room_7_measurements", "room_7_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 7 },
    "kisterem": { title: "room_plot", types: ["room_8_measurements", "room_8_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 8 },
    "vendégtér": { title: "room_plot", types: ["room_9_measurements", "room_9_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 9 },
    "Trafóház": { title: "room_plot", types: ["room_10_measurements", "room_10_set_temps", "heating_state"], day: dayStamp(), roomNumToPlot: 10 },
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
        if (!Object.values(graphData).includes(undefined)) {
            switch (mainGraphSetting.title) {
                case "gas_usage":
                    drawPlot(
                        graphData["gas_usage"],
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 0 },
                            plotRange: { bottom: [0, 24], left: [0, 10] },
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
                            plotRange: { bottom: [0, 24], left: [0, 10] },
                            dataKeys: { bottom: "h_of_day_frac", left: "burn_rate_in_m3_per_h" },
                            background: { present: false },
                            plotStyle: { joined: true, col: "rgb(0, 0, 0)", thickness: "2" }
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
                                plotRange: { bottom: [0, 24], left: [0.5, 4.5] },
                                dataKeys: { bottom: "h_of_day_frac", left: "cycle_state" },
                                background: { present: cycle == 1, col: "white" },
                                plotStyle: { joined: true, col: "rgba(255, 64, 0, 0.75)", thickness: "8", endCap: false },
                                tickVals: { left: [1, 2, 3, 4] },
                                axesLabel: { bottom: cycle == 1 ? "óra" : false, left: cycle == 1 ? "kör" : false },
                                plotLabel: cycle == 1 ? "körök kapcsolási mintázata" : false,
                                present: { show: cycle == 1, pos: maxHFrac },
                                segment: { do: true, gap: 30 / (24 * 60) }
                            }
                        );
                        drawPlot(
                            cycleOffData,
                            {
                                parentId: "graph",
                                plotRange: { bottom: [0, 24], left: [0.5, 4.5] },
                                dataKeys: { bottom: "h_of_day_frac", left: "cycle_state" },
                                background: { present: false, col: "white" },
                                tickVals: { left: [1, 2, 3, 4] },
                                plotStyle: { joined: true, col: "rgba(8, 86, 222, 0.23)", thickness: "6", endCap: false },
                                segment: { do: true, gap: 30 / (24 * 60) }
                            }
                        );
                    }
                    break;
                case "room_plot":
                    drawPlot(
                        graphData["room_" + mainGraphSetting.roomNumToPlot + "_set_temps"],//.sort((a, b) => a["h_of_day_frac"] - b["h_of_day_frac"]),
                        {
                            parentId: "graph",
                            smoothing: { bottom: 0, left: 0 },
                            plotRange: { bottom: [0, 24], left: [10, 24] },
                            dataKeys: { bottom: "h_of_day_frac", left: "set_temp" },
                            axesLabel: { bottom: "óra", left: "°C" },
                            plotStyle: { joined: true, col: "rgba(28, 185, 0,0.5)", thickness: "3", endCap: false },
                            plotLabel: roomDataAndState[mainGraphSetting.roomNumToPlot].name + " kért és mért hőmérséklet"
                        }
                    );
                    drawPlot(
                        graphData["room_" + mainGraphSetting.roomNumToPlot + "_measurements"],
                        {
                            parentId: "graph",
                            background: { present: false },
                            smoothing: { bottom: 0, left: 10 },
                            plotRange: { bottom: [0, 24], left: [10, 24] },
                            dataKeys: { bottom: "h_of_day_frac", left: "temp" },
                            axesLabel: { bottom: "óra", left: "°C" },
                            plotStyle: { joined: true, col: "rgba(255,0,0,1)", thickness: "2" },
                            plotLabel: roomDataAndState[mainGraphSetting.roomNumToPlot].name + " kért és mért hőmérséklet"
                        }
                    );
                    break;
            }
            d3.select("#graph").style("fill", "rgba(0,0,0,0)");
            d3.select("#graph").style("fill-opacity", "0");
        }
    }
}

d3.xml("canvas.svg").then(fileData => {
    insertCanvasFromFile(fileData);
    centerAndZoomRelativePointOfCanvas(0.5, 0.5, 2.8);
    setupTooltip();
    initializeCycleMarkers();

    runOnceThenSetInterval(joinMainGrapDataSourceToElements, 10);
    runOnceThenSetInterval(getDataFromFirebase, 5 * 1000);
    runOnceThenSetInterval(writeGasUsageToDial, 60 * 1000);
    runOnceThenSetInterval(drawMainGraph, 60 * 1000);
});