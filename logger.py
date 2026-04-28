"""Logging setup — console + rotating file."""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(level: str = "INFO"):
    Path("logs").mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Rotating file (10 MB, keep 5)
    fh = logging.handlers.RotatingFileHandler(
        "logs/bot.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Quiet noisy libraries
    for lib in ("aiohttp", "asyncio", "websockets", "urllib3"):
        logging.getLogger(lib).setLevel(logging.WARNING)
