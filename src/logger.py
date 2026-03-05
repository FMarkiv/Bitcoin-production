"""
Logging Configuration
=====================
Centralized logging setup for the BTC Tail Model Trading Bot.

Usage:
    from logger import get_logger

    logger = get_logger(__name__)
    logger.info("Message here")
    logger.error("Error occurred", exc_info=True)
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_logger(name: str,
               level: int = logging.INFO,
               log_file: Optional[str] = None) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (usually __name__)
        level: Logging level (default: INFO)
        log_file: Optional file path for logging to file

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Create formatter with timestamp
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def setup_file_logging(log_dir: str = "logs") -> str:
    """
    Setup file logging with daily rotation.

    Args:
        log_dir: Directory for log files

    Returns:
        Path to current log file
    """
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    log_file = log_path / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
    return str(log_file)


# Default logger for quick imports
default_logger = get_logger("btc_tail_bot")
