from utils.project import *

def foo():
    error_registrar(exception_type="Exception",severity=1)

def foo2():
    foo()

foo()
foo2()