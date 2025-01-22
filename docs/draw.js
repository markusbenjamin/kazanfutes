let canvasSvg;
let xOffset, yOffset, drawingWidth, drawingHeight, aspectRatio, zoomFactor;

function setup() {
    createCanvas(1, 1, SVG);
    colorMode(RGB, 1, 1, 1, 1);
    rectMode(CENTER);
    strokeCap(SQUARE);
}

function draw() {
    if (canvasInserted) {
        extractMappingParameters();
        clearp5JSDrawingWithinCanvas();

        //rect(xOffset, yOffset, drawingWidth, drawingHeight);

        let maxGasUsage = 9;
        let mappedGasUsage = constrain(currentGasUsageRate, 0, maxGasUsage) / maxGasUsage;
        if (boilerState != null) {
            const boxDims = getBBoxP5jsDimensions("flame_nest");
            let p = { x: boxDims.cx, y: boxDims.cy }
            let s = mapSize(0.05, 0.025 * aspectRatio);

            let flameSize = 0.5 + mappedGasUsage * 0.7;
            if (boilerState == 1) {
                let wiggleAmount = 0.06;
                drawFlame(
                    p.x - boxDims.w * 0.15,
                    p.y + boxDims.h * 0.2,
                    s.w * random(1 - wiggleAmount, 1 + wiggleAmount) * 1.5 * flameSize,
                    s.h * random(1 - wiggleAmount, 1 + wiggleAmount) * 1.5 * flameSize,
                    color(1, 0.5, 0, 0.875),
                    color(1, 1, 0, 0.9),
                    true
                );
                drawFlame(
                    p.x + boxDims.w * 0.2,
                    p.y + boxDims.h * 0.2,
                    s.w * random(1 - wiggleAmount, 1 + wiggleAmount) * 1.35 * flameSize,
                    s.h * random(1 - wiggleAmount, 1 + wiggleAmount) * 1.35 * flameSize,
                    color(1, 0.5, 0, 0.875),
                    color(1, 1, 0, 0.9),
                    true
                );
                if (false) {
                    for (let i = -3; i < 4; i++) {
                        drawFlame(
                            p.x + boxDims.w * 0.2,
                            p.y + boxDims.h * 0.2,
                            s.w * random(1 - wiggleAmount, 1 + wiggleAmount) * 1.2,
                            s.h * random(1 - wiggleAmount, 1 + wiggleAmount) * 1.2,
                            color(1, 0.5, 0, 0.875),
                            color(1, 1, 0, 0.9),
                            true
                        );
                    }
                }
            } else {
                let wiggleAmount = 0.035;
                for (let i = -3; i < 4; i++) {
                    drawFlame(
                        p.x + boxDims.w * i / 10 * 1.3,
                        p.y + boxDims.h * 0.5,
                        s.w * random(1 - wiggleAmount, 1 + wiggleAmount) * 0.3,
                        s.h * random(1 - wiggleAmount, 1 + wiggleAmount) * 0.3,
                        color(0.502, 0.918, random(0.8, 0.929), 0.875),
                        color(random(0.3, 0.4), 0.463, 0.784, 0.9),
                        true
                    );
                }
            }
            if (isValidNumber(currentGasUsageRate)) {
                //console.log(currentGasUsageRate);
                const boilerDims = getBBoxP5jsDimensions("boiler_body");

                let p = { x: boilerDims.cx, y: boilerDims.cy - boilerDims.h * 0.2 };
                let s = boilerDims.w * 0.5;
                stroke(boilerState ? 1 : 0, 0, boilerState ? 0 : 1, 1);
                stroke(0);
                strokeWeight(0.6);
                noFill();
                ellipse(p.x, p.y, s, s);
                fill(0);
                ellipse(p.x, p.y, s * 0.1, s * 0.1);


                let gasUsageDialOffset = PI / 3;
                let gasUsageDialSpacing = PI / 6;

                let dialAngle = PI / 2 + gasUsageDialOffset + (TWO_PI - 2 * gasUsageDialOffset) * mappedGasUsage;
                let dialLength = s * 0.038;

                let tickStartLength = s * 0.038 * 0.8;
                for (let tickAngle = PI / 2 + gasUsageDialOffset; tickAngle <= PI / 2 + TWO_PI - gasUsageDialOffset + gasUsageDialSpacing; tickAngle += gasUsageDialSpacing) {
                    strokeWeight(0.25);
                    stroke(0.5);
                    line(
                        p.x + s * tickStartLength * cos(tickAngle),
                        p.y + s * tickStartLength * sin(tickAngle),
                        p.x + s * dialLength * cos(tickAngle),
                        p.y + s * dialLength * sin(tickAngle)
                    );
                }
                strokeWeight(0.5);
                stroke(0.1);
                strokeCap(ROUND);
                line(p.x, p.y, p.x + s * dialLength * cos(dialAngle), p.y + s * dialLength * sin(dialAngle));
                strokeCap(SQUARE);

            }
        }

        flipToCanvas();
    }
}

function extractMappingParameters() { //The whole scheme is not really used, should be removed
    const backgroundBBox = d3.select("#background").node().getBBox();
    let topLeft = { x: backgroundBBox.x, y: backgroundBBox.y };
    let bottomRight = { x: backgroundBBox.x + backgroundBBox.width, y: backgroundBBox.y + backgroundBBox.height };
    xOffset = topLeft.x;
    yOffset = topLeft.y;
    drawingWidth = bottomRight.x - xOffset;
    drawingHeight = bottomRight.y - yOffset;
    aspectRatio = drawingWidth / drawingHeight;
    zoomFactor = 1 / 3;
}

function mapPos(xRelative, yRelative) {
    const x = xRelative * drawingWidth + xOffset;
    const y = yRelative * drawingHeight + yOffset;
    return {
        x: x,
        y: y
    }
}

function mapSize(wRelative, hRelative) {
    return {
        w: wRelative * drawingWidth,
        h: hRelative * drawingHeight
    }
}


function getBBoxP5jsDimensions(id) {
    const relativeDims = getBBoxRelativeDimensionsOld(id);
    let p = mapPos(relativeDims.x, relativeDims.y);
    let s = mapSize(relativeDims.w, relativeDims.h);
    let c = mapPos(relativeDims.cx, relativeDims.cy);
    return {
        x: p.x,
        y: p.y,
        w: s.w,
        h: s.h,
        cx: c.x,
        cy: c.y
    }
}

function getBBoxRelativeDimensions(id) {
    const bgDims = d3.select("#background").node().getBBox();
    const targetDims = d3.select("#" + id).node().getBBox();
    let relativeDims = {
        x: (targetDims.x - bgDims.x)/bgDims.width,
        y: (targetDims.y - bgDims.y)/bgDims.height,
        w: targetDims.width / bgDims.width,
        h: targetDims.height / bgDims.height,
        width: targetDims.width / bgDims.width,
        height: targetDims.height / bgDims.height
    }
    relativeDims["cx"] = relativeDims.x + relativeDims.w / 2;
    relativeDims["cy"] = relativeDims.y + relativeDims.h / 2;
    console.log(relativeDims);
    return relativeDims;
}

function getBBoxRelativeDimensionsOld(id) {
    const bBoxAbsoluteDims = d3.select("#" + id).node().getBBox();
    return {
        x: (bBoxAbsoluteDims.x - xOffset) / drawingWidth,
        y: (bBoxAbsoluteDims.y - yOffset) / drawingHeight,
        w: bBoxAbsoluteDims.width / drawingWidth,
        h: bBoxAbsoluteDims.height / drawingHeight,
        cx: (bBoxAbsoluteDims.x - xOffset + bBoxAbsoluteDims.width / 2) / drawingWidth,
        cy: (bBoxAbsoluteDims.y - yOffset + bBoxAbsoluteDims.height / 2) / drawingHeight
    }
}

function getBBoxDrawingDimensions(id) {
    const d3Dims = d3.select("#" + id).node().getBBox();
    return {
        x: d3Dims.x,
        y: d3Dims.y,
        cx: d3Dims.x + d3Dims.width / 2,
        cy: d3Dims.y + d3Dims.height / 2,
        w: d3Dims.width,
        h: d3Dims.height,
        width: d3Dims.width,
        height: d3Dims.height
    } // Overloaded for safety
}

function clearp5JSDrawingWithinCanvas() {
    const drawingGroup = document.querySelector("#p5jsDrawing"); // Select the group directly
    drawingGroup.querySelectorAll("g").forEach(g => g.remove()); // Remove all <g> elements
}

function flipToCanvas() {
    clearp5JSDrawingWithinCanvas();

    const groups = drawingContext.__root.querySelectorAll("g"); // Get all <g> elements
    groups.forEach(group => {
        select("#p5jsDrawing").elt.appendChild(group.cloneNode(true)); // Clone and append each <g>
    });
    document.getElementById("defaultCanvas0").style.display = "none";
    clear();
}

function drawFlame(x, y, w, h, colOuter, colInner, outer) {
    push();
    translate(x, y);
    fill(colOuter);
    noStroke();
    beginShape();

    // Draw right side of the flame using the given function and mirror for left side
    for (let i = 0; i <= 1; i += 0.01) {
        let flameX = (1 / 5) * pow(-1 + i, 2) * i * (-5 + 4 * i) * w;
        let flameY = -h * i;
        vertex(flameX, flameY);
    }

    // Draw the left side as a mirrored version of the right side
    for (let i = 1; i >= 0; i -= 0.01) {
        let flameX = -(1 / 5) * pow(-1 + i, 2) * i * (-5 + 4 * i) * w;
        let flameY = -h * i;
        vertex(flameX, flameY);
    }

    endShape(CLOSE);
    pop();

    if (outer) {
        drawFlame(x, y - h * 0.05, w * 0.6, h * 0.5, colInner, colInner, false)
    }
}