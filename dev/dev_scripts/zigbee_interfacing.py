from utils.project import *


deconz_access_params = get_deconz_access_params()
base_url = f"{deconz_access_params['api_url']}{deconz_access_params['api_key']}"
lights_url = f"{base_url}/lights"
lights_response = requests.get(lights_url)
lights_info = lights_response.json()

for id, info in lights_info.items():
    #print(id)
    if info['name'] != 'pult':
        try:
            put_response = requests.put(
                f"{lights_url}/{id}/state",
                json={
                    "on":True,
                    "ct":550,
                    "bri":180
                    },
                )
            put_response.raise_for_status()
            print(f"{put_response.status_code} for {put_response.reason}")
        except:
            raise ModuleException(f"cannot put request to {info['name']}")
        

exit()



deconz_session = read_deconz_state()
for light_id, light in deconz_session.lights.items():
    url = f"{deconz_access_params['api_url']}{deconz_access_params['api_key']}/lights/{light_id}/"
    print(light_id)
    try:
        response = requests.get(url)
        response.raise_for_status()

        light_info = response.json()

        print(light_info['state']['on'])
    except Exception:
        raise ModuleException('cannot reach light {light}')

    