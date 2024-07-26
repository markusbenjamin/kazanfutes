import os
import ast
import json

def process_log_file(log_file_path):
    with open(log_file_path, 'r') as file:
        for line in file:
            try:
                # Safely evaluate the string representation of the dictionary
                log_entry = ast.literal_eval(line.strip())

                # Convert the dictionary to a JSON string, ensuring proper JSON formatting
                json_entry = json.dumps(log_entry)

                # Extract the date
                date = log_entry['4'].split(' ')[0]
                output_file_path = f'log.{date}'

                # Write the JSON log entry to the corresponding file
                with open(output_file_path, 'a') as output_file:
                    output_file.write(json_entry + '\n')
            except (ValueError, SyntaxError):
                print(f"Skipping invalid line: {line.strip()}")

# Example usage
process_log_file('log_1.log')
process_log_file('log.log')
