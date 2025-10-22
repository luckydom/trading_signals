"""Logging utilities."""

import logging
import json
from pathlib import Path
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """JSON log formatter."""

    def format(self, record):
        log_obj = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def setup_logging(log_file: str = None, log_level: str = "INFO", json_format: bool = True):
    """
    Setup logging configuration.

    Args:
        log_file: Optional log file path
        log_level: Logging level
        json_format: Use JSON formatting

    Returns:
        Logger instance
    """
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler()
    if json_format:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
    logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        if json_format:
            file_handler.setFormatter(JSONFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )
        logger.addHandler(file_handler)

    return logger