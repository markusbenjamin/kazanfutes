from utils.project import *

try:
	moo()
except ModuleException as e:
	ServiceException("Module exception", original_exception=e, severity = 0)
except Exception as e:
	ServiceException("Unexpected error")