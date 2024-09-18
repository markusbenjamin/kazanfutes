from utils.project import *

settings.set('verbosity',True)

def foo():
    error_registrar(exception_type="Test exception blabla",severity=1)

foo()