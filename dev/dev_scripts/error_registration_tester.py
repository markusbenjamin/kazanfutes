from utils.project import *

settings.set('verbosity',True)

def foo():
    error_registrar(exception_type="Test exception",severity=3)

foo()