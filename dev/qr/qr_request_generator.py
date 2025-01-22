from utils.project import *
import qrcode
from PIL import Image, ImageDraw, ImageFont
import textwrap

def wrap_text(max_chars, text):
    return "\n".join(textwrap.wrap(text, width=max_chars, break_long_words=False))

#title: params.get("title") || "kérés címe",
#room_name: params.get("room_name") || "szoba neve",
#until: params.get("until") || null,
#temp: params.get("temp") || "hány fok"


base_url = 'https://markusbenjamin.github.io/kazanfutes/send_via_qr_code.html'
types = list(range(0,3))

#room_names = [info['name'] for info in get_rooms_info().values()]
#titles = ['fűtés_délutánig_be','fűtés_éjfélig_be','fűtés_éjfélig_ki']
#untils = ['18','24','24']
#temps = ['21','21','16']

base_url = 'http://127.0.0.1:5500/docs/send_via_qr_code.html'
room_names = ["SZGK"]
titles = ["test"]
untils = ["18"]
temps = [20]

request_titles = []
request_room_names = []
all_requests = []

for room_name in room_names:
    for request_type in range(0,len(titles)):
        request = []
        request.append(f'room_name={room_name}')
        request.append(f'title={titles[request_type]}')
        request.append(f'until={untils[request_type]}')
        request.append(f'temp={temps[request_type]}')
        request.append(f'redirect=1')
        
        full_url = base_url+'?'+'&'.join(request)
        all_requests.append(full_url)
        
        request_room_names.append(f"{room_name}")
        request_titles.append(f"{titles[request_type]}")

        print(full_url)

exit()

for request_num in range(0,len(all_requests)):
    qr = qrcode.QRCode(
        version=4,  # Larger version to accommodate more data
        error_correction=qrcode.constants.ERROR_CORRECT_M,  # Medium error correction
        box_size=12,  # Slightly larger boxes for better scanning
        border=4,  # Standard border size
        )

    qr.add_data(all_requests[request_num])
    qr.make(fit=True)

    qr_img = qr.make_image(fill='black', back_color='white')
 
    title_text = request_titles[request_num].replace('_', ' ')
    font = ImageFont.truetype("arial.ttf", 80)
    
    title_width, title_height = font.getbbox(title_text)[2:]

    h_pad = 10
    v_pad = 10
    total_width = max(qr_img.width*2, title_width) + h_pad  # Add padding for centering
    total_width = 700
    total_height = title_height + qr_img.height + v_pad  # Additional space for padding
    total_height = 900

    combined_img = Image.new('RGB', (total_width, total_height), 'white')

    draw = ImageDraw.Draw(combined_img)

    title_position = (total_width // 2, 20)
    draw.text(title_position, title_text, font=font, fill='black', anchor="mt")

    qr_position = (0, title_height + 20)
    combined_img.paste(qr_img, qr_position)

    room_name_text = request_room_names[request_num]
    font = ImageFont.truetype("arial.ttf", 15)
    room_name_width, room_name_height = font.getbbox(title_text)[2:]
    room_name_position = (room_name_width/2 + 25, title_height + qr_img.height + 10)
    draw.text(room_name_position, room_name_text, font=font, fill='black', anchor="mt")

    save_image(combined_img,f'dev/qr_codes/{request_room_names[request_num]}, {request_titles[request_num].replace('_', ' ')}.png')