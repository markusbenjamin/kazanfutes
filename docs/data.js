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

function updateRoomColor(roomId, temp) {
    // Create a color scale
    const colorScale = d3.scaleSequential(d3.interpolateRgb("blue", "red"))
        .domain([15, 25]); // Set the input domain (10°C to 30°C)
    d3.select(roomId).style("fill", colorScale(temp));
}

function updateCycleColor(cycle, state) {
    d3.select("#cycle" + cycle).style("stroke", state == 1 ? "rgba(255,0,0,0.75)" : "rgba(0,0,255,0.75)");
    d3.select("#cycle" + cycle).style("stroke-opacity", "1");

    d3.select("#cycle" + cycle + "_radiators").selectAll("*").style("fill", state == 1 ? "rgba(255,0,0,1)" : "rgba(0,0,255,1)");
    d3.select("#cycle" + cycle + "_radiators").selectAll("*").style("fill-opacity", "1");
}

let boilerState = null;

function updateBoilerColor(state) {
    //d3.select("#boiler").style("stroke", state == 1 ? "rgba(255,0,0,1)" : "rgba(0,0,255,1)");
    d3.select("#boiler").style("stroke-opacity", "0");
    //d3.select("#boiler").style("fill", state == 1 ? "rgba(255,0,0,0.5)" : "rgba(0,0,255,0.5)");

    d3.select("#flame_nest").style("fill", "rgba(0.2,0.2,0.2,1)");
    d3.select("#flame_nest").style("fill-opacity", "1");

    d3.select("#boiler_body").style("stroke", state == 1 ? "rgba(255,0,0,1)" : "rgba(0,0,255,1)");
    d3.select("#boiler_body").style("stroke-opacity", "1");
    boilerState = state;
}

const tooltipData = {
    1: { roomID: "#Oktopusz", name: "Oktopusz szita", temp: null },
    2: { roomID: "#Gólyafészek", name: "Gólyafészek", temp: null },
    3: { roomID: "#PK", name: "PK", temp: null },
    4: { roomID: "#SZGK", name: "SZGK", temp: null },
    5: { roomID: "#Mérce", name: "Mérce", temp: null },
    6: { roomID: "#Lahmacun", name: "Lahmacun", temp: null },
    7: { roomID: "#Gólyairoda", name: "Gólyairoda", temp: null },
    8: { roomID: "#kisterem", name: "kisterem", temp: null },
    9: { roomID: "#vendégtér", name: "vendégtér", temp: null },
    10: { roomID: "#Trafóház", name: "Trafóház", temp: null },
    11: { roomID: "#OktopuszKeramia", name: "Oktopusz kerámia", temp: null }
};

function setupTooltip() {
    // Setup tooltip
    const tooltip = d3.select("#tooltip");

    // Attach tooltip functionality to all path elements during initialization
    Object.keys(tooltipData).forEach(key => {
        const roomTooltipData = tooltipData[key]; // Access the value using the key
        d3.select(roomTooltipData.roomID)
            .on("mouseover", function (event) {
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
            .on("mousemove", function (event) {
                tooltip.style("left", (event.pageX + 5) + "px")
                    .style("top", (event.pageY - 28) + "px");
            })
            .on("mouseout", function () {
                tooltip.transition().duration(500).style("visibility", "hidden");
            })
    });
}

function pollFirebase() {
    const url = "https://kazanfutes-71b78-default-rtdb.europe-west1.firebasedatabase.app/system.json";
    setInterval(() => {
        fetchJSONEndpoint(url)
            .then(systemJSON => {
                const roomNums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
                roomNums.forEach(roomNum => {
                    const roomTemp = roundTo(systemJSON.state['measured_temps'][roomNum], 0.1);
                    updateRoomColor("#" + systemJSON.setup.rooms[roomNum].name, roomTemp);
                    tooltipData[roomNum].temp = (roomTemp.toFixed(2).slice(0, 4));
                });
                const roomTemp = roundTo((systemJSON.state['oktopusz_keramia'][1] + systemJSON.state['oktopusz_keramia'][2]) / 2, 0.1);
                //const roomTemp = roundTo(systemJSON.state['oktopusz_keramia'][1],0.1);
                updateRoomColor("#OktopuszKeramia", roomTemp);
                tooltipData[11].temp = (roomTemp.toFixed(2).slice(0, 4));

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
    }, 1 * 1000);
}

function writeGasUsageToDial(gasData = null) {
    if (gasData == null) {
        getDataFromGitHub(dayStamp(), "gas_usage", writeGasUsageToDial)
    }
    else {
        d3.select("#gas_piping").style("stroke", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_piping").style("stroke-opacity", "1");
        d3.select("#gas_meter").style("fill", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_meter").style("fill-opacity", "1");
        d3.select("#gas_meter2").style("fill", "rgba(0.2,0.2,0.2,1)");
        d3.select("#gas_meter2").style("fill-opacity", "1");

        let gasTotal = Math.round(gasData[gasData.length - 1].burnt_volume);
        if (gasTotal == NaN) { gasTotal = 0 };
        const dialBoxBB = getBBoxDrawingDimensions("gas_dial");
        let textXOffsetFactor = 0.15;
        if (gasTotal < 10) {
            textXOffsetFactor = 0.24;
        }
        d3.select("#drawing")
            .append("text")
            .attr("x", dialBoxBB.x + dialBoxBB.width * textXOffsetFactor)
            .attr("y", dialBoxBB.y + dialBoxBB.height * 0.7)
            .text(gasTotal + " m³")
            .style("font-family", "Consolas")
            .style("font-size", "5.25px")
            .style("fill", "black");

    }
}

function getDataFromGitHub(day, dataType, callback) {
    const url = "https://raw.githubusercontent.com/markusbenjamin/kazanfutes/refs/heads/main/data/formatted/" + day + "/" + dataType + ".json";
    fetchJSONEndpoint(url)
        .then(dataJSON => {
            callback(dataJSON);
        })
        .catch(error => {
            console.error('Error fetching data from GitHub:', error);
        });
}

function pollGitHub() { //add day, file params
    const url = "https://raw.githubusercontent.com/markusbenjamin/kazanfutes/refs/heads/main/data/formatted/" + dayStamp() + "/gas_usage.json";
    setInterval(() => {
        fetchJSONEndpoint(url)
            .then(dataJSON => {
                plotCurve('drawing', 'gas-graph', dataJSON, 175, 100, 200, 160 * 2 / 3, ["óra", "ráta (m³/h)"], "mai gázfogyás");
            })
            .catch(error => {
                console.error('Error fetching data from GitHub:', error);
            });
    }, 1 * 1000);
}

function plotCurve(parentContainerId = "canvas", graphContainerId, plotData, posX = 0, posY = 0, width = 100, height = 100, axesLabel = ["", ""], plotLabel = "") {
    // Ensure the parent container exists
    const parentContainer = d3.select(`#${parentContainerId}`);
    if (parentContainer.empty()) {
        throw new Error(`No element found with id: ${parentContainerId}`);
    }

    graphBBoxPosAndSize = d3.select("#graph").node().getBBox();

    const graphXMargin = 0.035;
    const graphYMargin = 0.12;
    const graphXOffset = 0;
    const graphYOffset = 3;
    posX = graphBBoxPosAndSize.x + graphBBoxPosAndSize.width * graphXMargin / 2 + graphXOffset;
    posY = graphBBoxPosAndSize.y + graphBBoxPosAndSize.height * graphYMargin / 2 + graphYOffset;
    width = graphBBoxPosAndSize.width * (1 - graphXMargin);
    height = graphBBoxPosAndSize.height * (1 - graphYMargin);

    // Check if the graph container group already exists, otherwise create it
    let graphContainer = parentContainer.select(`g#${graphContainerId}`);
    if (graphContainer.empty()) {
        graphContainer = parentContainer.append("g").attr("id", graphContainerId);
    }

    // Get the current zoom/pan transform from #drawing
    //const drawing = d3.select("#drawing");
    graphContainer.attr("transform", `translate(${posX}, ${posY})`); // Use x and y from parameters

    // Clear any existing content in the graph container
    graphContainer.selectAll("*").remove();

    // Parse the timestamp and convert it to hours (0–24)
    const parseTime = d3.timeParse("%Y-%m-%d-%H-%M-%S"); // Match your timestamp format
    plotData.forEach(d => {
        const parsedDate = parseTime(d.timestamp); // Parse the timestamp into a Date object
        if (parsedDate) {
            d.date = parsedDate.getHours() + parsedDate.getMinutes() / 60; // Convert to fractional hours
        } else {
            console.error(`Failed to parse timestamp: ${d.timestamp}`);
        }
    });

    // Apply moving average smoothing to burnt_volume
    const smoothedData = calculateMovingAverage(plotData, "burn_rate_in_m3_per_h", 25); // Adjust window size as needed

    // Set up dimensions
    const margin = { top: 10, right: 10, bottom: 20, left: 25 };
    width = width - margin.left - margin.right; // Adjust size as needed
    height = height - margin.top - margin.bottom;

    // Add a background rectangle for better visibility
    graphContainer.append("rect")
        .attr("width", width + margin.left + margin.right)
        .attr("height", height + margin.top + margin.bottom)
        .attr("fill", "white");

    // Create the main canvas area
    const g = graphContainer.append("g")
        .attr("transform", `translate(${margin.left},${margin.top})`);

    // Set up scales
    const x = d3.scaleLinear() // Use a linear scale for numeric values
        .domain([0, 24]) // Explicitly set the domain for 24 hours
        .range([0, width]); // Map to the graph's width

    const y = d3.scaleLinear()
        //.domain([0, Math.max(10, d3.max(plotData, d => d.burn_rate_in_m3_per_h) || 0)])
        .domain([0, 10])
        .nice()
        .range([height, 0]);

    // Add X-axis
    const xAxis = g.append("g")
        .attr("transform", `translate(0, ${height})`)
        .call(d3.axisBottom(x)
            .tickSize(2) // Set tick length
            .ticks(12) // Set the number of ticks (12 for 0, 2, 4, ..., 24)
        );

    // Style the X-axis
    xAxis.select(".domain") // Select the axis line
        .style("stroke-width", "0.5px"); // Set the axis line thickness

    xAxis.selectAll(".tick line") // Select all tick lines
        .attr("stroke-width", "0.5px") // Set tick line thickness
        .attr("y2", "2"); // Adjust tick length (positive increases length)

    xAxis.selectAll("text") // Select tick labels
        .attr("dy", "3")
        .style("font-family", "Consolas")
        .style("font-size", "5px"); // Set font size for tick labels

    // Add Y-axis
    const yAxis = g.append("g")
        .call(d3.axisLeft(y)
            .tickSize(2) // Set tick length
        );

    // Style the Y-axis
    yAxis.select(".domain") // Customize the domain path to match the tick range
        .style("stroke-width", "0.5px");

    yAxis.selectAll(".tick line")
        .attr("stroke-width", "0.5px") // Set tick line thickness
        .attr("x2", "-2"); // Adjust tick length (negative for left-side ticks)

    yAxis.selectAll("text")
        .attr("dx", "0")
        .style("font-size", "5px")
        .style("font-family", "Consolas")
        .style("text-anchor", "end"); // Set font size for tick labels

    // X-axis label
    g.append("text")
        .attr("x", width / 2)
        .attr("y", height + margin.bottom - 2)
        .style("text-anchor", "middle")
        .style("font-size", "6px")
        .style("font-family", "Consolas")
        .text(axesLabel[0]);

    // Y-axis label
    g.append("text")
        .attr("transform", `rotate(-90)`)
        .attr("x", -height / 2)
        .attr("y", -margin.left + 8)
        .style("text-anchor", "middle")
        .style("font-size", "6px")
        .style("font-family", "Consolas")
        .text(axesLabel[1]);

    // Plot title
    g.append("text")
        .attr("x", width / 2)
        .attr("y", -margin.top / 2)
        .style("text-anchor", "middle")
        .style("font-size", "7px")
        .style("font-family", "Consolas")
        .text(plotLabel);

    // Add dots (optional)
    g.selectAll(".dot")
        .data(plotData)
        .enter().append("circle")
        .attr("cx", d => x(d.date))
        .attr("cy", d => y(d.burn_rate_in_m3_per_h))
        .attr("r", 0.25)
        .attr("fill", "gray");

    // Draw the line
    const line = d3.line()
        .x(d => x(d.date))
        .y(d => y(d.burn_rate_in_m3_per_h))
        .curve(d3.curveBasis);

    g.append("path")
        .datum(smoothedData)
        .attr("fill", "none")
        .attr("stroke", "red")
        .attr("stroke-width", 1.5)
        .attr("d", line);
}

d3.xml("canvas.svg").then(fileData => {
    insertCanvasFromFile(fileData);
    centerAndZoomRelativePointOfCanvas(0.5, 0.5, 3);

    setupTooltip();

    pollFirebase();
    pollGitHub();
    writeGasUsageToDial();
});