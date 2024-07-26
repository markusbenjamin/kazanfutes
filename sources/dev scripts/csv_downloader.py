# room to GID mapping

import csv
import requests


def download_and_save_csv(url, csv_filename, skip_columns=0, delete_header=True):
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        lines = response.content.decode('utf-8-sig').splitlines()

        # Open the file to write to
        with open(csv_filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)

            # Read the CSV from the URL
            reader = csv.reader(lines)

            for row_number, row in enumerate(reader):
                # Skip the header if delete_header is True
                if row_number == 0 and delete_header:
                    continue

                # Write to local CSV, skipping the specified number of columns
                writer.writerow(row[skip_columns:])
    else:
        print(f"Failed to download the CSV. Status code: {response.status_code}")


room_GIDs = [
    0,
    674264149,
    228406814,
    228745025,
    994637352,
    2020257900,
    1236306457
]

download_and_save_csv(
        'https://docs.google.com/spreadsheets/d/e/2PACX-1vTiSvyjKOJk9UdY2OZQLpAfvJiEE2fkH9rc03AEzoqyUcOG1N7Kr_KOtABKeUpLxy3KzcvWjeBcTQ_P/pub?output=csv', 
        'test.csv',
        skip_columns=0, 
        delete_header=True
        )