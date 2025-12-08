"""
Logging configuration
"""

import logging
import json
from pythonjsonlogger import jsonlogger
from app.config import settings

def get_logger(name: str) -> logging.Logger:
    """Get configured logger"""
    logger = logging.getLogger(name)
    logger.setLevel(settings.LOG_LEVEL)
    
    # JSON formatter
    logHandler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter()
    logHandler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(logHandler)
    
    return logger
