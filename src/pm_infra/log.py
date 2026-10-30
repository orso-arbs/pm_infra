"""Rotating log under %LOCALAPPDATA%/pm_infra/logs, plus console echo when wanted."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from pm_infra.paths import logs_dir

_configured = False


def get_logger(name: str = "pm_infra", console: bool = False) -> logging.Logger:
    global _configured
    logger = logging.getLogger("pm_infra")
    if not _configured:
        logger.setLevel(logging.INFO)
        logs_dir().mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            logs_dir() / "pm_infra.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(fh)
        _configured = True
    if console and not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stdout for h in logger.handlers):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(sh)
    return logger.getChild(name) if name != "pm_infra" else logger
