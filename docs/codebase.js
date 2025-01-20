function fetchJSONEndpoint(url) {
    return fetch(url)
        .then(response => response.json())
        .then(data => {
            return data;
        })
        .catch(error => {
            console.error('Error fetching data:', error);
            throw error;
        });
}

function googleTimestamp(date = null) {
    if (date == null) {
        date = new Date()
    }
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');  // Months are 0-indexed
    const year = date.getFullYear();
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');

    return `${day}/${month}/${year} ${hours}:${minutes}:${seconds}`;
}

function humanTimestamp(date = null) {
    if (date == null) {
        date = new Date()
    }
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');  // Months are 0-indexed
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');

    return `${year}.${month}.${day}. ${hours}:${minutes}`;
}

function dayStamp(date = null) {
    if (date == null) {
        date = new Date()
    }
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');  // Months are 0-indexed
    const day = String(date.getDate()).padStart(2, '0');

    return `${year}-${month}-${day}`;
}

function timestamp(date = null) {
    if (date == null) {
        date = new Date()
    }
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');  // Months are 0-indexed
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');

    return `${year}-${month}-${day}-${hours}-${minutes}-${seconds}`;
}

function dateFromTimestamp(timestampString) {
    // Split the string by hyphens
    const parts = timestampString.split('-');

    // Extract the date and time components
    const year = parseInt(parts[0], 10);
    const month = parseInt(parts[1], 10) - 1;  // Months are 0-indexed in JS Date
    const day = parseInt(parts[2], 10);
    const hour = parseInt(parts[3], 10);
    const minute = parseInt(parts[4], 10);
    const second = parseInt(parts[5], 10);

    // Create and return a new Date object
    return new Date(year, month, day, hour, minute, second);
}

function timePassedSince(date, granularity = 'minutes') {
    const now = new Date();  // Current date and time
    const difference = now - date;  // Difference in milliseconds

    switch (granularity) {
        case 'milliseconds':
            return difference;
        case 'seconds':
            return Math.floor(difference / 1000);
        case 'minutes':
            return Math.floor(difference / 1000 / 60);
        case 'hours':
            return Math.floor(difference / 1000 / 60 / 60);
        case 'days':
            return Math.floor(difference / 1000 / 60 / 60 / 24);
        default:
            throw new Error("Invalid granularity specified. Use 'milliseconds', 'seconds', 'minutes', 'hours', or 'days'.");
    }
}

function addTimeToDate(date, amount, granularity) {
    const newDate = new Date(date);  // Create a copy of the original date

    switch (granularity) {
        case 'milliseconds':
            newDate.setMilliseconds(newDate.getMilliseconds() + amount);
            break;
        case 'seconds':
            newDate.setSeconds(newDate.getSeconds() + amount);
            break;
        case 'minutes':
            newDate.setMinutes(newDate.getMinutes() + amount);
            break;
        case 'hours':
            newDate.setHours(newDate.getHours() + amount);
            break;
        case 'days':
            newDate.setDate(newDate.getDate() + amount);
            break;
        default:
            throw new Error("Invalid granularity. Use 'milliseconds', 'seconds', 'minutes', 'hours', or 'days'.");
    }

    return newDate;
}

function roundTo(num, multiple) {
    return Math.round(num / multiple) * multiple;
}

// Function to calculate moving average
function calculateMovingAverage(data, field, windowSize) {
    // Ensure data is actually an array
    if (!Array.isArray(data)) {
        console.warn("calculateMovingAverage: 'data' is not an array:", data);
        return [];
    }

    // If empty array, just return an empty array
    if (data.length === 0) {
        return [];
    }

    // Main logic
    return data.map((d, i, arr) => {
        if (!d) {
            // If an element is null/undefined, you can decide how to handle it:
            // either return it as is, or create a fallback object, etc.
            return d;
        }

        const start = Math.max(0, i - Math.floor(windowSize / 2));
        const end = Math.min(arr.length, i + Math.floor(windowSize / 2) + 1);

        // slice out the subset
        const subset = arr.slice(start, end);

        // compute mean for 'field'
        const average = d3.mean(subset, v => v && v[field]);

        // return a new object with the smoothed field
        return { ...d, [field]: average };
    });
}


function getUnixDay(date = null) {
    if (date == null) {
        date = new Date();
    }

    // Get the time zone offset for Budapest in milliseconds
    const options = { timeZone: 'Europe/Budapest', year: 'numeric', month: '2-digit', day: '2-digit' };
    const formatter = new Intl.DateTimeFormat('en-US', options);

    // Use the formatter to convert to Budapest time
    const parts = formatter.formatToParts(date);

    // Ensure proper extraction of year, month, and day
    const year = parts.find(part => part.type === 'year').value;
    const month = parts.find(part => part.type === 'month').value;
    const day = parts.find(part => part.type === 'day').value;

    // Reconstruct the adjusted time in the Budapest time zone
    const adjustedDate = new Date(`${year}-${month}-${day}T00:00:00Z`);
    console.log(adjustedDate);  // Check the constructed date
    const unixDay = Math.floor(adjustedDate.getTime() / (1000 * 60 * 60 * 24));

    return unixDay;
}

function getHourOfDay(date = null) {
    if (date == null) {
        date = new Date()
    }
    return Number(date.toTimeString().slice(0, 2));
}

function getFractionalHourOfDay(date = null) {
    if (date == null) {
        date = new Date()
    }
    
    return date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600;
}

function hasNoNullValues(obj) {
    return Object.values(obj).every(value => value !== null);
}

let mousePosition = { x: 0, y: 0 };

// Add an event listener to track mouse position
window.addEventListener("pointermove", (event) => {
    mousePosition.x = event.clientX; // X-coordinate in viewport space
    mousePosition.y = event.clientY; // Y-coordinate in viewport space
});

// Function to poll the current mouse position
function getMousePosition() {
    return { ...mousePosition }; // Return a copy of the current mouse position
}

function runOnceThenSetInterval(functionToRun, interval) {
    functionToRun();
    setInterval(functionToRun, interval);
}

function deepObjectMerger(target, source) {
    // If the target isn't an object or is null, set it to an empty object
    if (typeof target !== 'object' || target === null) {
        target = {};
    }
    
    // Go through each property in the source
    for (const key in source) {
        if (Object.prototype.hasOwnProperty.call(source, key)) {
            const sourceValue = source[key];
            const targetValue = target[key];
            
            // If sourceValue is a non-array object, recurse
            if (
                typeof sourceValue === 'object' && 
                sourceValue !== null && 
                !Array.isArray(sourceValue)
            ) {
                target[key] = deepObjectMerger(targetValue, sourceValue);
            } else {
                // Otherwise just overwrite the property
                target[key] = sourceValue;
            }
        }
    }
    return target;
}

function splitDataIntoSegments(data, xKey, gapThreshold) {
    const segments = [];
    if (!data || data.length === 0) return segments;

    let currentSegment = [data[0]];

    for (let i = 1; i < data.length; i++) {
        const prev = data[i - 1];
        const curr = data[i];

        // If the gap is too large, start a new segment
        if ((curr[xKey] - prev[xKey]) > gapThreshold) {
            segments.push(currentSegment);
            currentSegment = [curr];
        } else {
            currentSegment.push(curr);
        }
    }
    // Push whatever is left as the last segment
    segments.push(currentSegment);

    return segments;
}