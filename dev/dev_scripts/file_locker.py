from filelock import FileLock

# Path to the file you want to lock
ERROR_REGISTRY_PATH = 'C:/Users/Beno/Documents/SZAKI/dev/kazanfutes/data/errors/error_registry.json'

# Create a FileLock for the JSON file
lock = FileLock(ERROR_REGISTRY_PATH + ".lock")

# Acquire the lock and hold it
with lock:
    print(f"{ERROR_REGISTRY_PATH} is now locked.")
    input("Press Enter to release the lock...")