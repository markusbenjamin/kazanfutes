from utils.project import *

node = JSONNodeAtURL(node_relative_path='update')
node.write({'bla':True},'bla')
exit()

firebase_node.poll_periodically(interval=1)
while True:
    try:
        time.sleep(0.5)
    except:
        firebase_node.stop_listening()
        exit()