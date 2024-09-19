from utils.project import *

def foo2():
	1/0

try:
	foo2()
except ZeroDivisionError as e:
	raise ProjectBaseException("TestException raised.", original_exception = e, severity = 2) from e
except Exception as e:
	raise ProjectBaseException("Test2Exception raised.") from e