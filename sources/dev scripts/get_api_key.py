# Ez akkor fut le jól, ha az url-be a Phoscon app címe van írva
# és ha a Phoscon appban a Gateway/ConBee II/Advancednél be lett
# nyomva, hogy Authenticate app.
# Illetve ha a pip install requests már lefutott.

import requests
import json

#url = "http://192.168.34.106:80/api" # Fűtés wifin
url = "http://192.168.22.139:80/api"
data = {"devicetype": "pydeconz_example"}

response = requests.post(url, json=data)

if response.status_code == 200:
    api_key = response.json()[0]["success"]["username"]
    print("API key:", api_key)
else:
    print("Error:", response.status_code, response.text)