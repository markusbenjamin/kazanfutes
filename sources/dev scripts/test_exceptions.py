import traceback
import sys

def get_exception_details(e):
    error_message = str(e)
    _, _, tb = sys.exc_info()
    tb_info = traceback.extract_tb(tb)
    # If the traceback is available, get the last call
    if tb_info:
        filename, line, func, text = tb_info[-1]
    else:
        filename, line, func, text = (None, None, None, None)
    return {
        'error_message': error_message,
        'filename': filename,
        'line': line,
        'function': func,
        'text': text
    }

# Example usage:
try:
    # Some code that may raise an exception
    1 / 0
except Exception as e:
    details = get_exception_details(e)
    print(details)  # or log this information as needed