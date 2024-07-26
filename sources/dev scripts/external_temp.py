import requests
import json

def external_temperature():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 47.4984,
        "longitude": 19.0405,
        "current_weather": "true"
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        raise Exception(f"Failed to retrieve data: {response.status_code}")
    data = response.json()
    temperature = data['current_weather']['temperature']
    return temperature

print(external_temperature())