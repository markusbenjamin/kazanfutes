from utils.project import *

print(settings.get('timestamp_format'))

settings.set('new_custom_setting','val')

print(settings.get('new_custom_setting'))