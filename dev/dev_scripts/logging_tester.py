from utils.project import *

init_logger(log_file=os.path.join(get_project_root(),'data','logs','test','test.json'))
log_data({'message':'test log'})