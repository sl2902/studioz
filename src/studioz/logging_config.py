"""Shared Loguru setup for StudioZ modules"""

import sys

from loguru import logger

def setup_logging(level: str) -> None:
    """Configure the project's shared console logger"""
    logger.remove()  # Remove default logger
    logger.add(
        sys.stderr, 
        level=level.upper(),
        colorize=sys.stderr.isatty(), 
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<cyan>{name}</cyan> | <level>{message}</level>"
        ),
    )