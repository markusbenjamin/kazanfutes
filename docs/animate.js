function insertDrawingFromFile(fileData) {
    // Extract the original SVG element
    const originalSVG = fileData.documentElement;

    // Create a new SVG element
    const newSVG = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    newSVG.id = "drawing";
    newSVG.setAttribute("originalWidth", originalSVG.getAttribute("width"))
    newSVG.setAttribute("originalHeight", originalSVG.getAttribute("height"))
    newSVG.setAttribute("viewBox", `0 0 ${window.innerWidth} ${window.innerHeight}`);
    newSVG.setAttribute("width", "100%");  // Make SVG cover the viewport
    newSVG.setAttribute("height", "100%");

    // Select all <g> elements in the original SVG
    const groups = originalSVG.querySelectorAll("g");
    groups.forEach(group => {
        // Create a new <g> element
        const newGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");

        // Set the new group ID based on `inkscape:label`
        newGroup.id = group.getAttribute("inkscape:label"); // Use inkscape:label as the ID
        const idioticShift = group.getAttribute("transform").match(/-?\d+\.\d+/g).map(num => Math.floor(parseFloat(num)));
        newGroup.setAttribute("idioticShiftX", idioticShift[0]); // To counteract the idiotic & unnecessary export shift of Inkscape
        newGroup.setAttribute("idioticShiftY", idioticShift[1]);

        // Clone child nodes (like paths, shapes) and append them to the new group
        group.childNodes.forEach(child => {
            newGroup.appendChild(child.cloneNode(true));
        });

        // Append the cleaned group to the new SVG
        newSVG.appendChild(newGroup);
    });

    // Append the new SVG to the container in the HTML
    document.getElementById("container").appendChild(newSVG);
}

function getDrawingDimensions() {
    const container = d3.select("#container");
    const drawing = container.select("#drawing")
    const wireframe = drawing.select("#wireframe");  // Select the inner layer using layerReference

    const zeroPositionShiftX = parseInt(wireframe.node().getAttribute("idioticShiftX"))
    const zeroPositionShiftY = parseInt(wireframe.node().getAttribute("idioticShiftY"))
    const drawingWidth = parseInt(drawing.node().getAttribute("originalWidth"))
    const drawingHeight = parseInt(drawing.node().getAttribute("originalHeight"))
    return {
        idioticShift: [zeroPositionShiftX, zeroPositionShiftY],
        size: [drawingWidth, drawingHeight]
    }
}

function centerAndZoomRelativePointOfDrawing(targetX, targetY, zoomLevel, duration = 10) {
    const container = d3.select("#container");

    const drawingDimensions = getDrawingDimensions();
    const scalingCorrection = [
        (window.innerWidth - drawingDimensions.size[0] * zoomLevel) / 2,
        (window.innerHeight - drawingDimensions.size[1] * zoomLevel) / 2
    ]
    const target = [
        targetX * drawingDimensions.size[0], // In original drawing coordinates!
        targetY * drawingDimensions.size[1]
    ]

    const drawing = container.select("#drawing")
    const wireframe = drawing.select("#wireframe");

    const zoomToPoint = d3.zoom()
        .on("zoom", ({ transform }) => {
            wireframe.transition().duration(duration).attr("transform", transform);
        });
    container.call(zoomToPoint.transform, d3.zoomIdentity.translate(
        drawingDimensions.idioticShift[0] * zoomLevel + scalingCorrection[0] + (drawingDimensions.size[0] / 2 - target[0]) * zoomLevel,
        drawingDimensions.idioticShift[1] * zoomLevel + scalingCorrection[1] + (drawingDimensions.size[1] / 2 - target[1]) * zoomLevel
    ).scale(zoomLevel));

    const zoomWithMouse = d3.zoom()
        .scaleExtent([0.1, 10])
        .on("zoom", ({ transform }) => {
            wireframe.transition().duration(10).attr("transform", transform);
        });
    container.call(zoomWithMouse);
}

function updateRoomColor(roomId, temp) {
    // Create a color scale
    const colorScale = d3.scaleSequential(d3.interpolateRgb("blue", "red"))
        .domain([15, 25]); // Set the input domain (10°C to 30°C)
    d3.select(roomId).style("fill", colorScale(temp));
}

function pollFirebase() {
    const url = "https://kazanfutes-71b78-default-rtdb.europe-west1.firebasedatabase.app/system.json"; // Update with your Firebase URL
    setInterval(() => {
        fetchJSONEndpoint(url)
            .then(systemJSON => {
                const roomNums = [1, 2, 3, 4, 5, 6, 7, 8, 9];
                roomNums.forEach(roomNum => {
                    updateRoomColor("#"+systemJSON.setup.rooms[roomNum].name, systemJSON.state['measured_temps'][roomNum]);
                });
            })
            .catch(error => {
                console.error('Error fetching data:', error);
            });
    }, 5000);
}

d3.xml("drawing.svg").then(fileData => {
    insertDrawingFromFile(fileData)
    centerAndZoomRelativePointOfDrawing(0.5, 0.5, 5);

    pollFirebase();
});