from utils.project import *

settings['dev'] = True
settings['verbosity'] = True

try:
    i = 0
    while True:
        time.sleep(1)
        i += 1
        print(i)
        if 4<i:
            faulty_module_function()
except ModuleException as e:
    ServiceException("bla",original_exception=e,severity=1)
except Exception:
    ServiceException("bla")