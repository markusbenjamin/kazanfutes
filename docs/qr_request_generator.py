from utils.project import *

#title: params.get("title") || "kérés címe",
#room_name: params.get("room_name") || "szoba neve",
#until: params.get("until") || null,
#temp: params.get("temp") || "hány fok"

base_url = 'https://markusbenjamin.github.io/kazanfutes/send_via_qr_code.html'
base_url = 'http://127.0.0.1:5500/docs/send_via_qr_code.html'
types = list(range(0,3))

room_names = [info['name'] for info in get_rooms_info().values()]

titles = ['fűtés délutánig be','fűtés éjfélig be','fűtés éjfélig ki']
untils = ['18','24','24']
temps = ['21','21','16']

for room_name in room_names:
    for request_type in list(range(0,len(titles))):
        request = []
        request.append(f'room_name={room_name}')
        request.append(f'title={titles[request_type]}')
        request.append(f'until={untils[request_type]}')
        request.append(f'temp={temps[request_type]}')
        request.append(f'redirect=1')
        

    print(base_url+'?'+'&'.join(request))