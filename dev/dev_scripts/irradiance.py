from meteostat import Point, Hourly
import pandas as pd

# Define the location (Budapest, 8th district)
location = Point(47.4879, 19.0929)  # Decimal form of 47°29'16.5"N, 19°05'34.4"E

# Define the date range
start = pd.Timestamp('2024-01-01')
end = pd.Timestamp('2024-12-31')

# Fetch hourly data
data = Hourly(location, start, end)
data = data.fetch()

# Filter for global solar irradiance ('tsun' or 'ghi' if available)
print(data[['global']])  # might be 'ghi', 'tsun', or 'srad' depending on what's available