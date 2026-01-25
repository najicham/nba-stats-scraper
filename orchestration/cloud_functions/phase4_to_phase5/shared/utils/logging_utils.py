# shared/utils/logging_utils.py
"""
Centralized logging utilities for NBA platform
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from google.cloud import logging as cloud_logging


def setup_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    """
    Set up structured logging for Cloud Run services
    
    Args:
        service_name: Name of the service (scrapers, processors, reportgen)
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
    
    Returns:
        Configured logger
    """
    # Set up Cloud Logging in production
    if not os.getenv('LOCAL_DEV'):
        cloud_logging.Client().setup_logging()
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(levelname)s:%(name)s:%(message)s'
    )
    
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, level.upper()))
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger with consistent naming"""
    return logging.getLogger(f"nba.{name}")


def log_scraper_step(logger: logging.Logger, step: str, message: str, 
                    run_id: str, extra: Optional[Dict[str, Any]] = None):
    """
    Log a structured scraper step for easy parsing
    
    Args:
        logger: Logger instance
        step: Step name (start, download, transform, export, etc.)
        message: Human readable message
        run_id: Correlation ID for this run
        extra: Additional structured data
    """
    if extra is None:
        extra = {}
    
    log_data = {
        "step": step,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extra
    }
    
    logger.info(f"SCRAPER_STEP {message}", extra=log_data)


def log_scraper_stats(logger: logging.Logger, stats: Dict[str, Any]):
    """
    Log final scraper statistics for monitoring
    
    Args:
        logger: Logger instance  
        stats: Statistics dictionary
    """
    stats_with_meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "scraper_completed",
        **stats
    }
    
    logger.info(f"SCRAPER_STATS {json.dumps(stats_with_meta)}")


def log_error_with_context(logger: logging.Logger, error: Exception, 
                          context: Dict[str, Any]):
    """
    Log errors with rich context for debugging
    
    Args:
        logger: Logger instance
        error: Exception that occurred
        context: Additional context (run_id, operation, etc.)
    """
    error_data = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **context
    }
    
    logger.error(f"ERROR {json.dumps(error_data)}", exc_info=True)

