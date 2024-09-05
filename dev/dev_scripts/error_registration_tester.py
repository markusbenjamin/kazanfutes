import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
#print("sys.path:", sys.path)

from utils.base import *
import time

errors.error_registrar(exception_type="Exception",severity=1,origin="origin_stamp",origin_timestamp=time.strftime(settings.get_timestamp_format()))