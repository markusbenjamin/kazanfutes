from utils.project import *

system_setup = get_system_setup()
node = JSONNodeAtURL(node_relative_path='system')
node.write({'setup':system_setup},'')
exit()

firebase_node.poll_periodically(interval=1)
while True:
    try:
        time.sleep(0.5)
    except:
        firebase_node.stop_listening()
        exit()