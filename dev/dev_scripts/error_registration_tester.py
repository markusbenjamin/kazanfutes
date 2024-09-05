from utils import project

def foo():
    project.error_registrar(exception_type="Exception",severity=1)

def foo2():
    foo()

foo()
foo2()