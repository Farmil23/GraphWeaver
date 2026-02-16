import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from app.core.config import settings

# Format log
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_DIR = "logs"  # Nama folder tempat nyimpen log
LOG_FILE = "graphweaver.log" # Nama filenya

def setup_logging():
    # 1. Buat folder 'logs' kalau belum ada
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    # 2. Siapkan File Handler dengan Rotasi
    # maxBytes=10MB (10 juta byte), backupCount=5 (simpan 5 file terakhir)
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, LOG_FILE), 
        maxBytes=10*1024*1024, 
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # 3. Konfigurasi Global
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),  # Tetap tampil di terminal
            file_handler                        # Simpan ke file juga
        ]
    )

def get_logger(name: str):
    return logging.getLogger(name)