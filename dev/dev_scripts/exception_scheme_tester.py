from utils.project import *

def foo():
	1/0

try:
	foo()
except ZeroDivisionError as e:
	raise ProjectBaseException("TestException raised.", original_exception = e, severity = 1) from e
except Exception as e:
	raise ProjectBaseException("Test2Exception raised.") from e