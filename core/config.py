
import json
from pathlib import Path
from copy import deepcopy


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULT = {
    "mode": "ask",
    "master": {
        "host": "0.0.0.0",
        "port": 8765,
        "auth_token": ""
    },
    "agent": {
        "name": "辅助端-01",
        "master_host": "192.168.1.100",
        "master_port": 8765,
        "auth_token": ""
    },
    "security": {
        "remember_token": False
    },
    "ldconsole_path": "",
    "max_emulators": 2
}


def _merge_dict(default, saved):
    result = deepcopy(default)

    if not isinstance(saved, dict):
        return result

    for key, value in saved.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value

    return result


def load_config():
    if not CONFIG_PATH.exists():
        cfg = deepcopy(DEFAULT)
        save_config(cfg)
        return cfg

    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        saved = {}

    return _merge_dict(DEFAULT, saved)


def save_config(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    temp_path = CONFIG_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp_path.replace(CONFIG_PATH)
