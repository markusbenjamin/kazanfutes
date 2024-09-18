try:
    raise ValueError
except Exception as e:
    exception_name = type(e).__name__
    print(exception_name)  # This will print: "ValueError"