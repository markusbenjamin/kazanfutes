// Define the dimensions and margins of the graph
const margin = { top: 20, right: 30, bottom: 30, left: 40 };
const width = 800 - margin.left - margin.right;
const height = 400 - margin.top - margin.bottom;

// Append the SVG object to the body of the page
const svg = d3.select("#chart")
    .append("svg")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom)
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top})`);

// Load the data from the JSON log files
const files = ["data1.json", "data2.json"];

Promise.all(files.map(url => d3.text(url))).then(fileContents => {
    let combinedData = [];

    fileContents.forEach(content => {
        const lines = content.trim().split('\n');
        lines.forEach(line => {
            const data = JSON.parse(line);
            Object.entries(data).forEach(([room, values]) => {
                if (values.temp !== "none" && values.hum !== "none") {
                    combinedData.push({
                        room: room,
                        temp: values.temp / 100,
                        hum: values.hum / 100,
                        timestamp: d3.timeParse("%Y-%m-%d-%H-%M")(values.last_updated)
                    });
                }
            });
        });
    });

    // Filter data to the last 24 hours
    const now = new Date();
    combinedData = combinedData.filter(d => now - d.timestamp <= 24 * 60 * 60 * 1000);

    // Nest data by room
    const nestedData = d3.group(combinedData, d => d.room);

    // Set the scales
    const x = d3.scaleTime()
        .domain(d3.extent(combinedData, d => d.timestamp))
        .range([0, width]);
    const y = d3.scaleLinear()
        .domain([0, d3.max(combinedData, d => d.temp)])
        .range([height, 0]);

    // Add the x-axis
    svg.append("g")
        .attr("transform", `translate(0,${height})`)
        .call(d3.axisBottom(x));

    // Add the y-axis
    svg.append("g")
        .call(d3.axisLeft(y));

    // Add the lines
    const line = d3.line()
        .x(d => x(d.timestamp))
        .y(d => y(d.temp));

    nestedData.forEach((values, room) => {
        svg.append("path")
            .datum(values)
            .attr("class", "line")
            .attr("d", line)
            .attr("stroke", () => d3.schemeCategory10[room % 10]);
    });
});
