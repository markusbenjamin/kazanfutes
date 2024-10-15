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

function roundTo(num, multiple) {
    return Math.round(num / multiple) * multiple;
}