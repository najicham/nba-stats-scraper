import os

def is_local():
    return os.environ.get("ENV", "") == "local"
