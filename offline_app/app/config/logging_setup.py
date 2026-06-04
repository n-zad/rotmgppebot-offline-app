"""Configure console and file logging under offline_app/logs/."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config.settings import AppConfig
from app.paths import ensure_app_dirs, logs_dir


def setup_logging(config: AppConfig) -> None:
    ensure_app_dirs()
    level_name = config.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if config.log_to_file:
        log_file = logs_dir() / "offline_app.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
