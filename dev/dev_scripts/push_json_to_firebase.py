from utils.project import *

setup = load_json_to_dict("system/setup.json")
#print(setup)

system_node = JSONNodeAtURL(node_relative_path='system')
system_node.write(setup,'setup')