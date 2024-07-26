import json

def simplify_json(input_file, output_file):
    # Load the input JSON file
    with open(input_file, "r") as f:
        data = json.load(f)

    # Extract the desired fields for each device
    simplified_data = [{"name": device["name"], "id": device["id"], "ip": device["ip"], "key": device["key"]} for device in data]

    # Save the simplified data to the specified output file
    with open(output_file, "w") as f:
        json.dump(simplified_data, f, indent=4)

    print(f"Data has been simplified and saved to {output_file}")

if __name__ == "__main__":
    input_path = "devices.json"  # Path to your input JSON file
    output_path = "plug_info.json"  # Path where you want the simplified JSON to be saved
    simplify_json(input_path, output_path)
