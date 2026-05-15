import io
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from app.core.config import settings

LOG_FORMAT   = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
BASE_LOG_DIR = "logs"

# Guard: configure only once even if setup_logging() is called from multiple modules
_CONFIGURED = False


def _get_dynamic_log_path() -> str:
    today      = datetime.now().strftime("%Y-%m-%d")
    target_dir = os.path.join(BASE_LOG_DIR, today)
    os.makedirs(target_dir, exist_ok=True)
    return os.path.join(target_dir, "finagent.log")


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    log_file_path = _get_dynamic_log_path()

    # ── File handler (always UTF-8) ───────────────────────────────────────
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # ── Console handler (UTF-8, safe on Windows CP1252 via errors=replace) ─
    try:
        # Wrap underlying buffer with UTF-8 encoding
        console_stream = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )
        # Keep a module-level reference so GC doesn't close the buffer
        globals()["_console_stream"] = console_stream
    except (AttributeError, ValueError):
        console_stream = sys.stdout

    console_handler = logging.StreamHandler(console_stream)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # ── Root logger ───────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    # Remove any handlers that basicConfig or other modules may have added
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
