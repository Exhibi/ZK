import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

ROOT = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger("LanControl")
LOGGER.setLevel(logging.INFO)

def setup_logger():
    if LOGGER.handlers:
        return LOGGER
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(log_dir / "control.log", maxBytes=2*1024*1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOGGER.addHandler(handler)
    return LOGGER

def log(message, level="info"):
    setup_logger()
    getattr(LOGGER, level if level in ("debug","info","warning","error","critical") else "info")(str(message))
