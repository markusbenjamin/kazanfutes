from utils.project import *

settings.set('verbosity',True)

def foo():
    error_registrar(exception_type="Test exception 2",severity=3)

foo()