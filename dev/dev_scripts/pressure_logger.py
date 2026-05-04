"""
Logs the pressure meter.
"""

from utils.project import *

relative_path = 'dev/data/pressure/'

capture_image_to_disk(relative_path,'unprocessed')

image = load_image(relative_path+'unprocessed.jpg')

capture_timestamp = timestamp()
daystamp = datetime.strptime(capture_timestamp,settings["timestamp_format"]).strftime("%Y-%m-%d")
hourminute_stamp = datetime.strptime(capture_timestamp,settings["timestamp_format"]).strftime("%H-%M")

image = image.crop((902, 468, 1040, 606))
image = image.rotate(90, resample=Image.BICUBIC, expand=True) # Rotate with antialiasing


save_image(image, relative_path+'processed.jpg')