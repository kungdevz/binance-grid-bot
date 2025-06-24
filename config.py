import os
from dotenv import load_dotenv, dotenv_values

load_dotenv()

def _cast_value(val: str):
    lower = val.lower()
    if lower in ("true", "false"):
        return lower == "true"
    if val.isdigit():
        return int(val)
    try:
        return float(val)
    except ValueError:
        return val

raw_env = dotenv_values()  

CONFIG = {
    key: _cast_value(value)
    for key, value in raw_env.items()
    if value is not None
}

CONFIG = { key.lower(): val for key, val in CONFIG.items() }

