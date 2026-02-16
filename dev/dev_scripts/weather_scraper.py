from utils.project import *

def get_open_meteo_data(lat:float = 47.4984, lon:float = 19.0405):
    """
    Fetch temperature from current_weather and humidity from hourly relativehumidity_2m
    via Open-Meteo API.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&current_weather=true&hourly=relativehumidity_2m"
    )
    try:
        response = requests.get(url)
        data = response.json()
        # Get current weather temperature
        current_weather = data.get("current_weather", {})        
        temperature = current_weather.get("temperature")
        current_time = current_weather.get("time")
        
        # Extract humidity by matching the current time in the hourly data
        hourly = data.get("hourly", {})
        print(hourly)
        times = hourly.get("time", [])
        humidity_values = hourly.get("relativehumidity_2m", [])
        humidity = None
        if current_time and times:
            if current_time in times:
                idx = times.index(current_time)
                if idx < len(humidity_values):
                    humidity = humidity_values[idx]
            else:
                humidity = humidity_values[0] if humidity_values else None
        return {"temperature": temperature, "humidity": humidity}
    except Exception as e:
        print(f"Error fetching Open-Meteo data: {e}")
        return None

print(get_open_meteo_data())
print(scrape_external_temperature())