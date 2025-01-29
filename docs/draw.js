let canvasSvg;
let xOffset, yOffset, drawingWidth, drawingHeight, aspectRatio, zoomFactor;

function setup() {
    createCanvas(1, 1, SVG);
    colorMode(RGB, 1, 1, 1, 1);
    rectMode(CENTER);
    strokeCap(SQUARE);
    textAlign(CENTER, CENTER);
}

function draw() {
    if (canvasInserted) {
        extractMappingParameters();
        clearp5JSDrawingWithinCanvas();

        drawBoiler();

        drawExternalThermometer();

        flipToCanvas();
    }
}

function drawExternalThermometer() {
    if (externalTemp) {
        const boxDims = getBBoxP5jsDimensions("external_thermometer");
        let x = boxDims.cx;
        let y = boxDims.cy;
        let w = boxDims.w;
        let h = boxDims.h;

        let tempRange;
        if (externalTemp < -5) {
            tempRange = [-10, 5];
        }
        else if (externalTemp < 10) {
            tempRange = [-5, 10];
        }
        else if (externalTemp < 20) {
            tempRange = [5, 20];
        }
        else if (externalTemp < 30) {
            tempRange = [15, 30]
        }
        else {
            tempRange = [25, 40]
        }
        let tempStripRange = [y + h * 0.425, y - h * 0.425]
        let tempLineX = x - w * 0.255;
        let tempLineW = w * 0.15;
        let extTempPos = map(externalTemp, tempRange[0], tempRange[1], tempStripRange[0], tempStripRange[1]);
        let extTempNorm = externalTemp / (tempRange[1] - tempRange[0]);

        stroke(0.25);
        //line(x + w * 0.35, tempStripRange[0], x + w * 0.35, tempStripRange[1])
        textAlign(RIGHT, CENTER);
        for (let temp = tempRange[0]; temp <= tempRange[1]; temp++) {
            let tempPos = map(temp, tempRange[0], tempRange[1], tempStripRange[0], tempStripRange[1]);
            if (temp == 0) {
                stroke(0.25);
                strokeWeight(tempLineW * 0.45);
                line(x - w * 0.5, tempPos, x + w * 0.5, tempPos);
            }
            else if (temp % 5 == 0) {
                stroke(0.25);
                fill(0.25)
                if (temp < 0) {
                    //stroke(0.75, 0, 0)
                }
                strokeWeight(tempLineW * (getZoomLevel() < 5 ? 0.4 : 0.25));
                line(x + w * 0.22, tempPos, x + w * 0.5, tempPos);
                noStroke();
                textFont(dashboardFont, getZoomLevel() < 5 ? 4 : 4);
                text(temp, x + w * 0.17, tempPos)
            }
            else {
                stroke(0.35);
                fill(0.55);
                if (temp < 0) {
                    //stroke(0.75, 0, 0, 0.5)
                }
                strokeWeight(tempLineW * (getZoomLevel() < 5 ? 0.25 : 0.2));
                line(x + w * 0.3, tempPos, x + w * 0.5, tempPos);
                noStroke();
                if (getZoomLevel() > 3) {
                    textFont(dashboardFont, 2.5);
                    text(temp, x + w * 0.2, tempPos)
                }
            }
        }
        textAlign(CENTER, CENTER);

        stroke(1);
        strokeCap(ROUND);
        strokeWeight(tempLineW);
        //line(tempLineX, tempStripRange[0], tempLineX, tempStripRange[1]);
        stroke(extTempNorm, 0, 1 - extTempNorm, 1);
        fill(extTempNorm, 0, 1 - extTempNorm, 1);
        stroke(extTempNorm, 0, 1 - extTempNorm, 1);
        stroke(28 / 255, 3 / 255, 252 / 255, 0.92);
        fill(28 / 255, 3 / 255, 252 / 255, 0.92);
        strokeWeight(tempLineW * 0.75);
        line(tempLineX, y + h * 0.49, tempLineX, extTempPos);
        ellipse(tempLineX, extTempPos, w * 0.1, w * 0.1);
        strokeCap(SQUARE);
    }
}

function drawBoiler() {
    let maxGasUsage = 10.5;
    let mappedGasUsage = constrain(currentGasUsageRate, 0, maxGasUsage - 0.5) / (maxGasUsage - 0.5);
    if (boilerState != null) {
        const boxDims = getBBoxP5jsDimensions("flame_nest");
        let p = { x: boxDims.cx, y: boxDims.cy }
        let s = mapSize(0.05, 0.025 * aspectRatio);

        //mappedGasUsage = 0;
        let flameSize = 0.3 + mappedGasUsage * 0.7;
        if (boilerState == 1) {
            let wiggleAmount = 0.06;
            extraFlameNum = 2;
            if (true) {
                for (let i = -(3 + extraFlameNum / 2); i < 4 + extraFlameNum / 2; i += 2) {
                    drawFlame(
                        p.x + boxDims.w / 2 * i / 10 * 2,
                        p.y + boxDims.h * 0.43,
                        s.w * random(1 - wiggleAmount, 1 + wiggleAmount) * flameSize,
                        s.h * random(1 - wiggleAmount, 1 + wiggleAmount) * flameSize,
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
            const dialDims = getBBoxP5jsDimensions("gas_rate_gauge");
            //console.log(dialDims)

            let p = { x: dialDims.cx, y: dialDims.cy };
            let s = dialDims.w;
            let r = s / 2;

            let gasUsageDialOffset = PI / 4;
            let dialAngle = (PI / 2 + gasUsageDialOffset + (TWO_PI - 2 * gasUsageDialOffset) * mappedGasUsage) * random(0.997, 1.003);
            let dialLength = s * 0.039;

            let gasUsageDialTickNum = 100;
            let primaryTickStartLength = r * 0.75;
            let primaryTickEndLength = r * 1;
            let primaryTickStrokeW = 0.15;
            let primaryTickNumberPosition = r * 0.65;
            let primaryTickColor = 0;
            let primaryTickFontSize = 0.8;

            let secondaryTickStartLength = r * 0.85;
            let secondaryTickEndLength = r * 1;
            let secondaryTickStrokeW = 0.05;
            let secondaryTickNumberPosition = r * 0.75;
            let secondaryTickColor = 0.3;
            let secondaryTickFontSize = 0.4;
            let tickNum = 0;
            for (let tickAngle = PI / 2 + gasUsageDialOffset; tickAngle <= PI / 2 + (TWO_PI - gasUsageDialOffset); tickAngle += (TWO_PI - 2 * gasUsageDialOffset) / gasUsageDialTickNum) {
                // Determine gas usage corresponding to drawn angle
                let gasUsageRateCorrespondingToAngle = constrain(
                    (tickAngle - (PI / 2 + gasUsageDialOffset)) * (maxGasUsage - 0.5) / (TWO_PI - 2 * gasUsageDialOffset),
                    0,
                    maxGasUsage - 0.5
                )

                if (getZoomLevel() > 7.5) {
                    // Draw secondary ticks and numbers
                    if (tickNum % 1 == 0) {
                        strokeWeight(secondaryTickStrokeW);
                        stroke(secondaryTickColor);
                        line(
                            p.x + secondaryTickStartLength * cos(tickAngle),
                            p.y + secondaryTickStartLength * sin(tickAngle),
                            p.x + secondaryTickEndLength * cos(tickAngle),
                            p.y + secondaryTickEndLength * sin(tickAngle)
                        );
                    }
                    if (tickNum % 10 == 5) {
                        strokeWeight(secondaryTickStrokeW * 1.5);
                        stroke(secondaryTickColor);
                        line(
                            p.x + secondaryTickStartLength * 0.95 * cos(tickAngle),
                            p.y + secondaryTickStartLength * 0.95 * sin(tickAngle),
                            p.x + secondaryTickEndLength * cos(tickAngle),
                            p.y + secondaryTickEndLength * sin(tickAngle)
                        );
                        fill(secondaryTickColor);
                        noStroke();

                        push();
                        translate(p.x + secondaryTickNumberPosition * cos(tickAngle), p.y + secondaryTickNumberPosition * sin(tickAngle));
                        rotate(tickAngle + PI / 2);
                        textFont(dashboardFont, secondaryTickFontSize);
                        //text(roundTo(gasUsageRateCorrespondingToAngle, 0.1), 0, 0);
                        pop();
                    }
                }


                // Draw primary ticks and numbers
                if (!isFractional(roundTo(gasUsageRateCorrespondingToAngle, 0.1))) {
                    stroke(primaryTickColor);
                    if (getZoomLevel() > 5) {
                        strokeWeight(primaryTickStrokeW);
                    }
                    else {
                        strokeWeight(primaryTickStrokeW * 2);
                        primaryTickStartLength = primaryTickNumberPosition;
                    }
                    line(
                        p.x + primaryTickStartLength * cos(tickAngle),
                        p.y + primaryTickStartLength * sin(tickAngle),
                        p.x + primaryTickEndLength * cos(tickAngle),
                        p.y + primaryTickEndLength * sin(tickAngle)
                    );
                }
                if (getZoomLevel() > 5) {
                    if (!isFractional(roundTo(gasUsageRateCorrespondingToAngle, 0.1))) {
                        fill(primaryTickColor);
                        noStroke();

                        push();
                        translate(p.x + primaryTickNumberPosition * cos(tickAngle), p.y + primaryTickNumberPosition * sin(tickAngle));
                        rotate(tickAngle + PI / 2);
                        textFont(dashboardFont, primaryTickFontSize);
                        text(roundTo(gasUsageRateCorrespondingToAngle, 0.1), 0, 0);
                        pop();
                    }
                }

                tickNum++;
            }

            // Draw hand
            strokeWeight(0.5);
            stroke(0.1);
            //line(p.x, p.y, p.x + s * dialLength * cos(dialAngle), p.y + s * dialLength * sin(dialAngle));
            //strokeCap(SQUARE);
            drawIsoscelesTriangle(
                p.x - r * 0.2 * cos(dialAngle), p.y - r * 0.2 * sin(dialAngle),
                0.201, r * 2, PI / 2 + dialAngle, 0.25);

            // Draw gauge
            stroke(0);
            strokeWeight(0.6);
            noFill();
            ellipse(p.x, p.y, s, s);
            fill(0);
            ellipse(p.x, p.y, s * 0.1, s * 0.1);
            noStroke();

            if (getZoomLevel() > 5) {
                // Write labels
                textFont(dashboardFont, 0.8);
                fill(0);
                text("m³/h", p.x, p.y + r * 0.35);

                let rotateToVertical = PI / 2;
                let labelAngleOffset = PI * 0.85;
                let labelRadius = r * 0.84;
                textFont("Courier New", 0.4);
                fill(0, 0.1);
                textOnArcUprightWeighted("M/B Méréstechnika", p.x, p.y, labelRadius, (0 + labelAngleOffset) + rotateToVertical, (TWO_PI - labelAngleOffset) + rotateToVertical);
            }
        }
    }
}

function textOnArcUprightWeighted(
    txt,
    centerX,
    centerY,
    radius,
    startAngle,
    endAngle
) {
    const len = txt.length;
    if (len === 0) return;

    // 1) Measure the width of each character, so we know how to proportionally
    //    distribute them along the arc.
    let charWidths = [];
    let totalWidth = 0;
    for (let i = 0; i < len; i++) {
        let w = textWidth(txt[i]);
        charWidths.push(w);
        totalWidth += w;
    }

    // 2) Keep track of how much width we've consumed so far
    //    so we can find each character's position along the arc.
    let consumedWidth = 0;

    for (let i = 0; i < len; i++) {
        // Character's own width
        let w = charWidths[i];

        // We want to place this character so that its *center* is allocated
        // half of its own width beyond whatever we've placed so far.
        let centerOfChar = consumedWidth + w / 2;

        // Convert that center position into a fraction of the total string width
        let fraction = centerOfChar / totalWidth;

        // Interpolate the angle for this character’s center
        let angle = TWO_PI - lerp(startAngle, endAngle, fraction);

        push();
        translate(
            centerX + radius * cos(angle),
            centerY + radius * sin(angle)
        );

        rotate(angle + PI + PI / 2);
        text(txt[i], 0, 0);
        pop();

        // 3) Update consumedWidth to move past this character
        consumedWidth += w;
    }
}

function textOnArcUpright(
    txt,
    centerX,
    centerY,
    radius,
    startAngle,
    endAngle
) {
    const len = txt.length;
    if (len === 0) return;

    for (let i = 0; i < len; i++) {
        // Interpolate the angle for this character.
        // If you have only one character (len=1), angleStep is irrelevant, so just place it at startAngle.
        let angle = (len > 1)
            ? map(len - 1 - i, 0, len - 1, startAngle, endAngle)
            : (startAngle + endAngle) / 2;

        push();
        // Move to the circle perimeter at this angle
        translate(
            centerX + radius * cos(angle),
            centerY + radius * sin(angle)
        );
        rotate(angle + PI + PI / 2);
        text(txt[i], 0, 0);
        pop();
    }
}

function drawIsoscelesTriangle(x, y, ratio, sideLength, rotationAngle, scaleFactor = 1) {
    push();

    // Translate to the desired position.
    translate(x, y);

    // Apply scaling.
    scale(scaleFactor);

    // Apply rotation.
    rotate(rotationAngle);

    // Calculate the base of the triangle.
    let base = ratio * sideLength;

    // Half of the base.
    let halfBase = base / 2;

    // The height of the isosceles triangle from Pythagorean theorem:
    // sideLength^2 = height^2 + (base/2)^2
    let height = sqrt(sideLength * sideLength - halfBase * halfBase);

    // Draw the triangle using the p5.js triangle() function.
    // The reference position is moved so that:
    //   - The base is centered at (0, 0).
    //   - The apex is at (0, -height).
    triangle(
        -halfBase, 0,       // left base corner
        halfBase, 0,       // right base corner
        0, -height  // apex
    );

    pop();
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
        x: (targetDims.x - bgDims.x) / bgDims.width,
        y: (targetDims.y - bgDims.y) / bgDims.height,
        w: targetDims.width / bgDims.width,
        h: targetDims.height / bgDims.height,
        width: targetDims.width / bgDims.width,
        height: targetDims.height / bgDims.height
    }
    relativeDims["cx"] = relativeDims.x + relativeDims.w / 2;
    relativeDims["cy"] = relativeDims.y + relativeDims.h / 2;
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
        const clonedGroup = group.cloneNode(true); // Clone the group
        clonedGroup.setAttribute("class", "clickthrough"); // Set the class for the cloned element
        select("#p5jsDrawing").elt.appendChild(clonedGroup); // Append the cloned group
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