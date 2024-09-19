from utils.project import *

try:
	faulty_module_function()
except ModuleException as e:
	ServiceException("Module exception", original_exception=e, severity = 0)
except Exception as e:
	ServiceException("Unexpected error",severity = 1)