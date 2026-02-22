import logging
import sys
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from app.core.config import settings

# Konfigurasi Dasar
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
BASE_LOG_DIR = "logs"

def _get_dynamic_log_path():
    """
    Menghasilkan path folder berdasarkan tanggal saat ini (misal: logs/2026-02-17/)
    dan nama file log.
    """
    # Ambil tanggal hari ini
    today = datetime.now().strftime("%Y-%m-%d")
    # Gabungkan path: logs/2026-02-17
    target_dir = os.path.join(BASE_LOG_DIR, today)
    
    # Buat folder jika belum ada
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    
    # Path lengkap file: logs/2026-02-17/graphweaver.log
    return os.path.join(target_dir, "graphweaver.log")

def setup_logging():
    # 1. Dapatkan path file log yang dinamis (otomatis buat folder)
    log_file_path = _get_dynamic_log_path()

    # 2. Siapkan File Handler dengan Rotasi
    file_handler = RotatingFileHandler(
        log_file_path, 
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
            logging.StreamHandler(sys.stdout),  # Tampil di terminal
            file_handler                        # Simpan ke file
        ]
    )

def get_logger(name: str):
    """Mengambil instance logger dan memastikan folder hari ini tersedia."""
    _get_dynamic_log_path()
    return logging.getLogger(name)