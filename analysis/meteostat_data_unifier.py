import os
import pandas as pd
from datetime import datetime

# Function to standardize timestamp format
def format_timestamp(ts):
    try:
        # Try to parse the timestamp in the "MM/DD/YYYY H:MM" format and convert to the desired format
        #2024-07-27 00:00:00
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d-%H-%M-%S")
    except ValueError:
        return ts  # Return original if the format is unexpected

# Get all CSV files from the current directory
csv_files = [f for f in os.listdir('.') if f.endswith('.csv')]

# Load all CSV files into dataframes
dataframes = [pd.read_csv(file) for file in csv_files]

# Concatenate all dataframes
combined_df = pd.concat(dataframes, ignore_index=True)

# Standardize the timestamp format in the 'time' column
combined_df['time'] = combined_df['time'].apply(format_timestamp)

# Remove duplicate rows based on the 'time' column
cleaned_df = combined_df.drop_duplicates(subset='time')

# Ensure the columns are renamed correctly
cleaned_df = cleaned_df.rename(columns={
    'time': 'timestamp',
    'temp': 'temp',
    'rhum': 'humidity',
    'wspd': 'wind speed',
    'coco': 'coco'
})

# Select and reorder the required columns
final_df = cleaned_df[['timestamp', 'temp', 'humidity', 'wind speed', 'coco']]

# Save the cleaned and unified data to a CSV file
output_file = 'unified_weather_data_cleaned.csv'
final_df.to_csv(output_file, index=False)

print(f"Unified data saved to {output_file}")