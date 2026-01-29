"""
Gunicorn configuration for prediction coordinator.

Fixes logging to properly forward Python logger output to Cloud Run stdout/stderr.
"""

import logging
import os
import sys

# Server socket - use PORT from environment (Cloud Run sets this)
port = os.environ.get("PORT", "8080")
bind = f"0.0.0.0:{port}"
workers = 1
threads = 8
timeout = 300
worker_class = "sync"

# Logging configuration
loglevel = "info"
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# CRITICAL FIX: Configure Python logging to integrate with gunicorn
# This ensures logger.info(), logger.debug(), etc. appear in Cloud Run logs
logconfig_dict = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'simple': {
            'format': '%(levelname)s - %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'default',
            'stream': sys.stdout,
        },
        'error_console': {
            'class': 'logging.StreamHandler',
            'level': 'WARNING',
            'formatter': 'default',
            'stream': sys.stderr,
        },
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console', 'error_console'],
    },
    'loggers': {
        'gunicorn.error': {
            'level': 'INFO',
            'handlers': ['error_console'],
            'propagate': False,
        },
        'gunicorn.access': {
            'level': 'INFO',
            'handlers': ['console'],
            'propagate': False,
        },
        # Application loggers
        'coordinator': {
            'level': 'INFO',
            'handlers': ['console', 'error_console'],
            'propagate': False,
        },
        'worker': {
            'level': 'INFO',
            'handlers': ['console', 'error_console'],
            'propagate': False,
        },
        'shared.publishers.unified_pubsub_publisher': {
            'level': 'INFO',
            'handlers': ['console', 'error_console'],
            'propagate': False,
        },
    },
}

# Create module-level logger for startup messages
_startup_logger = logging.getLogger('gunicorn.config')

# Log startup info
_startup_logger.info("Gunicorn starting with proper logging configuration")
_startup_logger.info(f"Workers: {workers}, Threads: {threads}, Timeout: {timeout}s")
_startup_logger.info(f"Log level: {loglevel}")
_startup_logger.info(f"Python logging: Configured to forward to stdout/stderr")
